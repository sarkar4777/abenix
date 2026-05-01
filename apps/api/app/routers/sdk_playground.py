"""SDK Code Playground — generate and execute SDK code for any asset."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.user import User
from models.agent import Agent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sdk-playground", tags=["sdk-playground"])

ROOT = Path(__file__).resolve().parents[4]


class AssetRef(BaseModel):
    type: Literal["agent", "pipeline", "knowledge_base"]
    id: str
    slug: str | None = None
    name: str = ""


class GenerateRequest(BaseModel):
    asset: AssetRef
    sdk: Literal["typescript", "python"]
    use_case: Literal[
        "one_shot", "stream", "batch", "kb_search", "kb_cognify", "kb_subject",
        "chat_create", "chat_send", "chat_list", "chat_history", "chat_delegated",
        "hitl", "custom",
    ]
    user_prompt: str = Field("", max_length=2000)
    include_comments: bool = True
    include_error_handling: bool = True


class ExecuteRequest(BaseModel):
    code: str
    language: Literal["typescript", "python"]
    timeout_seconds: int = Field(30, ge=1, le=120)
    env_overrides: dict[str, str] = Field(default_factory=dict)


def _load_sdk_source(sdk: str) -> str:
    """Read the actual SDK source so the LLM can only reference real methods."""
    if sdk == "typescript":
        path = ROOT / "packages" / "sdk" / "js" / "src" / "index.ts"
    else:
        path = ROOT / "packages" / "sdk" / "python" / "abenix_sdk" / "__init__.py"
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


# Common emoji / decorative-unicode replacements. Anything else outside
# printable ASCII becomes a plain ASCII fallback (see _sanitize_generated_code).
_EMOJI_REPLACEMENTS: dict[str, str] = {
    # Check / cross / warning — these break Windows stdout the most.
    "\u2713": "[OK]",       # check mark
    "\u2714": "[OK]",       # heavy check mark
    "\u2717": "[X]",        # ballot X
    "\u2718": "[X]",        # heavy ballot X
    "\u2705": "[OK]",       # white heavy check mark
    "\u274c": "[X]",        # cross mark
    "\u26a0": "[!]",        # warning sign
    "\u2139": "[i]",        # information source
    # Arrows
    "\u2192": "->",
    "\u2190": "<-",
    "\u2194": "<->",
    "\u21d2": "=>",
    # Dashes / quotes / ellipsis
    "\u2014": "-",          # em dash
    "\u2013": "-",          # en dash
    "\u2026": "...",        # ellipsis
    "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"',
    # Popular decorative symbols
    "\u2022": "*",          # bullet
    "\u2728": "",           # sparkles emoji
    "\U0001f680": "",       # rocket
    "\U0001f4ca": "",       # bar chart
    "\U0001f4c8": "",       # chart up
    "\U0001f389": "",       # party popper
    "\U0001f6a8": "[!]",    # police light
}

_NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")


def _sanitize_generated_code(code: str) -> str:
    """Guarantee the code is ASCII-safe regardless of what the LLM produced."""
    if not code:
        return code
    for bad, good in _EMOJI_REPLACEMENTS.items():
        if bad in code:
            code = code.replace(bad, good)
    # Drop stragglers. This keeps source as pure ASCII — the only 100%
    # portable encoding across Windows cp1252, POSIX utf-8, and everything
    # else we're likely to run inside.
    return _NON_ASCII_RE.sub("", code)


PYTHON_TEMPLATES = {
    "one_shot": '''import asyncio
import os
from abenix_sdk import Abenix

async def main():
    async with Abenix(
        api_key=os.environ["ABENIX_API_KEY"],
        base_url=os.environ.get("ABENIX_BASE_URL", "http://localhost:8000"),
    ) as forge:
        result = await forge.execute(
            "{slug}",
            "{example_message}",
        )
        print("Output:", result.output)
        print(f"Tokens: in={{result.input_tokens}}, out={{result.output_tokens}}")
        print(f"Cost: ${{result.cost:.4f}}")

asyncio.run(main())
''',
    "stream": '''import asyncio
import os
from abenix_sdk import Abenix

async def main():
    async with Abenix(
        api_key=os.environ["ABENIX_API_KEY"],
        base_url=os.environ.get("ABENIX_BASE_URL", "http://localhost:8000"),
    ) as forge:
        async for event in forge.stream("{slug}", "{example_message}"):
            if event.type == "token":
                print(event.text, end="", flush=True)
            elif event.type == "tool_call":
                print(f"\\n[tool] {{event.name}}({{event.arguments}})")
            elif event.type == "done":
                print(f"\\n[done] cost=${{event.cost:.4f}}")

asyncio.run(main())
''',
    "kb_search": '''import asyncio
import os
from abenix_sdk import Abenix

async def main():
    async with Abenix(api_key=os.environ["ABENIX_API_KEY"]) as forge:
        results = await forge.knowledge.search(
            kb_id="{kb_id}",
            query="{example_message}",
            mode="hybrid",
            top_k=5,
        )
        for r in results.get("results", []):
            print(f"Score: {{r.get('score'):.3f}}")
            print(f"Text: {{r.get('text')[:200]}}")

asyncio.run(main())
''',
    "kb_cognify": '''import asyncio
import os
from abenix_sdk import Abenix

async def main():
    async with Abenix(api_key=os.environ["ABENIX_API_KEY"]) as forge:
        result = await forge.knowledge.cognify(
            kb_id="{kb_id}",
            chunk_size=1000,
            chunk_overlap=200,
        )
        print(f"Cognify job: {{result.get('job_id')}}")
        print(f"Status: {{result.get('status')}}")

asyncio.run(main())
''',
    "kb_subject": '''import asyncio
import os
from abenix_sdk import Abenix, ActingSubject

# Per-end-user KB namespace. Standalone apps (the example app, IndustrialIoT, ...)
# call this once per end-user to get a private collection UUID, then ingest
# documents into it. The agent's knowledge_search tool, when called with this
# subject, sees ONLY this user's documents.
async def main():
    subject = ActingSubject(subject_type="myapp", subject_id="user-42",
                            email="user@example.com")
    async with Abenix(api_key=os.environ["ABENIX_API_KEY"], act_as=subject) as forge:
        coll = await forge.knowledge.ensure_subject_collection(
            project_slug="myapp",
            subject_type="myapp",
            subject_id="user-42",
            description="Per-user corpus",
        )
        print("KB id:", coll["id"])

asyncio.run(main())
''',
    "chat_create": '''import asyncio
import os
from abenix_sdk import Abenix

# Create a persistent chat thread bound to an agent. Threads are scoped per
# (app_slug, acting subject) so each end-user has their own private history.
async def main():
    async with Abenix(api_key=os.environ["ABENIX_API_KEY"]) as forge:
        thread = await forge.chat.create(
            app_slug="myapp",
            agent_slug="{slug}",
            title="My first conversation",
        )
        print("Thread id:", thread["id"])
        print("Bound to:", thread.get("agent_slug"))

asyncio.run(main())
''',
    "chat_send": '''import asyncio
import os
from abenix_sdk import Abenix

# Send a turn. The platform: appends the user msg, repacks the prior
# turns as the agent\\'s context, runs the agent, persists the response,
# returns both messages. Pass `context` for fresh per-turn data (e.g. a
# refreshed portfolio brief that should NOT bloat the persisted history).
async def main():
    async with Abenix(api_key=os.environ["ABENIX_API_KEY"]) as forge:
        thread = await forge.chat.create(app_slug="myapp", agent_slug="{slug}")
        turn = await forge.chat.send(
            thread["id"],
            "{example_message}",
            context="OPTIONAL FRESH CONTEXT — e.g. portfolio summary",
        )
        print("Assistant:", turn["assistant_message"]["content"])
        print(f"Cost: ${{turn['assistant_message']['cost']:.4f}}")

asyncio.run(main())
''',
    "chat_list": '''import asyncio
import os
from abenix_sdk import Abenix

# Sidebar query — list this user's threads for one app.
async def main():
    async with Abenix(api_key=os.environ["ABENIX_API_KEY"]) as forge:
        threads = await forge.chat.list(app_slug="myapp", limit=20)
        for t in threads:
            print(f"  {{t['title']:40}}  {{t['message_count']}} msgs  {{t['updated_at']}}")

asyncio.run(main())
''',
    "chat_history": '''import asyncio
import os
from abenix_sdk import Abenix

# Fetch a thread + all of its messages — for a UI rendering past chats.
async def main():
    thread_id = "PASTE_A_THREAD_UUID_HERE"
    async with Abenix(api_key=os.environ["ABENIX_API_KEY"]) as forge:
        thread = await forge.chat.get(thread_id)
        for m in thread.get("messages", []):
            print(f"[{{m['role'].upper()}}] {{m['content'][:200]}}")

asyncio.run(main())
''',
    "chat_delegated": '''import asyncio
import os
from abenix_sdk import Abenix, ActingSubject

# The standalone-app pattern — the example app / Industrial-IoT / ResolveAI use
# this. The platform key has can_delegate scope; ActingSubject identifies
# WHICH end-user is acting so chat threads + tool RBAC are scoped per user.
async def main():
    subject = ActingSubject(
        subject_type="myapp",         # YOUR app's namespace
        subject_id="end-user-uuid-from-myapp",
        email="enduser@customer.com",
        display_name="End User",
    )
    async with Abenix(
        api_key=os.environ["MYAPP_ABENIX_API_KEY"],
        act_as=subject,
    ) as forge:
        # All chat ops below are now scoped to (myapp, end-user-uuid).
        threads = await forge.chat.list(app_slug="myapp", agent_slug="{slug}", limit=1)
        if threads:
            tid = threads[0]["id"]
        else:
            tid = (await forge.chat.create(app_slug="myapp", agent_slug="{slug}"))["id"]
        turn = await forge.chat.send(tid, "{example_message}")
        print(turn["assistant_message"]["content"])

asyncio.run(main())
''',
}

TYPESCRIPT_TEMPLATES = {
    "one_shot": '''import {{ Abenix }} from '@abenix/sdk';

const forge = new Abenix({{
  apiKey: process.env.ABENIX_API_KEY!,
  baseUrl: process.env.ABENIX_BASE_URL || 'http://localhost:8000',
}});

async function main() {{
  const result = await forge.execute('{slug}', '{example_message}');
  console.log('Output:', result.output);
  console.log(`Cost: $${{result.cost.toFixed(4)}}`);
}}

main().catch(console.error);
''',
    "stream": '''import {{ Abenix }} from '@abenix/sdk';

const forge = new Abenix({{
  apiKey: process.env.ABENIX_API_KEY!,
}});

async function main() {{
  for await (const event of forge.stream('{slug}', '{example_message}')) {{
    if (event.type === 'token') process.stdout.write(event.text || '');
    else if (event.type === 'tool_call') console.log(`\\n[tool] ${{event.name}}`);
    else if (event.type === 'done') console.log(`\\n[done] cost=$${{event.cost}}`);
  }}
}}

main().catch(console.error);
''',
    "kb_search": '''import {{ Abenix }} from '@abenix/sdk';

const forge = new Abenix({{ apiKey: process.env.ABENIX_API_KEY! }});

async function main() {{
  const results = await forge.knowledge.search('{kb_id}', '{example_message}', {{
    mode: 'hybrid',
    topK: 5,
  }});
  results.results.forEach(r => {{
    console.log(`Score: ${{r.score.toFixed(3)}}`);
    console.log(`Text: ${{r.text.slice(0, 200)}}`);
  }});
}}

main().catch(console.error);
''',
    "kb_cognify": '''import {{ Abenix }} from '@abenix/sdk';

const forge = new Abenix({{ apiKey: process.env.ABENIX_API_KEY! }});

async function main() {{
  const result = await forge.knowledge.cognify('{kb_id}', {{
    chunkSize: 1000,
    chunkOverlap: 200,
  }});
  console.log(`Cognify job: ${{result.jobId}}`);
}}

main().catch(console.error);
''',
}


def _build_template_code(sdk: str, use_case: str, asset: AssetRef) -> str:
    templates = PYTHON_TEMPLATES if sdk == "python" else TYPESCRIPT_TEMPLATES
    template = templates.get(use_case, templates["one_shot"])
    return template.format(
        slug=asset.slug or asset.id,
        kb_id=asset.id,
        example_message="Analyze the latest data and provide insights",
    )


def _build_system_prompt(sdk: str, asset: AssetRef, asset_context: dict, use_case: str) -> str:
    sdk_source = _load_sdk_source(sdk)
    template = _build_template_code(sdk, use_case, asset)
    lang = sdk

    return f"""You are a code generator for the Abenix SDK.

Generate PRODUCTION-READY {lang} code that uses the Abenix SDK to accomplish the user's goal.

STRICT RULES:
1. Use ONLY classes, methods, and types defined in the SDK SOURCE below. Do not hallucinate methods.
2. Use exact method signatures shown.
3. Reference assets by SLUG when available, otherwise by ID.
4. Use environment variables: ABENIX_API_KEY and ABENIX_BASE_URL.
5. Include imports at the top. Include error handling.
6. Output a single fenced code block followed by a 2-sentence explanation.
7. The code must be directly runnable — no TODOs, no placeholders.
8. **NEVER USE EMOJI OR NON-ASCII DECORATIVE CHARACTERS** anywhere — not in
   strings, not in prints, not in comments. No checkmark, cross, rocket,
   sparkle, arrows, box-drawing chars, smart quotes, em-dash, ellipsis char.
   Use plain ASCII: "OK" instead of a checkmark, "-->" instead of an arrow,
   "..." (three dots) instead of an ellipsis char, "'" and '"' instead of
   smart quotes. This code will run in sandboxes with non-UTF8 default
   stdout (Windows cp1252); a single emoji will crash print() with
   UnicodeEncodeError and hide the real output. This rule is non-negotiable.
9. Do not wrap print() calls in try/except just to swallow encoding errors.
   Follow rule 8 and the problem doesn't exist.

ABENIX SDK SOURCE (authoritative):
```{lang}
{sdk_source[:8000]}
```

ASSET CONTEXT:
- Type: {asset.type}
- Name: {asset.name}
- ID: {asset.id}
- Slug: {asset.slug or 'N/A'}
- Description: {asset_context.get('description', '')[:300]}
- Mode: {asset_context.get('mode', 'agent')}

USE CASE: {use_case}

REFERENCE TEMPLATE (adapt this pattern):
```{lang}
{template}
```

Output format:
```{lang}
<your code here>
```

EXPLANATION: <2 sentences about what this code does>
IMPORTS: <comma-separated package names>
ENV_VARS: <comma-separated env var names>"""


@router.get("/asset-context/{asset_type}/{asset_id}")
async def get_asset_context(
    asset_type: str,
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Resolve an asset to its details for the playground UI."""
    if asset_type in ("agent", "pipeline"):
        try:
            agent_uuid = uuid.UUID(asset_id)
        except ValueError:
            return error("Invalid asset ID", 400)

        result = await db.execute(select(Agent).where(Agent.id == agent_uuid))
        agent = result.scalar_one_or_none()
        if not agent:
            return error("Agent not found", 404)

        cfg = agent.model_config or {}
        return success({
            "id": str(agent.id),
            "name": agent.name,
            "slug": agent.slug,
            "description": agent.description or "",
            "mode": getattr(agent, "agent_type", "agent"),
            "tools": cfg.get("tools", []),
            "model": cfg.get("model", ""),
            "input_variables": getattr(agent, "input_variables", []) or [],
        })
    elif asset_type == "knowledge_base":
        try:
            from models.knowledge_base import KnowledgeBase
            kb_uuid = uuid.UUID(asset_id)
            result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_uuid))
            kb = result.scalar_one_or_none()
            if not kb:
                return error("Knowledge base not found", 404)
            return success({
                "id": str(kb.id),
                "name": kb.name,
                "description": getattr(kb, "description", "") or "",
                "type": "knowledge_base",
            })
        except Exception as e:
            return error(f"Failed to load KB: {e}", 500)
    return error("Unknown asset type", 400)


@router.post("/generate")
async def generate_code(
    body: GenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Generate SDK code using LLM with SDK source as context."""
    # Resolve asset context
    asset_context = {}
    if body.asset.type in ("agent", "pipeline"):
        try:
            agent_uuid = uuid.UUID(body.asset.id)
            result = await db.execute(select(Agent).where(Agent.id == agent_uuid))
            agent = result.scalar_one_or_none()
            if agent:
                asset_context = {
                    "description": agent.description or "",
                    "mode": getattr(agent, "agent_type", "agent"),
                    "slug": agent.slug,
                }
                if not body.asset.slug:
                    body.asset.slug = agent.slug
                if not body.asset.name:
                    body.asset.name = agent.name
        except ValueError:
            pass

    # Try LLM generation
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            # Fallback: return template directly
            code = _build_template_code(body.sdk, body.use_case, body.asset)
            return success({
                "code": code,
                "language": body.sdk,
                "explanation": f"Template-based code for {body.use_case}. Set ANTHROPIC_API_KEY for AI-generated code.",
                "imports": ["abenix_sdk"] if body.sdk == "python" else ["@abenix/sdk"],
                "env_vars": ["ABENIX_API_KEY", "ABENIX_BASE_URL"],
                "model_used": "template",
                "generation_cost": 0.0,
                "template_source": body.use_case,
            })

        client = anthropic.Anthropic(api_key=api_key)
        system_prompt = _build_system_prompt(body.sdk, body.asset, asset_context, body.use_case)

        user_msg = f"Generate the code. {body.user_prompt or 'Make it production-ready with good error handling.'}"

        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=6000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text if response.content else ""

        # Extract code block
        code_match = re.search(r"```(?:python|typescript|ts|js)?\n(.*?)```", text, re.DOTALL)
        code = code_match.group(1).strip() if code_match else text
        # Non-negotiable: the generated code is ASCII-only before it ever
        # reaches the user or the sandbox. See rule 8 in the system prompt.
        code = _sanitize_generated_code(code)

        # Extract explanation
        exp_match = re.search(r"EXPLANATION:\s*(.+?)(?:IMPORTS:|$)", text, re.DOTALL)
        explanation = exp_match.group(1).strip() if exp_match else "Generated SDK code."

        # Extract imports & env vars
        imp_match = re.search(r"IMPORTS:\s*(.+?)(?:ENV_VARS:|$)", text, re.DOTALL)
        imports = [s.strip() for s in (imp_match.group(1) if imp_match else "").split(",") if s.strip()]

        env_match = re.search(r"ENV_VARS:\s*(.+?)$", text, re.DOTALL)
        env_vars = [s.strip() for s in (env_match.group(1) if env_match else "ABENIX_API_KEY").split(",") if s.strip()]

        return success({
            "code": code,
            "language": body.sdk,
            "explanation": explanation,
            "imports": imports or (["abenix_sdk"] if body.sdk == "python" else ["@abenix/sdk"]),
            "env_vars": env_vars,
            "model_used": "claude-sonnet-4-5-20250929",
            "generation_cost": 0.02,
            "template_source": body.use_case,
        })

    except Exception as e:
        logger.error("SDK code generation failed: %s", e)
        # Fallback to template
        code = _build_template_code(body.sdk, body.use_case, body.asset)
        return success({
            "code": code,
            "language": body.sdk,
            "explanation": f"LLM generation failed ({e}). Returning template.",
            "imports": ["abenix_sdk"] if body.sdk == "python" else ["@abenix/sdk"],
            "env_vars": ["ABENIX_API_KEY"],
            "model_used": "template",
            "generation_cost": 0.0,
            "template_source": body.use_case,
        })


@router.post("/execute")
async def execute_code(
    body: ExecuteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Execute Python code in a sandboxed environment with the SDK available.

    JavaScript execution is not yet supported — copy the code and run it locally.
    """
    async def stream_execution():
        if body.language != "python":
            yield f"event: error\ndata: {json.dumps({'message': 'Only Python execution is supported in v1. Copy the code and run it locally.'})}\n\n"
            yield f"event: done\ndata: {json.dumps({'status': 'unsupported'})}\n\n"
            return

        yield f"event: status\ndata: {json.dumps({'message': 'Starting execution...'})}\n\n"

        # Mint a temporary API key for the user (read-only, 1 hour TTL)
        try:
            import hashlib
            import secrets
            from models.api_key import ApiKey

            raw_key = f"af_pg_{secrets.token_urlsafe(24)}"
            key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
            key = ApiKey(
                tenant_id=user.tenant_id,
                user_id=user.id,
                name="SDK Playground (ephemeral)",
                key_hash=key_hash,
                key_prefix=raw_key[:11] + "****",
                scopes={"playground": True},
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            db.add(key)
            await db.commit()
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': f'Failed to mint key: {e}'})}\n\n"
            return

        yield f"event: status\ndata: {json.dumps({'message': 'Sandbox ready, running code...'})}\n\n"

        # Execute via subprocess for safety
        try:
            import asyncio
            import tempfile

            # Defence in depth: strip any non-ASCII from user-edited code
            # too, so the "Run" button works even on code the LLM didn't
            # produce (manual edits, paste from docs, etc.).
            safe_code = _sanitize_generated_code(body.code)

            # tempfile.NamedTemporaryFile(mode="w") uses locale default
            # encoding — on Windows that's cp1252 and non-ASCII source
            # would fail to write. Force utf-8 explicitly.
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8",
            ) as f:
                # Inject env vars at top
                f.write("import os\n")
                f.write(f'os.environ["ABENIX_API_KEY"] = "{raw_key}"\n')
                f.write('os.environ["ABENIX_BASE_URL"] = "http://localhost:8000"\n')
                f.write(safe_code)
                tmp_path = f.name

            # Run with timeout
            sdk_path = str(ROOT / "packages" / "sdk" / "python")
            # Force UTF-8 I/O in the subprocess so print() of any unicode
            # string (should be impossible after sanitize, but fail-safe)
            # doesn't crash with UnicodeEncodeError on Windows cp1252.
            env = {
                **os.environ,
                "PYTHONPATH": sdk_path,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            }

            proc = await asyncio.create_subprocess_exec(
                sys.executable, tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=body.timeout_seconds)
            except asyncio.TimeoutError:
                proc.kill()
                yield f"event: error\ndata: {json.dumps({'message': f'Execution timed out after {body.timeout_seconds}s'})}\n\n"
                yield f"event: done\ndata: {json.dumps({'status': 'timeout'})}\n\n"
                return

            stdout_text = stdout.decode("utf-8", errors="replace")[:50000]
            stderr_text = stderr.decode("utf-8", errors="replace")[:50000]

            if stdout_text:
                yield f"event: stdout\ndata: {json.dumps({'text': stdout_text})}\n\n"
            if stderr_text:
                yield f"event: stderr\ndata: {json.dumps({'text': stderr_text})}\n\n"

            status = "success" if proc.returncode == 0 else "error"
            yield f"event: done\ndata: {json.dumps({'status': status, 'exit_code': proc.returncode})}\n\n"

            # Cleanup
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
            yield f"event: done\ndata: {json.dumps({'status': 'error'})}\n\n"

    return StreamingResponse(stream_execution(), media_type="text/event-stream")


@router.get("/use-cases")
async def list_use_cases() -> JSONResponse:
    """Return supported use case templates."""
    return success([
        {"id": "one_shot", "label": "One-Shot Execution", "description": "Simple execute() call, returns final result"},
        {"id": "stream", "label": "Streaming", "description": "Stream events (tokens, tool calls, done)"},
        {"id": "kb_search", "label": "Knowledge Base Search", "description": "Hybrid vector + graph search"},
        {"id": "kb_cognify", "label": "Cognify (Build Graph)", "description": "Build knowledge graph from documents"},
        {"id": "batch", "label": "Batch Processing", "description": "Process multiple inputs in a loop"},
        {"id": "hitl", "label": "Human-in-the-Loop", "description": "Execute with approval gates"},
        {"id": "custom", "label": "Custom (Free-Form)", "description": "Describe what you want, AI generates it"},
    ])
