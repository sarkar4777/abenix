"""Quality probe: list agents, execute one, stream SSE, list tools."""
import asyncio, json, sys, traceback
from abenix_sdk import Abenix, StreamEvent

API_KEY = "af_luhS8NNNz0e1VoteEuspMFbM1X2GNeEPNt0HQMBjtgQ"
BASE = "http://localhost:8000"

async def main():
    results = {}
    async with Abenix(api_key=API_KEY, base_url=BASE, timeout=60.0) as forge:
        # 1) list agents
        try:
            agents = await forge.agents.list()
            results["agents_list_count"] = len(agents)
            results["agents_first"] = (agents[0] if agents else None) and {
                "id": agents[0].get("id"),
                "slug": agents[0].get("slug"),
                "name": agents[0].get("name"),
            }
            results["agents_list_parses"] = isinstance(agents, list) and (not agents or isinstance(agents[0], dict))
        except Exception as e:
            results["agents_list_error"] = repr(e)

        # 2) list tools
        try:
            tools = await forge.tools.list()
            results["tools_list_count"] = len(tools)
            results["tools_list_parses"] = isinstance(tools, list) and (not tools or isinstance(tools[0], dict))
        except Exception as e:
            results["tools_list_error"] = repr(e)

        # 3) list live executions
        try:
            live = await forge.executions.live()
            results["live_count"] = len(live)
            results["live_parses_dataclass"] = (not live) or hasattr(live[0], "execution_id")
        except Exception as e:
            results["live_error"] = repr(e)

        # 4) pick a simple agent and run synchronously
        target = None
        if results.get("agents_list_count"):
            # pick first agent with a slug we recognize, else first
            for a in agents:
                if a.get("slug") in ("echo", "general-assistant", "chat-agent"):
                    target = a; break
            target = target or agents[0]

        if target:
            results["execute_target"] = {"id": target.get("id"), "slug": target.get("slug"), "name": target.get("name")}
            try:
                er = await forge.execute(
                    target.get("slug") or target["id"],
                    "Say the single word PING and nothing else.",
                )
                results["execute_status"] = er.status
                results["execute_has_output"] = bool(er.output and er.output.strip())
                results["execute_output_preview"] = (er.output or "")[:200]
                results["execute_returns_dataclass"] = type(er).__name__
                results["execute_id"] = er.execution_id
            except Exception as e:
                results["execute_error"] = repr(e)
                results["execute_tb"] = traceback.format_exc()[-800:]

            # 5) stream the same agent
            try:
                stream_events = []
                async for ev in forge.stream(target.get("slug") or target["id"], "Reply ONE token then stop."):
                    stream_events.append({"type": ev.type, "text": ev.text, "name": ev.name})
                    if len(stream_events) >= 25:
                        break
                results["stream_event_count"] = len(stream_events)
                results["stream_event_types"] = sorted({e["type"] for e in stream_events})
                results["stream_yields_dataclass"] = stream_events and all("type" in e for e in stream_events)
                results["stream_first_events"] = stream_events[:6]
            except Exception as e:
                results["stream_error"] = repr(e)
                results["stream_tb"] = traceback.format_exc()[-800:]

    print(json.dumps(results, indent=2, default=str))

asyncio.run(main())
