"""Load Test Playground — AI-generated load test scripts that target a"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent
from models.user import User

router = APIRouter(prefix="/api/load-playground", tags=["load-playground"])


class LoadTarget(BaseModel):
    id: str = ""
    slug: str = ""
    name: str = ""
    type: str = "agent"  # agent | pipeline


class GenerateLoadRequest(BaseModel):
    target: LoadTarget
    scenario: str = Field(default="steady_burst")
    requests: int = Field(default=50, ge=1, le=2000)
    concurrency: int = Field(default=10, ge=1, le=200)
    message_sample: str = Field(default="")
    user_prompt: str = Field(default="")


class ExecuteLoadRequest(BaseModel):
    code: str
    env: dict = Field(default_factory=dict)


SCENARIOS = {
    "steady_burst": "fire N requests spread evenly across the run",
    "thundering_herd": "fire all N requests at t=0 (stress test)",
    "ramp_up": "start at concurrency=1, ramp to target concurrency over 30s",
    "warm_then_spike": "10 warm-up requests, then N requests at full concurrency",
    "mixed_payloads": "alternate between small and large user messages",
}


def _build_system_prompt(
    target: LoadTarget, scenario: str, requests: int, concurrency: int
) -> str:
    agent_ref = target.slug or target.id or target.name or "<agent>"
    return f"""You are a senior SRE who writes Python load tests.

Generate a COMPLETE, RUNNABLE Python 3.12 script that load-tests an Abenix {target.type} at {agent_ref!r}.
The script MUST:

1. Use `asyncio` + `httpx.AsyncClient` (NOT requests / aiohttp).
2. Read these env vars: ABENIX_API_URL, ABENIX_API_KEY. Fail-fast if either is missing.
3. Target the endpoint: POST {{ABENIX_API_URL}}/api/agents/{{AGENT_ID}}/execute with JSON body:
     {{"message": <user_msg>, "stream": false}}
   and header: Authorization: Bearer {{ABENIX_API_KEY}}
4. Use a Semaphore to cap concurrency at {concurrency}.
5. Fire {requests} total requests following the scenario: {scenario} — {SCENARIOS.get(scenario, scenario)}.
6. For each response:
   - record start/end timestamps,
   - status code,
   - parse body.data.duration_ms if present (the platform's own measurement),
   - classify as success (2xx) / client_error (4xx) / server_error (5xx) / timeout.
7. After all requests complete, print a report:
   - total wall-clock time
   - requests/sec (throughput)
   - success count / client_error count / server_error count / timeout count
   - latency percentiles from client-observed RTT: p50, p95, p99, max
   - server-reported duration_ms percentiles (same shape)
   - first 3 failure messages (truncated to 200 chars each)
8. Use a 60-second per-request timeout.
9. Print progress every 10% of requests completed (e.g. "42% 21/50 reqs ok=20 err=1 p95=820ms").
10. The script must be runnable with `python loadtest.py` — no external config files.

Output ONLY the Python code, no prose, no markdown fences. The code MUST start with `import asyncio` or `#!/usr/bin/env python3`."""


async def _llm_generate(system_prompt: str, user_prompt: str) -> tuple[str, str]:
    """Returns (code, model_used). Falls back to a template if no LLM key."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "", "none"
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=6000,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": user_prompt or "Generate the load test script.",
                }
            ],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        # Strip code fences if the model included them
        if text.strip().startswith("```"):
            lines = text.strip().splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)
        return text.strip(), "claude-sonnet-4-5-20250929"
    except Exception:
        return "", "error"


def _template_script(
    target: LoadTarget, scenario: str, requests: int, concurrency: int, sample_msg: str
) -> str:
    """Deterministic fallback — used when no ANTHROPIC_API_KEY is set."""
    return f'''#!/usr/bin/env python3
"""Abenix load test — {target.slug or target.id} ({scenario})

Runs {requests} requests at concurrency={concurrency} and reports p50/p95/p99.
"""
import asyncio, os, statistics, time, json
import httpx

AGENT_ID = {target.id!r}
API_URL = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("ABENIX_API_KEY")
if not API_KEY:
    raise SystemExit("Set ABENIX_API_KEY")

N = {requests}
CONC = {concurrency}
SAMPLE = {sample_msg!r} or "ping"
TIMEOUT = 60.0

async def one_request(client, sem, i, results):
    async with sem:
        t0 = time.perf_counter()
        try:
            r = await client.post(
                f"{{API_URL}}/api/agents/{{AGENT_ID}}/execute",
                headers={{"Authorization": f"Bearer {{API_KEY}}", "Content-Type": "application/json"}},
                json={{"message": SAMPLE, "stream": False}},
                timeout=TIMEOUT,
            )
            rtt = (time.perf_counter() - t0) * 1000.0
            body = r.json() if r.headers.get("content-type","").startswith("application/json") else {{}}
            server_ms = (body.get("data") or {{}}).get("duration_ms") or 0
            status = "ok" if r.status_code < 300 else ("client_error" if r.status_code < 500 else "server_error")
            results.append({{"rtt_ms": rtt, "server_ms": server_ms, "status": status, "code": r.status_code, "err": None if status == "ok" else r.text[:200]}})
        except asyncio.TimeoutError:
            results.append({{"rtt_ms": TIMEOUT*1000, "server_ms": 0, "status": "timeout", "code": 0, "err": "timeout"}})
        except Exception as e:
            results.append({{"rtt_ms": (time.perf_counter()-t0)*1000, "server_ms": 0, "status": "error", "code": 0, "err": str(e)[:200]}})
        if (len(results) % max(1, N // 10)) == 0:
            ok = sum(1 for r in results if r["status"] == "ok")
            rtts = sorted(r["rtt_ms"] for r in results)
            p95 = rtts[int(len(rtts)*0.95)] if rtts else 0
            print(f"{{len(results)*100//N}}% {{len(results)}}/{{N}} reqs ok={{ok}} err={{len(results)-ok}} p95={{p95:.0f}}ms", flush=True)

async def main():
    sem = asyncio.Semaphore(CONC)
    results = []
    async with httpx.AsyncClient() as client:
        t0 = time.perf_counter()
        await asyncio.gather(*[one_request(client, sem, i, results) for i in range(N)])
        wall = time.perf_counter() - t0

    def pct(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs)-1, int(len(xs)*p))] if xs else 0
    rtts = [r["rtt_ms"] for r in results]
    server = [r["server_ms"] for r in results if r["server_ms"] > 0]
    buckets = {{}}
    for r in results:
        buckets[r["status"]] = buckets.get(r["status"], 0) + 1

    print("")
    print("=" * 50)
    print(f"Target:           {{AGENT_ID}}")
    print(f"Scenario:         {scenario}")
    print(f"Total requests:   {{N}}")
    print(f"Concurrency:      {{CONC}}")
    print(f"Wall time:        {{wall:.2f}}s")
    print(f"Throughput:       {{N/wall:.1f}} req/s")
    print(f"Status buckets:   {{buckets}}")
    print(f"")
    print(f"Client-observed RTT (ms):")
    print(f"  p50  {{pct(rtts,0.50):8.0f}}   p95  {{pct(rtts,0.95):8.0f}}   p99  {{pct(rtts,0.99):8.0f}}   max  {{max(rtts) if rtts else 0:8.0f}}")
    if server:
        print(f"Server duration_ms:")
        print(f"  p50  {{pct(server,0.50):8.0f}}   p95  {{pct(server,0.95):8.0f}}   p99  {{pct(server,0.99):8.0f}}   max  {{max(server):8.0f}}")
    fails = [r for r in results if r["status"] != "ok"][:3]
    if fails:
        print("First failures:")
        for f in fails:
            print(f"  [{{f['status']}}] {{f['err']}}")

asyncio.run(main())
'''


@router.post("/generate")
async def generate_load_script(
    body: GenerateLoadRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Generate a Python load-test script for a specific agent/pipeline."""
    # Resolve target
    if body.target.id:
        try:
            aid = uuid.UUID(body.target.id)
            r = await db.execute(select(Agent).where(Agent.id == aid))
            agent = r.scalar_one_or_none()
            if agent:
                body.target.slug = body.target.slug or agent.slug
                body.target.name = body.target.name or agent.name
                body.target.type = (
                    "pipeline"
                    if (agent.model_config_ or {}).get("mode") == "pipeline"
                    else "agent"
                )
        except ValueError:
            pass

    system_prompt = _build_system_prompt(
        body.target, body.scenario, body.requests, body.concurrency
    )
    extra = body.user_prompt or f"Use message sample: {body.message_sample!r}"
    code, model_used = await _llm_generate(system_prompt, extra)
    if not code:
        code = _template_script(
            body.target,
            body.scenario,
            body.requests,
            body.concurrency,
            body.message_sample,
        )
        model_used = "template"

    return success(
        {
            "code": code,
            "language": "python",
            "model_used": model_used,
            "scenario": body.scenario,
            "requests": body.requests,
            "concurrency": body.concurrency,
            "env_vars": ["ABENIX_API_URL", "ABENIX_API_KEY"],
            "target": body.target.dict(),
        }
    )


@router.post("/execute")
async def execute_load_script(
    body: ExecuteLoadRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Run a generated Python load-test script with an ephemeral 1-hour API key.
    Streams stdout line-by-line over SSE so the user sees live progress."""

    async def stream():
        # Mint an ephemeral API key
        try:
            from models.api_key import ApiKey

            raw_key = f"af_load_{secrets.token_urlsafe(24)}"
            key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
            key = ApiKey(
                tenant_id=user.tenant_id,
                user_id=user.id,
                name="Load Playground (ephemeral)",
                key_hash=key_hash,
                key_prefix=raw_key[:11] + "****",
                scopes={"playground": True, "load_test": True},
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            db.add(key)
            await db.commit()
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': f'Failed to mint API key: {e}'})}\n\n"
            return

        yield f"event: status\ndata: {json.dumps({'message': 'API key minted, writing script'})}\n\n"

        # Write script to temp file
        script_path = Path(tempfile.mkstemp(prefix="loadtest_", suffix=".py")[1])
        script_path.write_text(body.code, encoding="utf-8")

        env = os.environ.copy()
        env.update(body.env or {})
        env["ABENIX_API_KEY"] = raw_key
        env.setdefault("ABENIX_API_URL", "http://localhost:8000")

        yield f"event: status\ndata: {json.dumps({'message': f'Executing {script_path.name}'})}\n\n"

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        assert proc.stdout
        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=600)
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                yield f"event: line\ndata: {json.dumps({'text': text})}\n\n"
            rc = await proc.wait()
            yield f"event: done\ndata: {json.dumps({'status': 'completed', 'exit_code': rc})}\n\n"
        except asyncio.TimeoutError:
            proc.kill()
            yield f"event: error\ndata: {json.dumps({'message': 'Execution timed out after 10 minutes'})}\n\n"
        finally:
            try:
                script_path.unlink()
            except Exception:
                pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
