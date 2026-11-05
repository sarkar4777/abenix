#!/usr/bin/env python3
"""Measure knowledge ingest, vector search, Cognify and Atlas against a running stack."""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import random
import statistics
import subprocess
import sys
import time
import uuid

import httpx
import numpy as np

WORDS = [f"w{i}" for i in range(40000)]
WEIGHTS = np.array([1 / (i + 1) for i in range(len(WORDS))])
WEIGHTS = WEIGHTS / WEIGHTS.sum()


def doc_text(kb_bytes: int, rng: np.random.Generator) -> str:
    out: list[str] = []
    size = 0
    while size < kb_bytes * 1024:
        sentence = " ".join(rng.choice(WORDS, size=14, p=WEIGHTS)) + "."
        out.append(sentence)
        size += len(sentence) + 1
    return "\n".join(out)


FIRST = (
    "Jana Omar Priya Lukas Mei Carlos Ingrid Tomas Aisha Henrik Sofia Daniel".split()
)
LAST = (
    "Novak Haddad Sharma Weber Chen Rivera Olsen Dvorak Khan Larsen Rossi Meyer".split()
)
COMPANY_A = "Nordtek Alba Vantor Keystone Helion Brightwater Cobalt Meridian Sable Orion".split()
COMPANY_B = "Steel Castings Hydraulics Logistics Energy Polymers Systems Marine Foods Pharma".split()
SITES = "Brno Leeds Lyon Porto Gdansk Tampere Bilbao Turin Ghent Malmo".split()
PARTS = (
    "hydraulic pump,control valve,turbine blade,gear assembly,pressure sensor".split(
        ","
    )
)


def company_text(kb_bytes: int, rng: np.random.Generator) -> str:
    def pick(items: list[str]) -> str:
        return items[int(rng.integers(len(items)))]

    out: list[str] = []
    size = 0
    while size < kb_bytes * 1024:
        supplier = f"{pick(COMPANY_A)} {pick(COMPANY_B)}"
        buyer = f"{pick(COMPANY_A)} {pick(COMPANY_B)}"
        person = f"{pick(FIRST)} {pick(LAST)}"
        line = (
            f"{supplier} supplies the {pick(PARTS)} to the {pick(SITES)} plant of {buyer} "
            f"under contract CT-{int(rng.integers(100000))}, managed by {person}. "
            f"{person} reports that delivery risk at {pick(SITES)} rose this quarter."
        )
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


def pct(values: list[float], q: float) -> float:
    return round(sorted(values)[min(len(values) - 1, int(len(values) * q))], 1)


class Stack:
    def __init__(self, api: str, email: str, password: str) -> None:
        self.http = httpx.AsyncClient(base_url=api, timeout=300)
        self.email, self.password = email, password
        self.results: dict[str, object] = {}

    async def login(self) -> None:
        r = await self.http.post(
            "/api/auth/login", json={"email": self.email, "password": self.password}
        )
        r.raise_for_status()
        self.http.headers["Authorization"] = (
            "Bearer " + r.json()["data"]["access_token"]
        )

    def note(self, key: str, value: object) -> None:
        self.results[key] = value
        print(f"{key} = {value}", flush=True)


async def pg_connect(namespace: str, port: int):
    import asyncpg

    raw = subprocess.run(
        ["kubectl", "-n", namespace, "get", "secret", "abenix-secrets", "-o", "json"],
        capture_output=True,
        check=True,
    ).stdout
    data = json.loads(raw)["data"]
    url = base64.b64decode(data["DATABASE_URL"]).decode()
    tail = url.split("@", 1)[1].split("/", 1)[1].split("?")[0]
    creds = url.split("//", 1)[1].split("@", 1)[0]
    user, password = creds.split(":", 1)
    return await asyncpg.connect(
        host="127.0.0.1",
        port=port,
        user=user,
        password=password,
        database=tail,
        ssl=False,
        timeout=30,
    )


async def ingest(stack: Stack, pg, args) -> str:
    r = await stack.http.post(
        "/api/knowledge-bases",
        json={"name": f"load-{uuid.uuid4().hex[:6]}", "vector_backend": "pgvector"},
    )
    r.raise_for_status()
    kb = r.json()["data"]["id"]
    if not args.docs:
        return kb
    rng = np.random.default_rng(7)
    semaphore = asyncio.Semaphore(args.upload_concurrency)
    rejected = [0]

    async def one(i: int) -> None:
        maker = company_text if args.corpus == "company" else doc_text
        body = maker(args.doc_kb, rng).encode()
        async with semaphore:
            res = await stack.http.post(
                f"/api/knowledge-bases/{kb}/upload",
                files={"file": (f"doc{i}.txt", body, "text/plain")},
            )
            if res.status_code >= 400:
                rejected[0] += 1

    started = time.time()
    await asyncio.gather(*(one(i) for i in range(args.docs)))
    stack.note("upload_seconds", round(time.time() - started, 1))
    stack.note("upload_rejected", rejected[0])

    last = -1
    still = time.time()
    while time.time() - started < args.ingest_limit:
        row = await pg.fetchrow(
            "SELECT count(*) FILTER (WHERE status::text IN ('READY','ready')) ready,"
            " count(*) FILTER (WHERE status::text IN ('PROCESSING','processing')) busy,"
            " count(*) total FROM documents WHERE kb_id=$1",
            uuid.UUID(kb),
        )
        chunks = await pg.fetchval(
            "SELECT count(*) FROM chunks WHERE collection_id=$1", uuid.UUID(kb)
        )
        print(
            f"  {int(time.time() - started)}s ready={row['ready']} busy={row['busy']}"
            f" chunks={chunks}",
            flush=True,
        )
        if row["busy"] == 0 and row["total"] >= args.docs - rejected[0]:
            break
        if chunks != last:
            last, still = chunks, time.time()
        if time.time() - still > 300:
            stack.note("ingest_stalled_after_s", int(time.time() - started))
            break
        await asyncio.sleep(15)
    elapsed = time.time() - started
    chunks = await pg.fetchval(
        "SELECT count(*) FROM chunks WHERE collection_id=$1", uuid.UUID(kb)
    )
    states = await pg.fetch(
        "SELECT status::text s, count(*) c FROM documents WHERE kb_id=$1 GROUP BY 1",
        uuid.UUID(kb),
    )
    stack.note("doc_states", {r["s"]: r["c"] for r in states})
    stack.note("chunks_ingested", chunks)
    stack.note("ingest_seconds", round(elapsed, 1))
    stack.note("chunks_per_second", round(chunks / max(elapsed, 1), 1))
    stack.note(
        "mb_text_per_minute",
        round(args.docs * args.doc_kb / 1024 / max(elapsed, 1) * 60, 1),
    )
    return kb


async def sizes(stack: Stack, pg, label: str) -> None:
    row = await pg.fetchrow(
        "SELECT count(*) n, pg_table_size('chunks') t, pg_indexes_size('chunks') i"
        " FROM chunks"
    )
    per_row = (row["t"] + row["i"]) / max(row["n"], 1)
    stack.note(
        f"size_{label}",
        {
            "rows": row["n"],
            "table_mb": round(row["t"] / 1048576),
            "indexes_mb": round(row["i"] / 1048576),
            "kb_per_row": round(per_row / 1024, 1),
        },
    )


def centers(k: int = 64, dim: int = 1536) -> np.ndarray:
    rng = np.random.default_rng(11)
    c = rng.normal(size=(k, dim))
    return c / np.linalg.norm(c, axis=1, keepdims=True)


def batch_lines(kb: uuid.UUID, doc: uuid.UUID, start: int, n: int, c: np.ndarray):
    rng = np.random.default_rng(start)
    which = rng.integers(0, len(c), size=n)
    vectors = c[which] + rng.normal(scale=0.03, size=(n, c.shape[1]))
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    out = []
    for i in range(n):
        vec = "[" + ",".join(f"{x:.5f}" for x in vectors[i]) + "]"
        body = " ".join(random.choices(WORDS[:3000], k=120))
        out.append(
            f"{uuid.uuid4()}\t{kb}\t{doc}\t{start + i}\t{body}\t{{}}\t{vec}\n".encode()
        )
    return b"".join(out)


async def load_rows(pg, kb: uuid.UUID, doc: uuid.UUID, start: int, count: int) -> None:
    c = centers()
    size = 5000

    async def source():
        for at in range(start, start + count, size):
            n = min(size, start + count - at)
            yield await asyncio.to_thread(batch_lines, kb, doc, at, n, c)

    await pg.copy_to_table(
        "chunks",
        source=source(),
        columns=[
            "id",
            "collection_id",
            "document_id",
            "chunk_index",
            "content",
            "metadata",
            "embedding",
        ],
        format="text",
    )


async def make_doc(pg, kb: str, name: str) -> uuid.UUID:
    doc = uuid.uuid4()
    await pg.execute(
        "INSERT INTO documents (id, kb_id, filename, file_type, file_size, chunk_count,"
        " status, storage_url, version_number, is_current) VALUES"
        " ($1,$2,$3,'text',1,0,'READY','load://synthetic',1,true)",
        doc,
        uuid.UUID(kb),
        name,
    )
    return doc


async def search_latency(stack: Stack, kb: str, n: int) -> dict:
    seen: list[float] = []
    returned: list[int] = []
    errors = 0
    for i in range(n):
        t0 = time.perf_counter()
        r = await stack.http.post(
            f"/api/knowledge-engines/{kb}/search",
            json={"query": f"w{i} w{i + 7} policy {i}", "mode": "vector", "top_k": 10},
        )
        seen.append((time.perf_counter() - t0) * 1000)
        if r.status_code >= 400:
            errors += 1
            continue
        returned.append(len((r.json().get("data") or {}).get("results") or []))
    return {
        "p50_ms": pct(seen, 0.5),
        "p95_ms": pct(seen, 0.95),
        "avg_results": round(statistics.mean(returned), 1) if returned else 0,
        "errors": errors,
    }


async def vectors(stack: Stack, pg, args) -> None:
    await stack.login()
    r = await stack.http.post(
        "/api/knowledge-bases",
        json={"name": f"ladder-{uuid.uuid4().hex[:6]}", "vector_backend": "pgvector"},
    )
    big = r.json()["data"]["id"]
    doc = await make_doc(pg, big, "ladder.txt")
    index = args.index_name
    have = await pg.fetchval("SELECT to_regclass($1)::text", index)
    stack.note("hnsw_index_present", bool(have))

    # inserts with the live index are the rate a running system really gets
    t0 = time.time()
    await load_rows(pg, uuid.UUID(big), doc, 0, args.live_insert_rows)
    rate = args.live_insert_rows / max(time.time() - t0, 0.1)
    stack.note("rows_per_second_with_live_index", round(rate, 1))

    done = args.live_insert_rows
    for target in [int(x) for x in args.ladder.split(",") if x]:
        if have:
            definition = await pg.fetchval(
                "SELECT indexdef FROM pg_indexes WHERE indexname=$1", index
            )
            await pg.execute(f"DROP INDEX {index}")
        t0 = time.time()
        await load_rows(pg, uuid.UUID(big), doc, done, target - done)
        added, done = target - done, target
        stack.note(
            f"copy_rows_per_second_{target}", round(added / max(time.time() - t0, 0.1))
        )
        stack.note(f"copy_seconds_to_{target}", round(time.time() - t0, 1))
        if have:
            t0 = time.time()
            await pg.execute("SET maintenance_work_mem='2GB'")
            await pg.execute("SET max_parallel_maintenance_workers=4")
            await pg.execute(definition)
            stack.note(f"index_build_seconds_{target}", round(time.time() - t0, 1))
        await pg.execute("ANALYZE chunks")
        await sizes(stack, pg, str(target))
        await stack.login()
        stack.note(
            f"search_big_kb_{target}",
            await search_latency(stack, big, args.queries),
        )
        # a tenant holding one percent of the rows sits behind the post filter
        rs = await stack.http.post(
            "/api/knowledge-bases",
            json={
                "name": f"small-{uuid.uuid4().hex[:6]}",
                "vector_backend": "pgvector",
            },
        )
        small = rs.json()["data"]["id"]
        small_doc = await make_doc(pg, small, "small.txt")
        await load_rows(pg, uuid.UUID(small), small_doc, 0, max(target // 100, 500))
        stack.note(
            f"search_small_kb_{target}",
            await search_latency(stack, small, min(args.queries, 50)),
        )


async def cognify(stack: Stack, pg, args, kb: str) -> None:
    await stack.login()
    rows = await pg.fetch(
        "SELECT d.id::text id FROM documents d WHERE d.kb_id=$1 AND d.chunk_count>0"
        " ORDER BY d.chunk_count LIMIT $2",
        uuid.UUID(kb),
        args.cognify_docs,
    )
    if not rows:
        stack.note("cognify", "no ready documents")
        return
    ids = [r["id"] for r in rows]
    chunks = await pg.fetchval(
        "SELECT count(*) FROM chunks WHERE document_id = ANY($1::uuid[])", ids
    )
    r = await stack.http.post(
        f"/api/knowledge-engines/{kb}/cognify",
        json={"doc_ids": ids, "model": args.cognify_model},
    )
    stack.note("cognify_status", r.status_code)
    if r.status_code >= 400:
        stack.note("cognify_error", r.text[:300])
        return
    job = (r.json().get("data") or {}).get("job_id") or (
        r.json().get("data") or {}
    ).get("id")
    t0 = time.time()
    while time.time() - t0 < args.cognify_limit:
        row = await pg.fetchrow(
            "SELECT status::text s, tokens_used t, cost_usd c, entities_extracted e,"
            " relationships_extracted rel, error_message m FROM cognify_jobs"
            " WHERE id=$1",
            uuid.UUID(job),
        )
        print(f"  cognify {int(time.time() - t0)}s {row['s']}", flush=True)
        if row["s"].lower() in (
            "complete",
            "completed",
            "failed",
            "partial",
            "cancelled",
        ):
            stack.note(
                "cognify_result",
                {
                    "status": row["s"],
                    "chunks": chunks,
                    "seconds": round(time.time() - t0, 1),
                    "seconds_per_chunk": round((time.time() - t0) / max(chunks, 1), 2),
                    "tokens": row["t"],
                    "entities": row["e"],
                    "relationships": row["rel"],
                    "error": (row["m"] or "")[:200],
                },
            )
            return
        await asyncio.sleep(10)
    stack.note("cognify_result", {"status": "still running at the limit"})


async def atlas(stack: Stack, pg, args) -> None:
    await stack.login()
    for size in [int(x) for x in args.atlas.split(",") if x]:
        r = await stack.http.post(
            "/api/atlas/graphs", json={"name": f"load {size}", "description": "load"}
        )
        r.raise_for_status()
        graph = uuid.UUID(r.json()["data"]["graph"]["id"])
        nodes = [uuid.uuid4() for _ in range(size)]
        await pg.executemany(
            "INSERT INTO atlas_nodes (id, graph_id, label, kind, description, properties,"
            " source, tags, recorded_at, created_at, updated_at) VALUES ($1,$2,$3,'concept',"
            "'', '{}'::jsonb, 'user', '[]'::jsonb, now(), now(), now())",
            [(n, graph, f"node {i}") for i, n in enumerate(nodes)],
        )
        await pg.executemany(
            "INSERT INTO atlas_edges (id, graph_id, from_node_id, to_node_id, label,"
            " description, is_directed, properties, source, created_at, updated_at) VALUES"
            " ($1,$2,$3,$4,'related_to','',true,'{}'::jsonb,'user',now(),now())",
            [
                (uuid.uuid4(), graph, nodes[i], nodes[random.randrange(size)])
                for i in range(size)
            ],
        )
        await pg.execute(
            "UPDATE atlas_graphs SET node_count=$2, edge_count=$2 WHERE id=$1",
            graph,
            size,
        )
        t0 = time.perf_counter()
        got = await stack.http.get(f"/api/atlas/graphs/{graph}")
        stack.note(
            f"atlas_{size}_get",
            {
                "status": got.status_code,
                "ms": round((time.perf_counter() - t0) * 1000),
                "mb": round(len(got.content) / 1048576, 1),
            },
        )
        t0 = time.perf_counter()
        added = await stack.http.post(
            f"/api/atlas/graphs/{graph}/nodes",
            json={"label": "one more", "kind": "concept"},
        )
        stack.note(
            f"atlas_{size}_add_node",
            {
                "status": added.status_code,
                "ms": round((time.perf_counter() - t0) * 1000),
            },
        )


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api", default=os.environ.get("API", "http://localhost:8000"))
    ap.add_argument("--email", default="admin@abenix.dev")
    ap.add_argument("--password", default="Admin123456")
    ap.add_argument("--namespace", default="abenix")
    ap.add_argument("--pg-port", type=int, default=15432)
    ap.add_argument("--docs", type=int, default=500)
    ap.add_argument("--doc-kb", type=int, default=40)
    ap.add_argument("--corpus", choices=["words", "company"], default="company")
    ap.add_argument("--upload-concurrency", type=int, default=8)
    ap.add_argument("--ingest-limit", type=int, default=1200)
    ap.add_argument("--live-insert-rows", type=int, default=5000)
    ap.add_argument("--ladder", default="100000,300000")
    ap.add_argument("--index-name", default="ix_chunks_embedding_hnsw")
    ap.add_argument("--queries", type=int, default=100)
    ap.add_argument("--cognify-docs", type=int, default=20)
    ap.add_argument("--cognify-limit", type=int, default=900)
    ap.add_argument("--cognify-model", default="claude-haiku-4-5")
    ap.add_argument("--atlas", default="1000,10000,50000")
    ap.add_argument("--steps", default="ingest,vectors,cognify,atlas")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    stack = Stack(args.api, args.email, args.password)
    await stack.login()
    pg = await pg_connect(args.namespace, args.pg_port)
    steps = args.steps.split(",")
    stack.note(
        "postgres_settings",
        {
            k: await pg.fetchval(f"SHOW {k}")
            for k in ("shared_buffers", "maintenance_work_mem", "effective_cache_size")
        },
    )
    kb = ""
    if "ingest" in steps:
        kb = await ingest(stack, pg, args)
        await sizes(stack, pg, "after_ingest")
        await stack.login()
        stack.note("search_ingested_kb", await search_latency(stack, kb, 30))
    if "cognify" in steps and kb:
        await cognify(stack, pg, args, kb)
    if "vectors" in steps:
        await vectors(stack, pg, args)
    if "atlas" in steps:
        await atlas(stack, pg, args)
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(stack.results, fh, indent=1, default=str)
    await pg.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
