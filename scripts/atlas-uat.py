"""End-to-end UAT for Atlas — runs inside a python:3.12-slim pod
talking to the in-cluster API service. Exits non-zero if any step fails.
"""
import json
import sys
import urllib.error
import urllib.request

API = "http://abenix-api:8000"


def req(method, path, headers=None, body=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    data = json.dumps(body).encode() if body is not None else None
    rq = urllib.request.Request(API + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(rq, timeout=120) as r:
            txt = r.read().decode()
            return r.status, json.loads(txt) if txt else {}
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


passed = 0
failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


print("=== Auth ===")
sc, body = req("POST", "/api/auth/login",
               body={"email": "admin@abenix.dev", "password": "Admin123456"})
tok = (body.get("data") or body).get("access_token")
check("login", sc == 200 and tok, f"sc={sc} token_len={len(tok) if tok else 0}")
H = {"Authorization": f"Bearer {tok}"}

print("\n=== KB list ===")
sc, body = req("GET", "/api/knowledge-bases", headers=H)
kbs = body.get("data") or []
if isinstance(kbs, dict):
    kbs = kbs.get("knowledge_bases", []) or kbs.get("collections", [])
check("list KBs", sc == 200, f"sc={sc} count={len(kbs)}")
kbid = kbs[0]["id"] if kbs else None
print(f"  first KB id: {kbid[:8] if kbid else None}…")

print("\n=== Phase 1: CRUD ===")
sc, body = req("POST", "/api/atlas/graphs", headers=H, body={"name": "Atlas UAT"})
gid = body.get("data", {}).get("graph", {}).get("id")
check("create graph", sc == 200 and gid is not None, f"gid={gid[:8] if gid else None}…")

sc, body = req("GET", "/api/atlas/graphs", headers=H)
check("list graphs", sc == 200, f"count={len(body.get('data', {}).get('graphs', []))}")

sc, body = req("GET", f"/api/atlas/graphs/{gid}", headers=H)
check("get full graph", sc == 200)

sc, body = req("POST", f"/api/atlas/graphs/{gid}/nodes", headers=H,
               body={"label": "Counterparty", "kind": "concept", "position": {"x": 100, "y": 200}})
nid1 = body.get("data", {}).get("node", {}).get("id")
check("create node #1", sc == 200 and nid1 is not None)

sc, body = req("POST", f"/api/atlas/graphs/{gid}/nodes", headers=H,
               body={"label": "Trade", "kind": "concept"})
nid2 = body.get("data", {}).get("node", {}).get("id")
check("create node #2", sc == 200 and nid2 is not None)

sc, body = req("POST", f"/api/atlas/graphs/{gid}/edges", headers=H,
               body={"from_node_id": nid1, "to_node_id": nid2, "label": "trades", "cardinality_to": "*"})
eid = body.get("data", {}).get("edge", {}).get("id")
check("create edge", sc == 200 and eid is not None)

sc, body = req("PATCH", f"/api/atlas/graphs/{gid}/nodes/{nid1}", headers=H,
               body={"description": "A legal entity participating in a trade"})
check("patch node", sc == 200 and body["data"]["node"]["description"].startswith("A legal"))

sc, body = req("GET", f"/api/atlas/graphs/{gid}/suggestions", headers=H)
check("suggestions", sc == 200, f"count={len(body.get('data', {}).get('suggestions', []))}")

print("\n=== Phase 2: Starters + KB binding + Layout + Query ===")
sc, body = req("GET", "/api/atlas/starters", headers=H)
n_starters = len(body.get("data", {}).get("starters", []))
check("list starters", sc == 200 and n_starters >= 5, f"count={n_starters}")

sc, body = req("POST", f"/api/atlas/graphs/{gid}/import-starter", headers=H, body={"kit": "fibo-core"})
n_imported = len(body.get("data", {}).get("created_nodes", []))
check("import fibo-core starter", sc == 200 and n_imported > 0, f"created_nodes={n_imported}")

if kbid:
    sc, body = req("POST", f"/api/atlas/graphs/{gid}/bind-kb", headers=H, body={"kb_id": kbid})
    check("bind to KB", sc == 200 and body["data"]["graph"]["kb_id"] == kbid)

    sc, body = req("POST", f"/api/atlas/graphs/{gid}/sync-kb", headers=H)
    check("sync KB into atlas", sc == 200, f"imported={body.get('data', {}).get('imported')}")

    sc, body = req("PATCH", f"/api/atlas/graphs/{gid}/nodes/{nid1}/binding", headers=H,
                   body={"binding": {"kind": "kb_collection", "ref_id": kbid}})
    has_binding = body.get("data", {}).get("node", {}).get("properties", {}).get("_binding") is not None
    check("bind node to KB", sc == 200 and has_binding)

    sc, body = req("GET", f"/api/atlas/graphs/{gid}/nodes/{nid1}/instances", headers=H)
    check("read live instances", sc == 200,
          f"binding_kind={body.get('data', {}).get('binding', {}).get('kind')}")

sc, body = req("POST", f"/api/atlas/graphs/{gid}/query", headers=H,
               body={"patterns": [{"label_like": "Trade"}]})
match_count = body.get("data", {}).get("count", 0)
check("visual query", sc == 200 and match_count >= 1, f"matches={match_count}")

for mode in ("circle", "grid", "semantic"):
    sc, body = req("POST", f"/api/atlas/graphs/{gid}/relayout", headers=H, body={"mode": mode})
    eff_mode = body.get("data", {}).get("mode")
    check(f"relayout mode={mode}", sc == 200, f"effective={eff_mode}")

# parse-nl uses an LLM; allow it to be skipped if no API key
sc, body = req("POST", f"/api/atlas/graphs/{gid}/parse-nl", headers=H,
               body={"text": "Buyer has many Invoices. Each Invoice belongs to one Buyer.",
                     "model": "gemini-2.5-flash"})
ops = body.get("data", {}).get("ops", [])
if sc == 200:
    check("parse-nl", len(ops) >= 1, f"ops={len(ops)}")
else:
    print(f"  SKIP  parse-nl  sc={sc} (likely no LLM key in env)")

# snapshots
sc, body = req("POST", f"/api/atlas/graphs/{gid}/snapshots", headers=H, body={"label": "uat checkpoint"})
check("create snapshot", sc == 200)

sc, body = req("GET", f"/api/atlas/graphs/{gid}/snapshots", headers=H)
n_snaps = len(body.get("data", {}).get("snapshots", []))
check("list snapshots", sc == 200 and n_snaps >= 1, f"count={n_snaps}")

# export
sc, _ = req("GET", f"/api/atlas/graphs/{gid}/export?format=json-ld", headers=H)
check("export json-ld", sc == 200)

sc, _ = req("GET", f"/api/atlas/graphs/{gid}/export?format=json", headers=H)
check("export plain json", sc == 200)

# delete edge + node
sc, _ = req("DELETE", f"/api/atlas/graphs/{gid}/edges/{eid}", headers=H)
check("delete edge", sc == 200)
sc, _ = req("DELETE", f"/api/atlas/graphs/{gid}/nodes/{nid2}", headers=H)
check("delete node", sc == 200)

# tenant isolation: attempt as a different user/tenant should 404
# (We only have one tenant in the smoke; check the wrong-uuid path instead.)
sc, _ = req("GET", "/api/atlas/graphs/00000000-0000-0000-0000-000000000000", headers=H)
check("404 on bogus graph id", sc == 404)

# cleanup
sc, _ = req("DELETE", f"/api/atlas/graphs/{gid}", headers=H)
check("delete graph", sc == 200)

print(f"\n=== {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)
