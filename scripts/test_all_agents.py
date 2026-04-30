#!/usr/bin/env python3
"""Test all OOB agents via the API to identify which ones execute successfully."""
import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict

API_URL = "http://localhost:8000"


def api_call(method: str, path: str, token: str | None = None, body: dict | None = None, timeout: int = 60):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{API_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"error": {"message": f"HTTP {e.code}", "code": e.code}}
    except Exception as e:
        return {"error": {"message": str(e), "code": -1}}


def main():
    # Login
    auth = api_call("POST", "/api/auth/login", body={"email": "demo@abenix.dev", "password": "Demo123456"})
    token = auth.get("data", {}).get("access_token")
    if not token:
        print(f"Login failed: {auth}")
        sys.exit(1)
    print(f"Logged in as demo@abenix.dev")

    # Get agents
    agents_resp = api_call("GET", "/api/agents", token=token)
    agents = agents_resp.get("data", [])
    oob = [a for a in agents if a.get("agent_type") == "oob"]
    print(f"Found {len(oob)} OOB agents\n")

    # Classify agents
    chat_agents = [a for a in oob if (a.get("model_config_") or {}).get("mode") != "pipeline"]
    pipeline_agents = [a for a in oob if (a.get("model_config_") or {}).get("mode") == "pipeline"]

    print(f"Chat agents: {len(chat_agents)}")
    print(f"Pipeline agents: {len(pipeline_agents)}\n")

    results = {"chat_ok": [], "chat_fail": [], "pipeline_ok": [], "pipeline_fail": []}

    # Test each chat agent
    print("=" * 70)
    print("CHAT AGENTS")
    print("=" * 70)
    for a in chat_agents:
        slug = a["slug"]
        # Pipeline-mode agents (despite being classified as chat) can chain many
        # LLM/tool calls; give them more time.
        is_pipe = (a.get("model_config_") or {}).get("mode") == "pipeline"
        resp = api_call(
            "POST",
            f"/api/agents/{a['id']}/execute",
            token=token,
            body={"message": "Say hello in 3 words.", "stream": False},
            timeout=300 if is_pipe else 90,
        )
        if resp.get("data") and resp["data"].get("output"):
            out_len = len(resp["data"]["output"])
            results["chat_ok"].append((slug, out_len))
            print(f"  OK   {slug:40} ({out_len} chars)")
        elif resp.get("data") and resp["data"].get("status") == "completed":
            # Pipeline-mode agent that completed successfully
            nodes = resp["data"].get("node_results", {})
            total = len(nodes)
            ok_nodes = sum(1 for n in nodes.values() if n.get("status") == "completed")
            results["chat_ok"].append((slug, f"{ok_nodes}/{total} nodes"))
            print(f"  OK   {slug:40} ({ok_nodes}/{total} pipeline nodes)")
        elif resp.get("data") and resp["data"].get("status") == "partial":
            # Partial pipeline success — all nodes attempted, some failed
            nodes = resp["data"].get("node_results", {})
            total = len(nodes)
            ok_nodes = sum(1 for n in nodes.values() if n.get("status") == "completed")
            if ok_nodes == total:
                results["chat_ok"].append((slug, f"{ok_nodes}/{total}"))
                print(f"  OK   {slug:40} ({ok_nodes}/{total} nodes partial-ok)")
            else:
                first_err = next((str(n.get("error", "?"))[:80] for n in nodes.values() if n.get("status") == "failed"), "?")
                results["chat_fail"].append((slug, f"{ok_nodes}/{total}: {first_err}"))
                print(f"  FAIL {slug:40} -> {ok_nodes}/{total} nodes: {first_err[:60]}")
        else:
            err = (resp.get("error") or {}).get("message", str(resp))[:100]
            results["chat_fail"].append((slug, err))
            print(f"  FAIL {slug:40} -> {err}")

    # Test each pipeline agent
    print()
    print("=" * 70)
    print("PIPELINE AGENTS")
    print("=" * 70)
    for a in pipeline_agents:
        slug = a["slug"]
        resp = api_call(
            "POST",
            f"/api/agents/{a['id']}/execute",
            token=token,
            body={"message": "Process this test message.", "stream": False},
            timeout=300,
        )
        if resp.get("data") and resp["data"].get("output"):
            out_len = len(resp["data"]["output"])
            results["pipeline_ok"].append((slug, out_len))
            print(f"  OK   {slug:40} ({out_len} chars)")
        elif resp.get("data") and resp["data"].get("status") in ("completed", "partial"):
            nodes = resp["data"].get("node_results", {})
            ok_nodes = sum(1 for n in nodes.values() if n.get("status") == "completed")
            total = len(nodes)
            if ok_nodes == total:
                results["pipeline_ok"].append((slug, f"{ok_nodes}/{total} nodes"))
                print(f"  OK   {slug:40} ({ok_nodes}/{total} nodes)")
            else:
                first_err = next((n.get("error", "?") for n in nodes.values() if n.get("status") == "failed"), "?")
                results["pipeline_fail"].append((slug, f"{ok_nodes}/{total} nodes: {first_err}"[:100]))
                print(f"  PART {slug:40} -> {ok_nodes}/{total} nodes: {first_err[:60]}")
        else:
            err = (resp.get("error") or {}).get("message", str(resp))[:100]
            results["pipeline_fail"].append((slug, err))
            print(f"  FAIL {slug:40} -> {err}")

    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Chat:     {len(results['chat_ok']):3} OK / {len(results['chat_fail']):3} FAIL / {len(chat_agents):3} total")
    print(f"Pipeline: {len(results['pipeline_ok']):3} OK / {len(results['pipeline_fail']):3} FAIL / {len(pipeline_agents):3} total")
    print(f"TOTAL:    {len(results['chat_ok']) + len(results['pipeline_ok']):3} OK / {len(results['chat_fail']) + len(results['pipeline_fail']):3} FAIL / {len(oob):3} total")

    # Categorize failures
    print()
    print("FAILURE CATEGORIES:")
    fail_categories = defaultdict(list)
    for slug, err in results["chat_fail"] + results["pipeline_fail"]:
        key = err.split(":")[0][:60]
        fail_categories[key].append(slug)

    for cat, slugs in sorted(fail_categories.items(), key=lambda x: -len(x[1])):
        print(f"  [{len(slugs)}] {cat}")
        for s in slugs[:3]:
            print(f"      - {s}")


if __name__ == "__main__":
    main()
