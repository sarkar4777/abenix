"""The enterprise context graph, Atlas as the ontology and Neo4j as its instances."""

from __future__ import annotations

import asyncio
import json
import types
import uuid

import pytest
from atlas_live import client
from kb_pg import make_doc
from kg_stack import cypher_sync

from engine.knowledge import cognify_pipeline as pipeline
from engine.knowledge import cognify_store as store
from engine.knowledge import document_acl
from engine.knowledge.entity_extractor import (
    ChunkExtractionResult,
    ExtractedEntity,
    ExtractedRelationship,
    extract_from_chunk,
)
from engine.knowledge.ontology import BoundOntology, apply_ontology, as_bound, type_key


def _data(r):
    assert r.status_code == 200, r.text
    return r.json()["data"]


class TypedExtractor:
    """Answers with one fitting entity pair and one that the ontology does not have."""

    async def __call__(
        self,
        items,
        doc_id,
        known_entities=None,
        model="",
        ontology=None,
        limiter=None,
        max_parallel=4,
    ):
        self.ontology = ontology
        out = []
        for index, _text in items:
            out.append(
                ChunkExtractionResult(
                    entities=[
                        ExtractedEntity(
                            "Acme Bank", "counterparty", "a bank", index, doc_id
                        ),
                        ExtractedEntity("Trade 42", "TRADE", "a trade", index, doc_id),
                        ExtractedEntity("Lunch", "event", "off topic", index, doc_id),
                    ],
                    relationships=[
                        ExtractedRelationship(
                            "Trade 42", "Acme Bank", "booked_with", "r", index, doc_id
                        ),
                        ExtractedRelationship(
                            "Trade 42", "Lunch", "HAPPENED_AT", "r", index, doc_id
                        ),
                        ExtractedRelationship(
                            "Acme Bank",
                            "Trade 42",
                            "BOOKED_WITH",
                            "wrong way",
                            index,
                            doc_id,
                        ),
                    ],
                    chunk_index=index,
                    doc_id=doc_id,
                    tokens_used=10,
                    cost=0.001,
                )
            )
        return out


@pytest.fixture
def bound(atlas_world, graph, kg_db_url, neo4j_uri):
    w = atlas_world

    async def setup():
        async with client(w.app) as http:
            g = _data(
                await http.post(
                    "/api/atlas/graphs", json={"name": "ctx", "kb_id": w.kb}
                )
            )["graph"]
            base = f"/api/atlas/graphs/{g['id']}"
            c = _data(await http.post(f"{base}/nodes", json={"label": "Counterparty"}))[
                "node"
            ]
            t = _data(await http.post(f"{base}/nodes", json={"label": "Trade"}))["node"]
            e = _data(
                await http.post(
                    f"{base}/edges",
                    json={
                        "from_node_id": t["id"],
                        "to_node_id": c["id"],
                        "label": "booked_with",
                    },
                )
            )["edge"]
            return g, c, t, e

    g, c, t, e = asyncio.run(setup())
    yield types.SimpleNamespace(
        w=w, url=kg_db_url, gid=g["id"], concept=c, trade=t, edge=e, uri=neo4j_uri
    )
    store.dispose_engines()


def _cognify(b, extract, doc=None):
    w = b.w
    job = str(uuid.uuid4())
    w.cur.execute(
        "INSERT INTO cognify_jobs (id, tenant_id, kb_id, status, documents_processed, entities_extracted, "
        "entities_merged, relationships_extracted, tokens_used, cost_usd, anthropic_cost, openai_cost, "
        "google_cost, other_cost) VALUES (%s, %s, %s, 'EXTRACTING', 0,0,0,0,0,0,0,0,0,0)",
        (job, w.tenant, w.kb),
    )
    doc = doc or {
        "id": make_doc(w.cur, w.kb, ["text"]),
        "filename": "a",
        "chunks": ["text"],
    }

    async def run():
        await pipeline.ensure_schema(force=True)
        ontology = await asyncio.to_thread(pipeline.load_active_ontology, w.kb, b.url)
        ctx = pipeline.build_context(w.kb, w.tenant, job, {}, b.url, ontology=ontology)
        ctx.extract = extract
        ctx.threshold = 0.0
        return await pipeline.cognify_document(ctx, doc), ontology

    return asyncio.run(run())


def test_extraction_is_typed_by_the_bound_atlas_and_entities_map_to_concepts(bound):
    outcome, ontology = _cognify(bound, TypedExtractor())
    assert ontology.source == "atlas" and ontology.graph_id == bound.gid
    assert {t["name"] for t in ontology.entity_types} == {"Counterparty", "Trade"}
    assert (
        outcome.off_ontology == 3
    ), "Lunch, its edge and the wrong way edge are dropped"

    rows = cypher_sync(
        bound.uri,
        "MATCH (e:Entity {kb_id: $k}) RETURN e.canonical_name AS n, e.entity_type AS t, "
        "e.atlas_concept_id AS c, e.atlas_graph_id AS g ORDER BY n",
        k=bound.w.kb,
    )
    assert [(r["n"], r["t"], r["c"]) for r in rows] == [
        ("Acme Bank", "Counterparty", bound.concept["id"]),
        ("Trade 42", "Trade", bound.trade["id"]),
    ]
    assert rows[0]["g"] == bound.gid
    rels = cypher_sync(
        bound.uri,
        "MATCH (a:Entity {kb_id: $k})-[r]->(b) RETURN type(r) AS t, r.atlas_edge_id AS e",
        k=bound.w.kb,
    )
    assert rels == [{"t": "BOOKED_WITH", "e": bound.edge["id"]}]
    bound.w.cur.execute(
        "SELECT canonical_name, atlas_concept_id FROM graph_entities WHERE kb_id = %s ORDER BY 1",
        (bound.w.kb,),
    )
    assert [str(r[1]) for r in bound.w.cur.fetchall()] == [
        bound.concept["id"],
        bound.trade["id"],
    ]


def test_atlas_shows_counts_and_browses_and_queries_real_neo4j(bound, monkeypatch):
    _cognify(bound, TypedExtractor())
    w = bound.w
    base = f"/api/atlas/graphs/{bound.gid}"

    async def hidden_nothing(*_a, **_k):
        return set()

    monkeypatch.setattr(document_acl, "hidden_for_search", hidden_nothing)

    async def go():
        async with client(w.app) as http:
            ctx = _data(await http.get(f"{base}/context"))
            page = _data(
                await http.get(
                    f"{base}/entities", params={"concept_id": bound.concept["id"]}
                )
            )
            found = _data(await http.get(f"{base}/entities", params={"q": "trade"}))
            hood = _data(
                await http.get(
                    f"{base}/entities/neighbourhood", params={"name": "Acme Bank"}
                )
            )
            q = _data(
                await http.post(
                    f"{base}/entities/query",
                    json={
                        "from": "Trade",
                        "relationship": "booked_with",
                        "to": "Counterparty",
                    },
                )
            )
            return ctx, page, found, hood, q

    ctx, page, found, hood, q = asyncio.run(go())
    assert ctx["bound"] and ctx["kb_id"] == w.kb and ctx["neo4j_available"]
    counts = {c["label"]: c["entity_count"] for c in ctx["concepts"]}
    assert counts == {"Counterparty": 1, "Trade": 1}
    assert ctx["mapped_entities"] == 2 and ctx["unmapped_entities"] == 0
    assert ctx["neo4j_entity_count"] == 2 and ctx["relationship_count"] == 1
    assert [e["name"] for e in page["entities"]] == ["Acme Bank"] and page[
        "source"
    ] == "neo4j"
    assert [e["name"] for e in found["entities"]] == ["Trade 42"]
    assert hood["entity"]["name"] == "Acme Bank"
    assert (
        hood["neighbours"][0]["name"] == "Trade 42"
        and hood["neighbours"][0]["outgoing"] is False
    )
    assert q["matches"] == [
        {
            "source": "Trade 42",
            "source_type": "Trade",
            "relationship": "BOOKED_WITH",
            "weight": 1.0,
            "target": "Acme Bank",
            "target_type": "Counterparty",
        }
    ]


def test_entities_from_documents_the_user_cannot_see_stay_hidden(bound, monkeypatch):
    w = bound.w
    doc = {"id": make_doc(w.cur, w.kb, ["text"]), "filename": "s", "chunks": ["text"]}
    _cognify(bound, TypedExtractor(), doc)

    async def hide(*_a, **_k):
        return {doc["id"]}

    monkeypatch.setattr(document_acl, "hidden_for_search", hide)

    async def go():
        async with client(w.app) as http:
            return (
                _data(await http.get(f"/api/atlas/graphs/{bound.gid}/entities")),
                await http.get(
                    f"/api/atlas/graphs/{bound.gid}/entities/neighbourhood",
                    params={"name": "Acme Bank"},
                ),
            )

    page, hood = asyncio.run(go())
    assert page["entities"] == [] and hood.status_code == 404


def test_an_unbound_atlas_says_so_and_governance_can_be_turned_off(bound):
    w = bound.w

    async def go():
        async with client(w.app) as http:
            g = _data(await http.post("/api/atlas/graphs", json={"name": "free"}))[
                "graph"
            ]
            ctx = _data(await http.get(f"/api/atlas/graphs/{g['id']}/context"))
            browse = await http.get(f"/api/atlas/graphs/{g['id']}/entities")
            await http.post(
                f"/api/atlas/graphs/{bound.gid}/bind-kb",
                json={"kb_id": w.kb, "governs_extraction": False},
            )
            return ctx, browse

    ctx, browse = asyncio.run(go())
    assert ctx["bound"] is False and ctx["concepts"] == []
    assert browse.status_code == 400 and "Bind this atlas" in browse.text
    assert pipeline.load_active_ontology(w.kb, bound.url) is None


def test_a_graph_in_another_tenant_cannot_govern_this_kb(bound):
    w = bound.w
    from kb_pg import make_tenant

    from atlas_live import make_user

    other = make_tenant(w.cur)
    stranger = make_user(w.cur, other)
    w.cur.execute(
        "UPDATE atlas_graphs SET settings = '{\"governs_extraction\": false}' WHERE id = %s",
        (bound.gid,),
    )
    gid = str(uuid.uuid4())
    w.cur.execute(
        "INSERT INTO atlas_graphs (id, tenant_id, owner_user_id, name, description, kb_id, version, node_count, edge_count, settings) "
        "VALUES (%s, %s, %s, 'x', '', %s, 1, 1, 0, '{}')",
        (gid, other, str(stranger.id), w.kb),
    )
    w.cur.execute(
        "INSERT INTO atlas_nodes (id, graph_id, label, kind, description, properties, source, tags, recorded_at) "
        "VALUES (gen_random_uuid(), %s, 'Evil', 'concept', '', '{}', 'user', '[]', now())",
        (gid,),
    )
    assert pipeline.load_active_ontology(w.kb, bound.url) is None


def test_the_prompt_carries_the_ontology(monkeypatch):
    seen = {}

    class _Router:
        async def complete(self, messages, system, model, temperature, max_tokens=None):
            seen["system"] = system
            return types.SimpleNamespace(
                content=json.dumps({"entities": [], "relationships": []}),
                input_tokens=1,
                output_tokens=1,
                cost=0.0,
            )

    import engine.llm_router as lr

    monkeypatch.setattr(lr, "LLMRouter", _Router)
    onto = BoundOntology(
        entity_types=[{"name": "Counterparty", "description": "a party"}],
        relationship_types=[
            {"name": "booked_with", "from": "Trade", "to": "Counterparty"}
        ],
    )
    out = asyncio.run(extract_from_chunk("text", 0, "d", ontology=onto))
    assert out.error is None
    assert "Counterparty: a party" in seen["system"]
    assert "booked_with (from Trade to Counterparty)" in seen["system"]


def test_ontology_matching_ignores_case_and_spacing():
    assert (
        type_key("Legal Entity") == type_key("legal_entity") == type_key("LegalEntity")
    )
    onto = BoundOntology(entity_types=[{"name": "LegalEntity", "concept_id": "c1"}])
    assert onto.map_entity("legal entity") == ("LegalEntity", "c1")
    assert onto.map_entity("planet") is None
    guided = BoundOntology(entity_types=[{"name": "LegalEntity"}], strict=False)
    assert guided.map_entity("planet") == ("planet", None)
    assert as_bound({"entity_types": [], "relationship_types": []}) is None
    assert as_bound(None) is None


def test_no_ontology_changes_nothing():
    result = ChunkExtractionResult([ExtractedEntity("A", "x", "", 0, "d")], [], 0, "d")
    assert apply_ontology(result, None) == 0 and len(result.entities) == 1


def test_agent_tools_read_entities_and_a_diff_snapshot(bound, monkeypatch):
    from engine.tools import atlas_tools

    _cognify(bound, TypedExtractor())
    w = bound.w
    monkeypatch.setenv("DATABASE_URL", bound.url)
    monkeypatch.setattr(atlas_tools, "_POOL", None)

    async def hidden_nothing(*_a, **_k):
        return set()

    monkeypatch.setattr(document_acl, "hidden_for_search", hidden_nothing)
    base = f"/api/atlas/graphs/{bound.gid}"

    async def go():
        async with client(w.app) as http:
            snap = _data(await http.post(f"{base}/snapshots", json={"label": "first"}))
            w.cur.execute(
                "UPDATE atlas_snapshots SET created_at = now() - interval '1 hour' WHERE id = %s",
                (snap["id"],),
            )
            w.cur.execute(
                "UPDATE atlas_graphs SET created_at = now() - interval '2 hours' WHERE id = %s",
                (bound.gid,),
            )
            await http.post(f"{base}/nodes", json={"label": "Later"})
        tenant = w.tenant
        instances = atlas_tools.AtlasInstancesTool(
            tenant_id=tenant, allowed_graph_ids=[bound.gid]
        )
        listed = await instances.execute({"concept": "Trade"})
        hood = await instances.execute({"name": "Acme Bank", "neighbours": True})
        typed = await instances.execute(
            {
                "concept": "Trade",
                "relationship": "booked_with",
                "to_concept": "Counterparty",
            }
        )
        described = await atlas_tools.AtlasDescribeTool(
            tenant_id=tenant, allowed_graph_ids=[bound.gid]
        ).execute({})
        from datetime import datetime, timedelta, timezone

        past = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        as_of = await atlas_tools.AtlasAsOfTool(
            tenant_id=tenant, allowed_graph_ids=[bound.gid]
        ).execute({"as_of": past})
        await (await atlas_tools._pool()).close()
        return listed, hood, typed, described, as_of

    listed, hood, typed, described, as_of = asyncio.run(go())
    assert [e["name"] for e in json.loads(listed.content)["entities"]] == ["Trade 42"]
    assert json.loads(hood.content)["neighbours"][0]["name"] == "Trade 42"
    assert json.loads(typed.content)["matches"][0]["target"] == "Acme Bank"
    counts = json.loads(described.content)["context_graph"]["entities_by_concept"]
    assert counts == {"Counterparty": 1, "Trade": 1}
    snapshot = json.loads(as_of.content)
    assert snapshot["source"] == "snapshot" and snapshot["found"]
    assert {n["label"] for n in snapshot["nodes"]} == {"Counterparty", "Trade"}
    assert snapshot["edges"][0]["label"] == "booked_with"
