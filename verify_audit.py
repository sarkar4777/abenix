import json, urllib.request, urllib.error, sys, time

BASE = "http://localhost:8000"

def req(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

out = {}
# login
st, login = req("POST", "/api/auth/login", {"email": "admin@abenix.dev", "password": "Admin123456"})
out["login_status"] = st
tok = login["data"]["access_token"]

# baseline activity
st, before = req("GET", "/api/settings/activity", token=tok)
out["activity_before_count"] = len(before.get("data") or [])
out["activity_before_top5"] = [(r["action"], r["created_at"]) for r in (before.get("data") or [])[:5]]

# GET retention current
st, ret_before = req("GET", "/api/settings/retention", token=tok)
out["retention_get_before"] = (st, ret_before)

# PUT retention with new values
st, ret_put = req("PUT", "/api/settings/retention", {"execution_retention_days": 75, "audit_log_retention_days": 800}, token=tok)
out["retention_put_status"] = st
out["retention_put_body"] = ret_put

# GET dlp
st, dlp_before = req("GET", "/api/settings/dlp", token=tok)
out["dlp_get_before"] = (st, dlp_before)

# PUT dlp
st, dlp_put = req("PUT", "/api/settings/dlp", {"mode": "mask", "enabled": True}, token=tok)
out["dlp_put_status"] = st
out["dlp_put_body"] = dlp_put

# small wait then re-check activity
time.sleep(2)
st, after = req("GET", "/api/settings/activity", token=tok)
out["activity_after_count"] = len(after.get("data") or [])
out["activity_after_top10"] = [(r["action"], r["created_at"]) for r in (after.get("data") or [])[:10]]

# also probe: do tenant_settings_updated PUT to confirm audit path still works
st, tnt_put = req("PUT", "/api/settings/tenant", {"slack_webhook_url": ""}, token=tok)
out["tenant_put_status"] = st
out["tenant_put_body"] = tnt_put

time.sleep(2)
st, after2 = req("GET", "/api/settings/activity", token=tok)
out["activity_after_tenant_count"] = len(after2.get("data") or [])
out["activity_after_tenant_top10"] = [(r["action"], r["created_at"]) for r in (after2.get("data") or [])[:10]]

# search for any retention/dlp action keywords
actions_all = [r["action"] for r in (after2.get("data") or [])]
out["any_retention_action"] = [a for a in actions_all if "retention" in a.lower() or "dlp" in a.lower()]
out["distinct_actions"] = sorted(set(actions_all))

with open("verify_audit_out.json", "w") as f:
    json.dump(out, f, indent=2, default=str)
print("DONE")
