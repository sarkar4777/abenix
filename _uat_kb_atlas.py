"""End-to-end UAT: agent + KB + Atlas + SSE + invoke_agent recursion."""
import json
import sys
import time
import urllib.error
import urllib.request
import socket

BASE = "http://localhost:8000"


def req(method, path, token=None, body=None, raw=False, timeout=120, extra_headers=None):
    url = BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            body_bytes = resp.read()
            status = resp.getcode()
            if raw:
                return status, body_bytes.decode("utf-8", errors="replace"), dict(resp.headers)
            try:
                return status, json.loads(body_bytes.decode()), dict(resp.headers)
            except Exception:
                return status, body_bytes.decode("utf-8", errors="replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        try:
            j = json.loads(body_text)
        except Exception:
            j = body_text
        return e.code, j, dict(e.headers or {})


def get_sse(path, token, body, timeout=120):
    """Return list of SSE events as dicts (event, data)."""
    url = BASE + path
    data = json.dumps(body).encode()
    req_obj = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {token}",
        },
    )
    events = []
    try:
        with urllib.request.urlopen(req_obj, timeout=timeout) as resp:
            current_event = None
            current_data = []
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")
                if line == "":
                    if current_event or current_data:
                        events.append({"event": current_event, "data": "".join(current_data)})
                        current_event = None
                        current_data = []
                    continue
                if line.startswith("event:"):
                    current_event = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    current_data.append(line[len("data:"):].lstrip())
                if len(events) > 400:
                    break
            if current_event or current_data:
                events.append({"event": current_event, "data": "".join(current_data)})
            return resp.getcode(), events
    except (urllib.error.HTTPError, socket.timeout) as e:
        return getattr(e, "code", 0), events


def main():
    out = {}

    s, j, _ = req("POST", "/api/auth/login", body={"email": "admin@abenix.dev", "password": "Admin123456"})
    token = j["data"]["access_token"]
    user_id = j["data"]["user"]["id"]
    out["login"] = {"status": s, "user_id": user_id}

    # KB list
    s, j, _ = req("GET", "/api/knowledge-bases", token=token)
    kbs = j.get("data", j) if isinstance(j, dict) else j
    if isinstance(kbs, dict) and "items" in kbs:
        kbs = kbs["items"]
    kbs_sorted = sorted(kbs, key=lambda k: k.get("doc_count") or 0, reverse=True)
    # find one in admin's tenant for grant
    kb = next((k for k in kbs_sorted if k.get("doc_count", 0) >= 5), kbs_sorted[0])
    kb_id = kb["id"]
    out["kb"] = {"id": kb_id, "name": kb["name"], "doc_count": kb.get("doc_count"), "tenant_id": kb.get("tenant_id")}

    # 3. Create agent with knowledge_base_ids in body (as caller asked)
    create_body = {
        "name": f"uat-kb-agent-{int(time.time())}",
        "system_prompt": "You answer using the knowledge_search tool only. Always cite sources.",
        "model_config": {
            "model": "claude-haiku-4-5-20251001",
            "tools": ["knowledge_search"],
            "temperature": 0.3,
        },
        "category": "audit",
        "knowledge_base_ids": [kb_id],  # try direct attachment
    }
    s, j, _ = req("POST", "/api/agents", token=token, body=create_body)
    out["agent_create_status"] = s
    out["agent_create_resp_keys"] = list(j.get("data", {}).keys()) if isinstance(j, dict) and isinstance(j.get("data"), dict) else None
    if s not in (200, 201):
        out["agent_create_err"] = j
        print(json.dumps(out, indent=2, default=str))
        return
    agent = j["data"]
    agent_id = agent["id"]
    out["agent_id"] = agent_id
    # check if the kb id was stored
    out["agent_kb_field_visible"] = {
        k: agent.get(k) for k in ("knowledge_base_ids", "kb_ids", "knowledge_collection_ids")
    }

    # 4. Activate agent (status DRAFT may still execute, but force ACTIVE)
    s, j, _ = req("PUT", f"/api/agents/{agent_id}", token=token, body={"status": "active"})
    out["agent_activate_status"] = s

    # 5. Grant KB to agent via collection-grants endpoint (the official path)
    s, j, _ = req(
        "POST",
        f"/api/knowledge-collections/{kb_id}/agents",
        token=token,
        body={"agent_id": agent_id, "permission": "READ"},
    )
    out["kb_grant_status"] = s
    if s not in (200, 201):
        out["kb_grant_err"] = j

    # 6. Execute agent (sync, wait) with question that should hit KB
    exec_body = {
        "message": "Summarise what this knowledge base contains. Cite specific document or chunk references in your answer.",
        "stream": False,
        "wait": True,
        "wait_timeout_seconds": 180,
    }
    t0 = time.time()
    s, j, _ = req("POST", f"/api/agents/{agent_id}/execute", token=token, body=exec_body, timeout=240)
    out["exec_sync_status"] = s
    out["exec_sync_elapsed_s"] = round(time.time() - t0, 1)
    if isinstance(j, dict):
        d = j.get("data", j)
        if isinstance(d, dict):
            out["exec_sync_keys"] = list(d.keys())
            # surface key fields
            out["exec_sync_status_field"] = d.get("status")
            out["exec_sync_execution_id"] = d.get("execution_id") or d.get("id")
            out["exec_sync_trace_id"] = d.get("trace_id")
            out["exec_sync_node_results_keys"] = list((d.get("node_results") or {}).keys()) if isinstance(d.get("node_results"), dict) else None
            out_msg = d.get("output_message") or d.get("output") or d.get("response") or d.get("final_output") or ""
            out["exec_sync_output_excerpt"] = (str(out_msg) or "")[:1500]
            # full summary fields
            summ = d.get("summary") or {}
            if isinstance(summ, dict):
                out["exec_sync_summary_keys"] = list(summ.keys())
                out["exec_sync_summary_excerpt"] = json.dumps(summ, default=str)[:800]
            # look for citation/source fields
            for ck in ("citations", "sources", "chunk_refs", "references", "kb_refs"):
                if ck in d:
                    out[f"exec_sync_has_{ck}"] = True
                    out[f"exec_sync_{ck}_sample"] = str(d.get(ck))[:600]
            # raw tool calls / events
            tc = d.get("tool_calls") or d.get("events") or d.get("trace")
            if tc:
                out["exec_sync_tool_calls_sample"] = str(tc)[:1500]
        else:
            out["exec_sync_raw"] = str(d)[:600]
    else:
        out["exec_sync_raw"] = str(j)[:600]

    # 7. SSE stream test
    sse_body = {
        "message": "Search the KB for the most relevant document and return the top 3 chunks with their source identifiers.",
        "stream": True,
    }
    sse_code, events = get_sse(f"/api/agents/{agent_id}/execute", token, sse_body, timeout=180)
    out["sse_http_status"] = sse_code
    out["sse_event_count"] = len(events)
    # distinct event names
    names = {}
    for e in events:
        n = e.get("event") or "default"
        names[n] = names.get(n, 0) + 1
    out["sse_event_kinds"] = names
    # surface any tool_call/knowledge_search events
    tool_evts = [e for e in events if e.get("event") in ("tool_call", "tool_start", "tool_use", "tool_result")]
    out["sse_tool_event_count"] = len(tool_evts)
    out["sse_tool_event_sample"] = [
        {"event": e["event"], "data_excerpt": e["data"][:400]} for e in tool_evts[:3]
    ]
    # last event
    if events:
        out["sse_first_event"] = {"event": events[0].get("event"), "data_excerpt": events[0]["data"][:300]}
        out["sse_last_event"] = {"event": events[-1].get("event"), "data_excerpt": events[-1]["data"][:600]}

    # 8. Atlas: list graphs
    s, j, _ = req("GET", "/api/atlas/graphs", token=token)
    out["atlas_graphs_status"] = s
    graphs = []
    if isinstance(j, dict):
        graphs = j.get("data") if isinstance(j.get("data"), list) else (j if isinstance(j, list) else [])
    elif isinstance(j, list):
        graphs = j
    out["atlas_graph_count"] = len(graphs) if isinstance(graphs, list) else None
    # pick one with nodes
    chosen_graph = None
    for g in graphs or []:
        nc = g.get("node_count") or g.get("nodes") or 0
        if isinstance(nc, int) and nc > 0:
            chosen_graph = g
            break
    if chosen_graph is None and graphs:
        # fetch each to check node count
        for g in graphs[:10]:
            gid = g.get("id")
            if not gid:
                continue
            s2, j2, _ = req("GET", f"/api/atlas/graphs/{gid}", token=token)
            if s2 == 200:
                d = j2.get("data", j2) if isinstance(j2, dict) else j2
                nodes = d.get("nodes") if isinstance(d, dict) else None
                if isinstance(nodes, list) and len(nodes) > 0:
                    chosen_graph = {**g, "node_count": len(nodes)}
                    break
    out["chosen_atlas_graph"] = {
        "id": chosen_graph.get("id"),
        "name": chosen_graph.get("name"),
        "node_count": chosen_graph.get("node_count"),
    } if chosen_graph else None

    # 9. Build atlas-using agent
    if chosen_graph:
        atlas_agent_body = {
            "name": f"uat-atlas-agent-{int(time.time())}",
            "system_prompt": "You query the knowledge graph using atlas_query and return what you find.",
            "model_config": {
                "model": "claude-haiku-4-5-20251001",
                "tools": ["atlas_query"],
                "atlas_graphs": [chosen_graph["id"]],
                "temperature": 0.2,
            },
            "category": "audit",
        }
        s, j, _ = req("POST", "/api/agents", token=token, body=atlas_agent_body)
        out["atlas_agent_create_status"] = s
        if s in (200, 201):
            atlas_agent_id = j["data"]["id"]
            out["atlas_agent_id"] = atlas_agent_id
            # activate
            req("PUT", f"/api/agents/{atlas_agent_id}", token=token, body={"status": "active"})
            atlas_exec_body = {
                "message": f"Use atlas_query on graph {chosen_graph['id']} to list any 5 nodes and their types.",
                "stream": False,
                "wait": True,
                "wait_timeout_seconds": 180,
            }
            t0 = time.time()
            s, j, _ = req("POST", f"/api/agents/{atlas_agent_id}/execute", token=token, body=atlas_exec_body, timeout=240)
            out["atlas_exec_status"] = s
            out["atlas_exec_elapsed_s"] = round(time.time() - t0, 1)
            if isinstance(j, dict):
                d = j.get("data", j)
                if isinstance(d, dict):
                    out["atlas_exec_keys"] = list(d.keys())
                    om = d.get("output_message") or d.get("output") or d.get("response") or ""
                    out["atlas_exec_output_excerpt"] = str(om)[:1500]
                    out["atlas_exec_status_field"] = d.get("status")
                    out["atlas_exec_execution_id"] = d.get("execution_id") or d.get("id")
        else:
            out["atlas_agent_create_err"] = j

    # 10. invoke_agent recursion: create wrapper agent that calls the first one
    wrapper_body = {
        "name": f"uat-wrapper-{int(time.time())}",
        "system_prompt": (
            f"You delegate research to other agents via invoke_agent. "
            f"For any user question, call invoke_agent with agent_id='{agent_id}' and pass the user message."
        ),
        "model_config": {
            "model": "claude-haiku-4-5-20251001",
            "tools": ["invoke_agent"],
            "temperature": 0.2,
        },
        "category": "audit",
    }
    s, j, _ = req("POST", "/api/agents", token=token, body=wrapper_body)
    out["wrapper_create_status"] = s
    if s in (200, 201):
        wrapper_id = j["data"]["id"]
        req("PUT", f"/api/agents/{wrapper_id}", token=token, body={"status": "active"})
        wrap_exec_body = {
            "message": "Delegate this to the KB agent: what does the knowledge base contain?",
            "stream": False,
            "wait": True,
            "wait_timeout_seconds": 180,
        }
        t0 = time.time()
        s, j, _ = req("POST", f"/api/agents/{wrapper_id}/execute", token=token, body=wrap_exec_body, timeout=240)
        out["wrapper_exec_status"] = s
        out["wrapper_exec_elapsed_s"] = round(time.time() - t0, 1)
        if isinstance(j, dict):
            d = j.get("data", j)
            if isinstance(d, dict):
                om = d.get("output_message") or d.get("output") or d.get("response") or ""
                out["wrapper_exec_output_excerpt"] = str(om)[:1200]
                out["wrapper_exec_status_field"] = d.get("status")
            else:
                out["wrapper_exec_raw"] = str(d)[:600]

    # 11. Pull execution detail for trace ids / cost / events
    exec_id_to_check = out.get("exec_sync_execution_id")
    if exec_id_to_check:
        s, j, _ = req("GET", f"/api/executions/{exec_id_to_check}", token=token)
        out["exec_detail_status"] = s
        if isinstance(j, dict):
            d = j.get("data", j)
            if isinstance(d, dict):
                out["exec_detail_keys"] = list(d.keys())
                for k in ("trace_id", "total_cost_usd", "total_cost", "input_tokens", "output_tokens", "cost_usd", "tokens", "events_count", "cost", "model_used", "status", "failure_code", "error_message", "duration_ms"):
                    if k in d:
                        out[f"exec_detail_{k}"] = d.get(k)
                tcs = d.get("tool_calls")
                out["exec_detail_tool_calls_count"] = len(tcs) if isinstance(tcs, list) else "n/a"
                if isinstance(tcs, list) and tcs:
                    out["exec_detail_tool_calls_sample"] = json.dumps(tcs[:3], default=str)[:2000]
                nr = d.get("node_results")
                if nr:
                    out["exec_detail_node_results_sample"] = json.dumps(nr, default=str)[:1500]
                om = d.get("output_message")
                if om:
                    out["exec_detail_output_message_excerpt"] = str(om)[:1500]
                et = d.get("execution_trace")
                if et:
                    out["exec_detail_execution_trace_excerpt"] = str(et)[:1500]
        s, j, _ = req("GET", f"/api/executions/{exec_id_to_check}/events", token=token)
        out["exec_events_status"] = s
        if isinstance(j, dict):
            d = j.get("data", j)
            if isinstance(d, list):
                out["exec_events_count"] = len(d)
                names = {}
                for e in d:
                    n = e.get("event_type") or e.get("type") or e.get("event") or "?"
                    names[n] = names.get(n, 0) + 1
                out["exec_events_kinds"] = names

    print(json.dumps(out, indent=2, default=str)[:14000])


if __name__ == "__main__":
    main()
