"""Atlas on a graph too big to load whole, against real Postgres."""

from __future__ import annotations

import asyncio
import json
import uuid

from atlas_live import app_for, bulk_graph, client, make_user
from kb_pg import make_doc, make_kb, make_tenant

from app.routers import atlas as router
from app.services import atlas_snapshots


def _go(world, coro_factory):
    async def main():
        async with client(world.app) as http:
            return await coro_factory(http)

    return asyncio.run(main())


def _data(r):
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_get_graph_is_paged_not_everything(atlas_world):
    w = atlas_world
    gid = bulk_graph(w.cur, w.tenant, w.user, 300, 400)

    async def go(http):
        first = _data(
            await http.get(f"/api/atlas/graphs/{gid}", params={"node_limit": 100})
        )
        second = _data(
            await http.get(
                f"/api/atlas/graphs/{gid}",
                params={"node_limit": 100, "after": first["next_cursor"]},
            )
        )
        meta = _data(
            await http.get(f"/api/atlas/graphs/{gid}", params={"node_limit": 0})
        )
        whole = _data(await http.get(f"/api/atlas/graphs/{gid}"))
        return first, second, meta, whole

    first, second, meta, whole = _go(w, go)
    assert len(first["nodes"]) == 100 and first["truncated"] and first["next_cursor"]
    assert not ({n["id"] for n in first["nodes"]} & {n["id"] for n in second["nodes"]})
    assert meta["nodes"] == [] and meta["graph"]["node_count"] == 300
    assert len(whole["nodes"]) == 300 and not whole["truncated"]
    assert len(whole["edges"]) == 400


def test_a_small_graph_keeps_its_old_response_shape(atlas_world):
    w = atlas_world

    async def go(http):
        g = _data(await http.post("/api/atlas/graphs", json={"name": "small"}))["graph"]
        a = _data(
            await http.post(f"/api/atlas/graphs/{g['id']}/nodes", json={"label": "A"})
        )["node"]
        b = _data(
            await http.post(f"/api/atlas/graphs/{g['id']}/nodes", json={"label": "B"})
        )["node"]
        e = _data(
            await http.post(
                f"/api/atlas/graphs/{g['id']}/edges",
                json={"from_node_id": a["id"], "to_node_id": b["id"], "label": "knows"},
            )
        )["edge"]
        got = _data(await http.get(f"/api/atlas/graphs/{g['id']}"))
        return got, a, e

    got, a, e = _go(w, go)
    assert {n["label"] for n in got["nodes"]} == {"A", "B"}
    assert got["edges"][0]["id"] == e["id"]
    assert got["graph"]["node_count"] == 2 and got["graph"]["edge_count"] == 1
    assert got["graph"]["version"] == 4


def test_neighbourhood_viewport_and_search_stay_inside_their_limits(
    atlas_world,
):
    w = atlas_world
    gid = bulk_graph(w.cur, w.tenant, w.user, 2000, 3000)
    # a hub with far more edges than any page holds
    w.cur.execute(
        "SELECT id FROM atlas_nodes WHERE graph_id = %s ORDER BY created_at LIMIT 1",
        (gid,),
    )
    hub = str(w.cur.fetchone()[0])
    w.cur.execute(
        """
        INSERT INTO atlas_edges (id, graph_id, from_node_id, to_node_id, label, description,
            is_directed, properties, source, recorded_at, created_at, updated_at)
        SELECT gen_random_uuid(), %s, %s, id, 'hub', '', true, '{}', 'user', now(), now(), now()
        FROM atlas_nodes WHERE graph_id = %s AND id <> %s LIMIT 1500
        """,
        (gid, hub, gid, hub),
    )

    async def go(http):
        hood = _data(
            await http.get(
                f"/api/atlas/graphs/{gid}/neighbourhood",
                params={"node_id": hub, "limit": 60, "fanout": 20},
            )
        )
        view = _data(
            await http.get(
                f"/api/atlas/graphs/{gid}/viewport",
                params={"min_x": 0, "min_y": 0, "max_x": 500, "max_y": 500, "limit": 5},
            )
        )
        wide = _data(
            await http.get(
                f"/api/atlas/graphs/{gid}/viewport",
                params={
                    "min_x": 0,
                    "min_y": 0,
                    "max_x": 99999,
                    "max_y": 99999,
                    "limit": 50,
                },
            )
        )
        found = _data(
            await http.get(f"/api/atlas/graphs/{gid}/search", params={"q": "ode 123"})
        )
        page = _data(
            await http.get(
                f"/api/atlas/graphs/{gid}/search", params={"q": "node", "limit": 7}
            )
        )
        over = _data(
            await http.get(f"/api/atlas/graphs/{gid}/overview", params={"limit": 30})
        )
        return hood, view, wide, found, page, over

    hood, view, wide, found, page, over = _go(w, go)
    assert hood["truncated"] and len(hood["nodes"]) <= 60 and hood["degree"] >= 1500
    assert hood["center"] == hub
    assert len(view["nodes"]) <= 5
    assert len(wide["nodes"]) == 50 and wide["truncated"] and wide["in_view"] == 2000
    assert {n["label"] for n in found["nodes"]} >= {"Node 123", "Node 1234"}
    assert len(page["nodes"]) == 7 and page["next_cursor"]
    assert hub in {n["id"] for n in over["nodes"]} and len(over["nodes"]) == 30


def test_mutations_do_not_read_every_row_and_counts_stay_right(
    atlas_world, monkeypatch
):
    w = atlas_world
    gid = bulk_graph(w.cur, w.tenant, w.user, 500, 500)
    statements: list[str] = []
    from sqlalchemy import event

    event.listen(
        w.engine.sync_engine,
        "before_cursor_execute",
        lambda _c, _cur, st, *_a: statements.append(st),
    )

    def whole_table_reads():
        out = []
        for st in statements:
            flat = " ".join(st.split())
            if flat.startswith("SELECT atlas_nodes.id") or flat.startswith(
                "SELECT atlas_edges.id"
            ):
                if (
                    "LIMIT" not in flat
                    and " IN (" not in flat
                    and "atlas_nodes.id =" not in flat
                    and "atlas_edges.id =" not in flat
                ):
                    out.append(flat[:160])
        return out

    async def go(http):
        base = f"/api/atlas/graphs/{gid}"
        n = _data(
            await http.post(
                f"{base}/nodes", json={"label": "New", "position": {"x": 1, "y": 1}}
            )
        )
        w.cur.execute(
            "SELECT id FROM atlas_nodes WHERE graph_id = %s AND label = 'Node 7'",
            (gid,),
        )
        seven = str(w.cur.fetchone()[0])
        e = _data(
            await http.post(
                f"{base}/edges",
                json={
                    "from_node_id": n["node"]["id"],
                    "to_node_id": seven,
                    "label": "x",
                },
            )
        )
        await http.patch(f"{base}/nodes/{seven}", json={"description": "changed"})
        await http.delete(f"{base}/nodes/{n['node']['id']}")
        return _data(await http.get(base, params={"node_limit": 0})), e

    meta, _e = _go(w, go)
    assert whole_table_reads() == []
    assert meta["graph"]["node_count"] == 500 and meta["graph"]["edge_count"] == 500


def _state(cur, gid):
    cur.execute(
        "SELECT id, label, description, position_x FROM atlas_nodes WHERE graph_id = %s ORDER BY id",
        (gid,),
    )
    nodes = cur.fetchall()
    cur.execute(
        "SELECT id, from_node_id, to_node_id, label FROM atlas_edges WHERE graph_id = %s ORDER BY id",
        (gid,),
    )
    return nodes, cur.fetchall()


def test_snapshots_store_only_what_changed_and_restore_exactly(
    atlas_world,
):
    w = atlas_world
    gid = bulk_graph(w.cur, w.tenant, w.user, 200, 200)
    base = f"/api/atlas/graphs/{gid}"
    # the graph was built a while ago, so only the edits below count as changes
    for table in ("atlas_nodes", "atlas_edges"):
        w.cur.execute(
            f"UPDATE {table} SET updated_at = now() - interval '1 hour', "
            "created_at = created_at - interval '1 hour' WHERE graph_id = %s",
            (gid,),
        )

    async def go(http):
        first = _data(await http.post(f"{base}/snapshots", json={"label": "one"}))
        w.cur.execute(
            "SELECT count(*) FROM atlas_snapshot_rows WHERE graph_id = %s", (gid,)
        )
        baseline = w.cur.fetchone()[0]
        before = _state(w.cur, gid)
        # one edit, one new node, one delete with its edges
        w.cur.execute(
            "SELECT id FROM atlas_nodes WHERE graph_id = %s ORDER BY created_at LIMIT 2",
            (gid,),
        )
        a, b = [str(r[0]) for r in w.cur.fetchall()]
        await http.patch(f"{base}/nodes/{a}", json={"description": "edited"})
        await http.delete(f"{base}/nodes/{b}")
        await http.post(f"{base}/nodes", json={"label": "Added"})
        second = _data(await http.post(f"{base}/snapshots", json={"label": "two"}))
        w.cur.execute(
            "SELECT payload FROM atlas_snapshots WHERE id = %s", (second["id"],)
        )
        payload = w.cur.fetchone()[0]
        w.cur.execute(
            "SELECT count(*) FROM atlas_snapshot_rows WHERE graph_id = %s", (gid,)
        )
        grown = w.cur.fetchone()[0]
        after = _state(w.cur, gid)
        restored = _data(
            await http.post(f"{base}/snapshots/{first['id']}/restore", json={})
        )
        back = _state(w.cur, gid)
        await http.post(f"{base}/snapshots/{second['id']}/restore", json={})
        forward = _state(w.cur, gid)
        meta = _data(await http.get(base, params={"node_limit": 0}))
        return baseline, grown, payload, before, back, after, forward, restored, meta

    baseline, grown, payload, before, back, after, forward, restored, meta = _go(w, go)
    assert baseline == len(before[0]) + len(before[1])
    assert payload["format"] == "diff" and not payload["baseline"]
    assert "nodes" not in payload
    # far below another whole copy of the graph
    assert grown - baseline < 50
    assert back == before
    assert forward[0] == after[0] and forward[1] == after[1]
    assert restored["restored"] and meta["graph"]["node_count"] == len(after[0])


def test_old_style_full_snapshots_still_restore(atlas_world):
    w = atlas_world
    gid = bulk_graph(w.cur, w.tenant, w.user, 5, 0)
    node = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    w.cur.execute(
        "INSERT INTO atlas_snapshots (id, graph_id, version, auto, payload) VALUES (%s, %s, 0, false, %s)",
        (
            sid,
            gid,
            json.dumps(
                {
                    "graph": {},
                    "nodes": [{"id": node, "label": "Legacy", "kind": "concept"}],
                    "edges": [],
                }
            ),
        ),
    )

    async def go(http):
        return _data(
            await http.post(f"/api/atlas/graphs/{gid}/snapshots/{sid}/restore", json={})
        )

    assert _go(w, go)["restored"]
    w.cur.execute("SELECT label FROM atlas_nodes WHERE graph_id = %s", (gid,))
    assert [r[0] for r in w.cur.fetchall()] == ["Legacy"]


def test_pruning_keeps_named_snapshots_restorable(atlas_world, monkeypatch):
    w = atlas_world
    gid = bulk_graph(w.cur, w.tenant, w.user, 10, 0)
    base = f"/api/atlas/graphs/{gid}"
    monkeypatch.setattr(atlas_snapshots, "KEEP_AUTO", 2)
    real = atlas_snapshots.prune

    async def keep_two(db, graph_id, keep=2):
        return await real(db, graph_id, keep=2)

    monkeypatch.setattr(atlas_snapshots, "prune", keep_two)

    async def go(http):
        named = _data(await http.post(f"{base}/snapshots", json={"label": "keep me"}))
        before = _state(w.cur, gid)
        w.cur.execute(
            "SELECT id FROM atlas_nodes WHERE graph_id = %s ORDER BY created_at LIMIT 1",
            (gid,),
        )
        nid = str(w.cur.fetchone()[0])
        from sqlalchemy import select

        from models.atlas import AtlasGraph

        for i in range(6):
            await http.patch(f"{base}/nodes/{nid}", json={"description": f"edit {i}"})
            async with w.factory() as db:
                g = (
                    await db.execute(
                        select(AtlasGraph).where(AtlasGraph.id == uuid.UUID(gid))
                    )
                ).scalar_one()
                await atlas_snapshots.capture(db, g, w.user.id)
                await db.commit()
        w.cur.execute(
            "SELECT count(*) FROM atlas_snapshots WHERE graph_id = %s AND auto", (gid,)
        )
        autos = w.cur.fetchone()[0]
        w.cur.execute(
            "SELECT count(*) FROM atlas_snapshot_rows WHERE graph_id = %s AND kind = 'n' AND row_id = %s",
            (gid, nid),
        )
        versions = w.cur.fetchone()[0]
        await http.post(f"{base}/snapshots/{named['id']}/restore", json={})
        return autos, versions, before, _state(w.cur, gid)

    autos, versions, before, back = _go(w, go)
    assert autos <= 3
    assert versions <= 4, "pruned versions of the row are gone"
    assert back == before


def test_big_sync_runs_in_the_background_in_batches(atlas_world, monkeypatch):
    w = atlas_world
    w.cur.execute(
        "INSERT INTO documents (id, kb_id, filename, file_type, file_size, chunk_count, status, storage_url, version_number, is_current) "
        "SELECT gen_random_uuid(), %s, 'doc' || i || '.txt', 'txt', 10, 1, 'READY', '', 1, true FROM generate_series(1, 1300) i",
        (w.kb,),
    )
    gid = bulk_graph(w.cur, w.tenant, w.user, 1, 0, kb=w.kb)
    import app.core.deps as deps

    monkeypatch.setattr(deps, "bg_session", w.factory)

    async def go(http):
        started = _data(await http.post(f"/api/atlas/graphs/{gid}/sync-kb"))
        assert started["queued"] and started["created_nodes"] == []
        for _ in range(200):
            status = _data(await http.get(f"/api/atlas/graphs/{gid}/sync-kb"))
            if not status["running"]:
                break
            await asyncio.sleep(0.05)
        again = _data(await http.post(f"/api/atlas/graphs/{gid}/sync-kb"))
        meta = _data(
            await http.get(f"/api/atlas/graphs/{gid}", params={"node_limit": 0})
        )
        return status, again, meta

    status, again, meta = _go(w, go)
    assert status["sync"]["status"] == "complete" and status["sync"]["imported"] == 1300
    assert again["imported"] == 0 and not again["queued"]
    assert meta["graph"]["node_count"] == 1301
    w.cur.execute(
        "SELECT count(*) FROM atlas_nodes WHERE graph_id = %s AND document_id IS NOT NULL",
        (gid,),
    )
    assert w.cur.fetchone()[0] == 1300


def test_small_sync_still_answers_inline(atlas_world):
    w = atlas_world
    make_doc(w.cur, w.kb, ["x"], filename="one.txt")
    gid = bulk_graph(w.cur, w.tenant, w.user, 1, 0, kb=w.kb)

    async def go(http):
        return _data(await http.post(f"/api/atlas/graphs/{gid}/sync-kb"))

    out = _go(w, go)
    assert out["imported"] == 1 and out["created_nodes"][0]["label"] == "one.txt"


def test_query_finds_a_pattern_without_loading_the_graph(atlas_world):
    w = atlas_world
    gid = bulk_graph(w.cur, w.tenant, w.user, 1000, 1000)

    async def go(http):
        return _data(
            await http.post(
                f"/api/atlas/graphs/{gid}/query",
                json={"patterns": [{"label_like": "node 12"}], "limit": 5},
            )
        ), _data(await http.get(f"/api/atlas/graphs/{gid}/suggestions"))

    q, sugg = _go(w, go)
    assert q["count"] == 5 and "truncated" in q
    assert isinstance(sugg["suggestions"], list)


def test_big_relayout_runs_in_sql_and_export_streams(atlas_world, monkeypatch):
    w = atlas_world
    gid = bulk_graph(w.cur, w.tenant, w.user, 50, 20)
    monkeypatch.setattr(router, "FULL_GRAPH_LIMIT", 10)
    import app.core.deps as deps

    monkeypatch.setattr(deps, "async_session", w.factory)

    async def go(http):
        out = _data(
            await http.post(
                f"/api/atlas/graphs/{gid}/relayout", json={"mode": "semantic"}
            )
        )
        ld = await http.get(f"/api/atlas/graphs/{gid}/export")
        plain = await http.get(
            f"/api/atlas/graphs/{gid}/export", params={"format": "json"}
        )
        return out, ld, plain

    out, ld, plain = _go(w, go)
    assert out["reload"] and out["mode"] == "grid" and out["relaid_out"] == 50
    doc = json.loads(ld.text)
    assert len(doc["@graph"]) == 70 and doc["@context"]["owl"]
    assert "attachment" in ld.headers["content-disposition"]
    full = json.loads(plain.text)
    assert len(full["nodes"]) == 50 and len(full["edges"]) == 20


def test_another_tenant_gets_nothing_from_the_new_routes(kg_conn, kg_db_url):
    cur = kg_conn.cursor()
    tenant = make_tenant(cur)
    other = make_tenant(cur)
    owner = make_user(cur, tenant)
    stranger = make_user(cur, other)
    gid = bulk_graph(cur, tenant, owner, 5, 2)
    app, _engine, _f = app_for(kg_db_url, stranger)
    cur.execute("SELECT id FROM atlas_nodes WHERE graph_id = %s LIMIT 1", (gid,))
    node = str(cur.fetchone()[0])

    async def go():
        async with client(app) as http:
            out = []
            for path, params in (
                ("overview", {}),
                ("viewport", {"min_x": 0, "min_y": 0, "max_x": 9, "max_y": 9}),
                ("neighbourhood", {"node_id": node}),
                ("search", {"q": "node"}),
                ("context", {}),
                ("entities", {}),
            ):
                out.append(
                    (
                        await http.get(f"/api/atlas/graphs/{gid}/{path}", params=params)
                    ).status_code
                )
            return out

    assert asyncio.run(go()) == [404] * 6


def test_creating_a_graph_bound_to_another_tenants_kb_is_refused(kg_conn, kg_db_url):
    cur = kg_conn.cursor()
    tenant = make_tenant(cur)
    other = make_tenant(cur)
    foreign_kb = make_kb(cur, other)
    user = make_user(cur, tenant)
    app, _engine, _f = app_for(kg_db_url, user)

    async def go():
        async with client(app) as http:
            return await http.post(
                "/api/atlas/graphs", json={"name": "x", "kb_id": foreign_kb}
            )

    assert asyncio.run(go()).status_code == 404
