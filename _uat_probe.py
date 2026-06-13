"""Probe: force tool call + inspect execution detail tool_calls."""
import json, time, urllib.error, urllib.request

BASE = "http://localhost:8000"


def req(method, path, token=None, body=None, timeout=240):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.getcode(), json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, e.read().decode()


def main():
    out = {}
    _, j = req("POST", "/api/auth/login", body={"email": "admin@abenix.dev", "password": "Admin123456"})
    token = j["data"]["access_token"]

    # KB lookup
    _, j = req("GET", "/api/knowledge-bases", token=token)
    kbs = j["data"] if isinstance(j, dict) else j
    kb = sorted(kbs, key=lambda k: k.get("doc_count") or 0, reverse=True)[0]
    kb_id = kb["id"]

    # Use the agent already created above? Re-create with stronger prompt and matching tool_config.
    body = {
        "name": f"uat-kb-forced-{int(time.time())}",
        "system_prompt": (
            "You MUST call knowledge_search FIRST for every user message before answering. "
            "After receiving the tool result, summarise it and list exact source identifiers."
        ),
        "model_config": {
            "model": "claude-haiku-4-5-20251001",
            "tools": ["knowledge_search"],
            "temperature": 0.0,
            "max_iterations": 5,
        },
        "category": "audit",
    }
    s, j = req("POST", "/api/agents", token=token, body=body)
    out["create"] = s
    aid = j["data"]["id"]
    req("PUT", f"/api/agents/{aid}", token=token, body={"status": "active"})

    s, j = req(
        "POST",
        f"/api/knowledge-collections/{kb_id}/agents",
        token=token,
        body={"agent_id": aid, "permission": "READ"},
    )
    out["grant"] = s

    # Execute (sync)
    s, j = req(
        "POST",
        f"/api/agents/{aid}/execute",
        token=token,
        body={
            "message": "What is in this knowledge base? You MUST call knowledge_search before answering.",
            "stream": False,
            "wait": True,
            "wait_timeout_seconds": 180,
        },
    )
    out["exec_sync"] = s
    eid = None
    if isinstance(j, dict):
        d = j.get("data", j)
        out["exec_keys"] = list(d.keys()) if isinstance(d, dict) else None
        out["exec_status"] = d.get("status") if isinstance(d, dict) else None
        out["exec_output"] = str(d.get("output") or d.get("output_message") or "")[:600] if isinstance(d, dict) else None
        out["exec_summary"] = d.get("summary") if isinstance(d, dict) else None
        eid = d.get("execution_id") or d.get("id") if isinstance(d, dict) else None
    # Detail
    if eid:
        s, j = req("GET", f"/api/executions/{eid}", token=token)
        if isinstance(j, dict):
            d = j.get("data", j)
            out["detail_status"] = d.get("status")
            out["detail_tool_calls"] = d.get("tool_calls")
            out["detail_node_results"] = d.get("node_results")
            out["detail_execution_trace_excerpt"] = str(d.get("execution_trace") or "")[:1200]
            out["detail_output_message"] = str(d.get("output_message") or "")[:1200]
            out["detail_error"] = d.get("error_message")
            out["detail_failure_code"] = d.get("failure_code")
            out["detail_trace_id"] = d.get("trace_id")
            out["detail_input_tokens"] = d.get("input_tokens")
            out["detail_output_tokens"] = d.get("output_tokens")
            out["detail_cost"] = d.get("cost")

    # also call /api/tools to list available tools
    s, j = req("GET", "/api/tools", token=token)
    if isinstance(j, dict):
        d = j.get("data", j)
        if isinstance(d, list):
            ks_present = [t for t in d if (t.get("name") if isinstance(t, dict) else t) == "knowledge_search"]
            out["tools_listing_status"] = s
            out["knowledge_search_listed"] = bool(ks_present)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
