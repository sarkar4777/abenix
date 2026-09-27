"""Seed knowledge-base collections + sample documents from YAML.

Loads every `kb/*.yaml` file and ensures:

  1. The KnowledgeProject exists for `project.slug` under the shared tenant.
  2. Each collection in `collections[]` exists as a KnowledgeBase row.
  3. Each agent listed in `agent_slugs[]` has an AgentCollectionGrant.
  4. Each document in `documents[]` is upserted by `doc.id`.

Idempotent: running twice is a no-op. Documents are upserted by stable id,
never duplicated, and a document that already has chunks is left alone.
Chunking and embedding happen here, with the same splitter the worker uses, so
a seeded collection is searchable the moment the deploy finishes.

Without this seed every standalone (ResolveAI, ClaimsIQ, Industrial IoT)
sees `knowledge_search → results=0` because no collection rows exist
for the tenant. After seeding, the new structured `no_match` vs.
`no_kb_configured` warnings let agents distinguish "searched, found
nothing" from "nothing wired" — and policy-research / resolution-planner
emit non-empty fallbacks instead of silently returning [].
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select, text as _sql
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.agent import Agent  # noqa: E402
from models.collection_grant import (  # noqa: E402
    AgentCollectionGrant,
    CollectionPermission,
)
from models.knowledge_base import (  # noqa: E402
    Document,
    DocumentStatus,
    KBStatus,
    KnowledgeBase,
)
from models.knowledge_project import (  # noqa: E402
    CollectionVisibility,
    KnowledgeProject,
)
from models.tenant import Tenant  # noqa: E402
from models.user import User  # noqa: E402

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix",
)
SEEDS_DIR = Path(__file__).parent / "kb"
SHARED_TENANT_NAME = "Abenix"


async def _get_shared_tenant_user(db: AsyncSession) -> tuple[Tenant, User]:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.name == SHARED_TENANT_NAME))
    ).scalar_one_or_none()
    if tenant is None:
        raise RuntimeError(
            "Abenix tenant missing — run seed_agents.py before seed_kb.py."
        )
    system_user = (
        await db.execute(select(User).where(User.email == "system@abenix.dev"))
    ).scalar_one_or_none()
    if system_user is None:
        raise RuntimeError("system@abenix.dev user missing — seed_agents first.")
    return tenant, system_user


async def _upsert_project(
    db: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, spec: dict[str, Any]
) -> KnowledgeProject:
    proj = (
        await db.execute(
            select(KnowledgeProject).where(
                KnowledgeProject.tenant_id == tenant_id,
                KnowledgeProject.slug == spec["slug"],
            )
        )
    ).scalar_one_or_none()
    if proj is None:
        proj = KnowledgeProject(
            tenant_id=tenant_id,
            name=spec.get("name") or spec["slug"],
            slug=spec["slug"],
            description=spec.get("description") or "",
            created_by=user_id,
        )
        db.add(proj)
        await db.flush()
        print(f"  + project {proj.slug}")
    return proj


async def _upsert_collection(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project: KnowledgeProject,
    user_id: uuid.UUID,
    spec: dict[str, Any],
) -> KnowledgeBase:
    name = spec["name"]
    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.tenant_id == tenant_id,
                KnowledgeBase.project_id == project.id,
                KnowledgeBase.name == name,
            )
        )
    ).scalar_one_or_none()
    if kb is None:
        kb = KnowledgeBase(
            tenant_id=tenant_id,
            project_id=project.id,
            name=name,
            description=spec.get("description") or "",
            default_visibility=CollectionVisibility(
                spec.get("default_visibility", "project")
            ),
            vector_backend=spec.get("vector_backend", "pgvector"),
            status=KBStatus.READY,
            doc_count=0,
            created_by=user_id,
        )
        db.add(kb)
        await db.flush()
        print(f"    + collection {name} ({spec['slug']})")
    return kb


async def _grant_agents(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    collection: KnowledgeBase,
    slugs: list[str],
    permission: str,
) -> None:
    if not slugs:
        return
    rows = await db.execute(
        select(Agent).where(Agent.tenant_id == tenant_id, Agent.slug.in_(slugs))
    )
    agents = rows.scalars().all()
    if not agents:
        return
    # ON CONFLICT DO NOTHING handles idempotency atomically — survives
    # concurrent re-runs and dodges the autoflush-vs-unique-constraint
    # race that previously aborted the whole transaction.
    for agent in agents:
        stmt = (
            pg_insert(AgentCollectionGrant.__table__)
            .values(
                id=uuid.uuid4(),
                agent_id=agent.id,
                collection_id=collection.id,
                permission=CollectionPermission(permission).value,
                granted_by=user_id,
            )
            .on_conflict_do_nothing(index_elements=["agent_id", "collection_id"])
        )
        await db.execute(stmt)


# Collection name -> seed documents that never became searchable chunks.
_PENDING_DOCS: dict[str, int] = {}


def _chunk(text: str, size: int = 1000, overlap: int = 200) -> list[str]:
    """Same splitter the worker uses, so seeded and uploaded chunks match."""
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        return RecursiveCharacterTextSplitter(
            chunk_size=size,
            chunk_overlap=overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
        ).split_text(text)
    except ImportError:
        # Seeding runs in the API pod, which may not carry the worker's
        # dependencies. Paragraph splitting is coarser but keeps the seed
        # working rather than skipping it.
        out, buf = [], ""
        for para in text.split("\n\n"):
            if len(buf) + len(para) > size and buf:
                out.append(buf.strip())
                buf = buf[-overlap:] if overlap else ""
            buf += para + "\n\n"
        if buf.strip():
            out.append(buf.strip())
        return out or [text]


def _embed(texts: list[str]) -> tuple[list[list[float]], str] | None:
    """Embed with whatever provider is configured. None when none is."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        try:
            import openai

            model = "text-embedding-3-small"
            client = openai.OpenAI(api_key=key)
            out: list[list[float]] = []
            # The endpoint takes batches, and 64 seed docs is a few hundred
            # chunks — one call each would be slow and needlessly rate-limited.
            for i in range(0, len(texts), 64):
                resp = client.embeddings.create(model=model, input=texts[i : i + 64])
                out.extend(d.embedding for d in resp.data)
            return out, model
        except Exception as exc:  # noqa: BLE001
            print(f"      (embedding provider failed: {type(exc).__name__}: {exc})")
    try:
        from local_embeddings import embed_many, embedder_id, is_enabled

        if is_enabled():
            return embed_many(texts), embedder_id()
    except Exception:  # noqa: BLE001
        pass
    return None


async def _upsert_documents(
    db: AsyncSession,
    *,
    collection: KnowledgeBase,
    documents: list[dict[str, Any]],
) -> int:
    """Write each seed document and its embedded chunks.

    This used to be a deliberate no-op, on the reasoning that chunking and
    embedding belonged to the ingestion pipeline rather than to raw SQL. The
    effect was 64 showcase documents that existed only as YAML: every
    collection empty, and every agent that calls knowledge_search answering
    that it cannot look anything up. Since the `chunks` table is now created
    at boot and an embedder is always reachable, seeding can do the real work.

    Returns the number of documents that could NOT be made searchable, so the
    caller can say so plainly instead of leaving it to be discovered.
    """
    if not documents:
        return 0

    specs = []
    for doc in documents:
        body = (doc.get("content") or "").strip()
        if not body:
            continue
        specs.append((doc, doc.get("title") or doc.get("id") or "untitled", body))
    if not specs:
        return 0

    stable_ids = {str(d.get("id") or "") for d, _, _ in specs}
    existing = (
        (
            await db.execute(
                select(Document).where(
                    Document.kb_id == collection.id,
                    Document.filename.in_([f"{s}.md" for s in stable_ids if s]),
                )
            )
        )
        .scalars()
        .all()
    )
    done = {d.filename for d in existing if d.chunk_count > 0}

    todo = [(d, t, b) for d, t, b in specs if f"{d.get('id')}.md" not in done]
    if not todo:
        print(f"      ({len(specs)} doc(s) already indexed)")
        return 0

    all_chunks: list[str] = []
    spans: list[tuple[int, int]] = []
    for _doc, title, body in todo:
        # The title goes in the chunk text: retrieval on "return policy"
        # should find the return policy even when the body never repeats
        # its own heading.
        parts = _chunk(f"{title}\n\n{body}")
        spans.append((len(all_chunks), len(all_chunks) + len(parts)))
        all_chunks.extend(parts)

    embedded = _embed(all_chunks)
    if embedded is None:
        print(f"      ({len(todo)} doc(s) NOT ingested — no embedding provider)")
        return len(todo)
    vectors, model = embedded

    if collection.embedding_model != model:
        collection.embedding_model = model

    written = 0
    for (doc, title, body), (lo, hi) in zip(todo, spans):
        stable = str(doc.get("id") or uuid.uuid4())
        row = next((d for d in existing if d.filename == f"{stable}.md"), None)
        if row is None:
            row = Document(
                id=uuid.uuid4(),
                kb_id=collection.id,
                filename=f"{stable}.md",
                file_type="md",
                file_size=len(body.encode("utf-8")),
                chunk_count=0,
                status=DocumentStatus.PROCESSING,
                storage_url=f"seed://{collection.id}/{stable}",
            )
            db.add(row)
            await db.flush()

        await db.execute(
            _sql("DELETE FROM chunks WHERE document_id = :d").bindparams(d=row.id)
        )
        meta_base = dict(doc.get("metadata") or {})
        meta_base.update({"filename": f"{stable}.md", "title": title, "source": "seed"})
        for offset, idx in enumerate(range(lo, hi)):
            meta = dict(meta_base)
            meta["chunk_index"] = offset
            meta["text_preview"] = all_chunks[idx][:200]
            await db.execute(
                _sql(
                    """
                    INSERT INTO chunks
                        (id, collection_id, document_id, chunk_index, content,
                         metadata, embedding)
                    VALUES (:id, :cid, :did, :ix, :content,
                            CAST(:meta AS jsonb), CAST(:emb AS vector))
                    ON CONFLICT (document_id, chunk_index) DO UPDATE
                        SET content = EXCLUDED.content,
                            metadata = EXCLUDED.metadata,
                            embedding = EXCLUDED.embedding
                    """
                ).bindparams(
                    id=uuid.uuid4(),
                    cid=collection.id,
                    did=row.id,
                    ix=offset,
                    content=all_chunks[idx],
                    meta=_json.dumps(meta),
                    emb="[" + ",".join(f"{x:.7f}" for x in vectors[idx]) + "]",
                )
            )
        row.chunk_count = hi - lo
        row.status = DocumentStatus.READY
        written += 1

    collection.doc_count = (
        await db.execute(
            _sql("SELECT count(*) FROM documents WHERE kb_id = :k").bindparams(
                k=collection.id
            )
        )
    ).scalar() or 0
    print(f"      ({written} doc(s) indexed, {len(all_chunks)} chunks, {model})")
    return 0


async def seed_kb() -> None:
    if not SEEDS_DIR.exists():
        print(f"No KB seed dir at {SEEDS_DIR}")
        return
    yaml_files = sorted(SEEDS_DIR.glob("*.yaml"))
    if not yaml_files:
        print(f"No KB seed YAML files in {SEEDS_DIR}")
        return

    engine = create_async_engine(DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    failures: list[str] = []
    # One session per YAML file with a clean commit boundary.
    # If one file's seed hits a UNIQUE / autoflush issue, it shouldn't
    # poison the whole bootstrap — log it, move on.
    for yf in yaml_files:
        with open(yf, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data:
            continue
        print(f"Seeding KB {yf.name} ...")
        try:
            async with factory() as db:
                tenant, user = await _get_shared_tenant_user(db)
                proj_spec = data.get("project") or {}
                project = await _upsert_project(
                    db, tenant_id=tenant.id, user_id=user.id, spec=proj_spec
                )
                for c_spec in data.get("collections") or []:
                    # Each collection gets its own savepoint so a single
                    # bad collection doesn't take the whole project down.
                    async with db.begin_nested():
                        kb = await _upsert_collection(
                            db,
                            tenant_id=tenant.id,
                            project=project,
                            user_id=user.id,
                            spec=c_spec,
                        )
                        await db.flush()
                        await _grant_agents(
                            db,
                            tenant_id=tenant.id,
                            user_id=user.id,
                            collection=kb,
                            slugs=c_spec.get("agent_slugs") or [],
                            permission=c_spec.get("agent_permission", "READ"),
                        )
                        await db.flush()
                        pending = await _upsert_documents(
                            db,
                            collection=kb,
                            documents=c_spec.get("documents") or [],
                        )
                        if pending:
                            _PENDING_DOCS[kb.name] = pending
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{yf.name}: {type(exc).__name__}: {exc}"[:300])
            print(f"  [warn] {yf.name} failed — {type(exc).__name__}: {str(exc)[:200]}")
    await engine.dispose()
    if failures:
        print(f"KB seed complete with {len(failures)} failure(s):")
        for line in failures:
            print(f"  - {line}")
        # Don't fail the whole deploy — agents/users seeding already
        # succeeded. KB is best-effort. Future invocations are idempotent.
        return
    print("KB seed complete.")
    _warn_if_collections_empty()


def _warn_if_collections_empty() -> None:
    """Say it out loud when the collections went in with no content."""
    if not _PENDING_DOCS:
        return
    total = sum(_PENDING_DOCS.values())
    print("")
    print(
        f"  WARNING: {total} seed document(s) across "
        f"{len(_PENDING_DOCS)} collection(s) were NOT ingested."
    )
    print("  Collections and agent grants exist, but there is nothing to search.")
    print("  Agents that rely on knowledge_search will answer that they cannot")
    print("  look anything up:")
    for name in sorted(_PENDING_DOCS):
        print(f"    - {name}")
    print("  Ingestion needs an embedding provider — set OPENAI_API_KEY, or set")
    print("  ABENIX_LOCAL_EMBEDDINGS=1 for the offline hashing embedder — then")
    print("  re-run this seed.")


if __name__ == "__main__":
    asyncio.run(seed_kb())
