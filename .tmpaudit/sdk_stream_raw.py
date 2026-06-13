"""Compare raw SSE bytes vs SDK-parsed stream events to localise the bug."""
import asyncio, json, httpx

API_KEY = "af_luhS8NNNz0e1VoteEuspMFbM1X2GNeEPNt0HQMBjtgQ"
BASE = "http://localhost:8000"
AGENT_ID = "9cb47129-47c3-4d7b-8681-92dee67f715c"

async def main():
    raw_lines = []
    async with httpx.AsyncClient(base_url=BASE, headers={"X-API-Key": API_KEY, "Content-Type": "application/json"}, timeout=60.0) as http:
        async with http.stream("POST", f"/api/agents/{AGENT_ID}/execute", json={"message": "Say PING.", "stream": True}) as resp:
            print("status:", resp.status_code)
            async for line in resp.aiter_lines():
                raw_lines.append(line)
                if len(raw_lines) >= 40:
                    break
    print(f"--- raw lines ({len(raw_lines)}) ---")
    for i, l in enumerate(raw_lines):
        print(f"{i:02d}: {l!r}")

    # Now drive the SDK
    print("--- SDK parsed events ---")
    from abenix_sdk import Abenix
    events = []
    async with Abenix(api_key=API_KEY, base_url=BASE, timeout=60.0) as forge:
        async for ev in forge.stream(AGENT_ID, "Say PING."):
            events.append(ev)
            if len(events) >= 25:
                break
    for ev in events:
        print(ev)

asyncio.run(main())
