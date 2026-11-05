"""Graph writes and retrieval against real Neo4j."""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from kg_stack import cypher_sync

from engine.knowledge import graph_writer as gw
from engine.knowledge import hybrid_search as hs
from engine.knowledge import neo4j_client as nc
from engine.knowledge.entity_resolver import ResolvedEntity, ResolvedRelationship


def _ent(name, docs=(), aliases=(), kind="organization", **props):
    return ResolvedEntity(
        canonical_name=name,
        entity_type=kind,
        description=f"{name} desc",
        aliases=list(aliases),
        source_doc_ids=list(docs),
        properties=props,
    )


def _rel(a, b, docs=(), kind="WORKS_WITH", weight=1.0):
    return ResolvedRelationship(
        source=a,
        target=b,
        relationship_type=kind,
        description="r",
        source_doc_ids=list(docs),
        weight=weight,
    )


def _run(coro):
    async def wrapped():
        await nc.ensure_schema(force=True)
        return await coro()

    return asyncio.run(wrapped())


def _kb():
    return str(uuid.uuid4())


def test_schema_has_the_fulltext_index_and_keeps_the_composite_constraint(
    graph, neo4j_uri
):
    _run(lambda: asyncio.sleep(0))
    rows = cypher_sync(
        neo4j_uri,
        "SHOW INDEXES YIELD name, type, properties RETURN name, type, properties",
    )
    by_name = {r["name"]: r for r in rows}
    assert by_name[nc.FULLTEXT_INDEX]["type"] == "FULLTEXT"
    assert set(by_name[nc.FULLTEXT_INDEX]["properties"]) == {
        "canonical_name",
        "aliases",
        "kb_token",
    }
    assert "entity_kb_name" in by_name


def test_aliases_are_found_through_the_index_and_only_in_that_kb(graph):
    kb, other = _kb(), _kb()

    async def go():
        await gw.write_entities(
            kb,
            [_ent("International Business Machines", aliases=["IBM"])],
            tenant_id="t1",
        )
        await gw.write_entities(
            other, [_ent("IBM Clone", aliases=["IBM"])], tenant_id="t1"
        )
        results, found = await hs._graph_search(["IBM"], [kb], tenant_id="t1")
        missing, _ = await hs._graph_search(["IBM"], [_kb()], tenant_id="t1")
        return results, found, missing

    results, found, missing = _run(go)
    assert found == ["International Business Machines"] and not missing
    assert all("Clone" not in r.content for r in results)


def test_another_tenant_cannot_read_a_kb_even_with_its_id(graph):
    kb = _kb()

    async def go():
        await gw.write_entities(
            kb, [_ent("Acme"), _ent("Globex")], tenant_id="tenant-a"
        )
        await gw.write_relationships(kb, [_rel("Acme", "Globex")])
        same, _ = await hs._graph_search(["Acme"], [kb], tenant_id="tenant-a")
        other, _ = await hs._graph_search(["Acme"], [kb], tenant_id="tenant-b")
        page = await nc.browse_entities(kb, tenant_id="tenant-b")
        hood = await nc.entity_neighbourhood(kb, "Acme", tenant_id="tenant-b")
        return same, other, page, hood

    same, other, page, hood = _run(go)
    assert same and not other
    assert page["entities"] == [] and hood["entity"] is None


def test_a_hub_with_thousands_of_neighbours_stays_capped_and_quick(graph):
    kb = _kb()
    spokes = [f"Spoke {i:05d}" for i in range(5000)]

    async def go():
        await gw.write_entities(
            kb, [_ent("Hub")] + [_ent(s) for s in spokes], tenant_id="t"
        )
        await gw.write_relationships(kb, [_rel("Hub", s) for s in spokes])
        started = time.monotonic()
        results, _ = await hs._graph_search(["Hub"], [kb], depth=4, tenant_id="t")
        return results, time.monotonic() - started

    results, seconds = _run(go)
    context = [r for r in results if r.source_type == "graph_context"]
    assert len(context) <= hs.GRAPH_RESULT_CAP
    assert seconds < 3


def test_traversal_honours_acls_at_every_hop(graph):
    kb = _kb()
    secret = "secret-doc"

    async def go():
        await gw.write_entities(
            kb,
            [_ent("A", ["open"]), _ent("B", [secret]), _ent("C", ["open"])],
            tenant_id="t",
        )
        await gw.write_relationships(
            kb, [_rel("A", "B", ["open"]), _rel("B", "C", ["open"])]
        )
        results, _ = await hs._graph_search(
            ["A"], [kb], depth=3, hidden={secret}, tenant_id="t"
        )
        return results

    results = _run(go)
    assert not [r for r in results if r.source in ("B", "C")]


def test_failed_rows_are_counted_and_the_rest_of_the_batch_lands(graph):
    kb = _kb()

    async def go():
        await gw.write_entities(kb, [_ent("Known")], tenant_id="t")
        return await gw.write_relationships(
            kb,
            [_rel("Known", "Known"), _rel("Known", "Ghost")],
        )

    stats = _run(go)
    assert stats.written == 1 and stats.failed == 1
    assert "endpoint missing" in stats.errors[0]


def test_writes_are_batched_with_a_bounded_size(graph):
    kb = _kb()
    seen = []
    real = gw._write

    async def spy(driver, statement, batch, **params):
        seen.append(len(batch))
        return await real(driver, statement, batch, **params)

    async def go():
        gw._write = spy
        try:
            names = [f"N{i}" for i in range(1200)]
            await gw.write_entities(kb, [_ent(n) for n in names], tenant_id="t")
            return await gw.write_relationships(
                kb, [_rel(names[0], n) for n in names[1:]]
            )
        finally:
            gw._write = real

    stats = _run(go)
    assert stats.written == 1199 and max(seen) <= gw.RELATIONSHIP_BATCH_SIZE
    assert len(seen) >= 6


def test_a_poison_row_fails_alone(graph, monkeypatch):
    kb = _kb()
    real = gw._write

    async def poison(driver, statement, batch, **params):
        if any(r.get("canonical_name") == "Bad" for r in batch):
            raise ValueError("rejected")
        return await real(driver, statement, batch, **params)

    monkeypatch.setattr(gw, "_write", poison)

    async def go():
        return await gw.write_entities(
            kb, [_ent(f"N{i}") for i in range(7)] + [_ent("Bad")]
        )

    stats = _run(go)
    assert stats.written == 7 and stats.failed == 1 and "Bad" in stats.errors[0]


def test_transient_errors_are_retried_then_reported_as_unavailable(graph, monkeypatch):
    from neo4j.exceptions import ServiceUnavailable

    attempts = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def execute_write(self, work):
            attempts.append(1)
            raise ServiceUnavailable("gone")

    class _Driver:
        def session(self, **_k):
            return _Session()

    monkeypatch.setattr(gw, "get_neo4j_driver", lambda: asyncio.sleep(0, _Driver()))
    monkeypatch.setattr(gw.asyncio, "sleep", lambda *_a: _noop())

    async def _noop():
        return None

    async def go():
        return await gw.write_entities(_kb(), [_ent("X")])

    async def run():
        real_driver = _Driver()
        monkeypatch.setattr(gw, "get_neo4j_driver", lambda: _async(real_driver))
        return await go()

    async def _async(v):
        return v

    with pytest.raises(gw.GraphUnavailable):
        asyncio.run(run())
    assert len(attempts) == gw.WRITE_ATTEMPTS


def test_delete_kb_graph_removes_only_that_kb_in_small_transactions(graph, neo4j_uri):
    kb, keep = _kb(), _kb()

    async def go():
        await gw.write_entities(kb, [_ent(f"N{i}") for i in range(30)])
        await gw.write_entities(keep, [_ent("Stays")])
        return await gw.delete_kb_graph(kb, batch=7)

    out = _run(go)
    assert out == {"entities_deleted": 30}
    assert (
        cypher_sync(
            neo4j_uri, "MATCH (e:Entity {kb_id: $k}) RETURN count(e) AS n", k=kb
        )[0]["n"]
        == 0
    )
    assert (
        cypher_sync(
            neo4j_uri, "MATCH (e:Entity {kb_id: $k}) RETURN count(e) AS n", k=keep
        )[0]["n"]
        == 1
    )


def test_browse_pages_by_concept_and_search_with_stable_cursor(graph):
    kb = _kb()
    concept = str(uuid.uuid4())

    async def go():
        await gw.write_entities(
            kb,
            [_ent(f"Counterparty {i:02d}", atlas_concept_id=concept) for i in range(5)]
            + [_ent("Unrelated Thing")],
            tenant_id="t",
        )
        first = await nc.browse_entities(kb, "t", concept_id=concept, limit=2)
        second = await nc.browse_entities(
            kb, "t", concept_id=concept, after=first["next_cursor"], limit=2
        )
        found = await nc.browse_entities(kb, "t", query="unrelated")
        counts = await nc.concept_counts(kb, "t")
        return first, second, found, counts

    first, second, found, counts = _run(go)
    assert [e["name"] for e in first["entities"]] == [
        "Counterparty 00",
        "Counterparty 01",
    ]
    assert [e["name"] for e in second["entities"]] == [
        "Counterparty 02",
        "Counterparty 03",
    ]
    assert [e["name"] for e in found["entities"]] == ["Unrelated Thing"]
    assert counts["total"] == 6


def test_the_explorer_tool_works_and_is_scoped(graph):
    from engine.tools.graph_explorer_tool import GraphExplorerTool

    kb = _kb()

    async def go():
        await gw.write_entities(
            kb, [_ent("Acme", aliases=["ACME Inc"]), _ent("Globex")], tenant_id="t"
        )
        await gw.write_relationships(kb, [_rel("Acme", "Globex")])
        tool = GraphExplorerTool(kb_id=kb, tenant_id="t")
        return (
            await tool.execute({"operation": "graph_stats"}),
            await tool.execute({"operation": "find_entity", "entity_name": "acme"}),
            await tool.execute(
                {"operation": "find_entity", "entity_name": ".*(unclosed["}
            ),
            await tool.execute(
                {"operation": "entity_relationships", "entity_name": "Acme"}
            ),
            await tool.execute(
                {
                    "operation": "entity_path",
                    "entity_name": "Acme",
                    "target_entity": "Globex",
                }
            ),
            await GraphExplorerTool(kb_id=kb, tenant_id="other").execute(
                {"operation": "find_entity", "entity_name": "Acme"}
            ),
        )

    stats, found, odd, rels, path, other = _run(go)
    assert not odd.is_error
    assert stats.metadata["entities"] == 2 and not stats.is_error
    assert not found.is_error and "Acme" in found.content
    assert "WORKS_WITH" in rels.content and "Globex" in path.content
    assert "No entities" in other.content


def test_kb_wide_merge_moves_edges_and_merges_documents(graph, neo4j_uri):
    from engine.knowledge.kb_resolution import resolve_kb_entities

    kb = _kb()

    async def go():
        await gw.write_entities(
            kb,
            [
                _ent("ACME Corp", ["d1"]),
                _ent("Acme Corp.", ["d2"]),
                _ent("Globex", ["d3"]),
            ],
            tenant_id="t",
        )
        await gw.write_relationships(
            kb,
            [_rel("Acme Corp.", "Globex", ["d2"]), _rel("ACME Corp", "Globex", ["d1"])],
        )
        return await resolve_kb_entities(kb, "t", use_llm=False)

    out = _run(go)
    assert out.exact_merges == 1 and out.names_scanned == 3
    rows = cypher_sync(
        neo4j_uri,
        "MATCH (e:Entity {kb_id: $k}) RETURN e.canonical_name AS n, e.source_doc_ids AS d, e.aliases AS a",
        k=kb,
    )
    assert len(rows) == 2
    merged = next(r for r in rows if r["n"] != "Globex")
    assert set(merged["d"]) == {"d1", "d2"} and merged["a"]
    edges = cypher_sync(
        neo4j_uri,
        "MATCH (:Entity {kb_id: $k})-[r]->(b:Entity {kb_id: $k}) RETURN r.source_doc_ids AS d, r.weight AS w",
        k=kb,
    )
    assert (
        len(edges) == 1 and set(edges[0]["d"]) == {"d1", "d2"} and edges[0]["w"] == 2.0
    )
