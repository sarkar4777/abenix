"""Talk-to-workflow shell — POST a single command, get a structured result."""
from __future__ import annotations

import json as _json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.services.workflow_shell_grammar import GRAMMAR, list_verbs, parse_command, verb_doc_md
from app.services.workflow_shell_runtime import (
    EXECUTE_VERBS,
    GOVERN_VERBS,
    INSPECT_RUNTIMES,
    LEARN_VERBS,
    MUTATING_VERBS,
    build_mutation_patch,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

from models.agent import Agent
from models.pipeline_healing import (
    PipelinePatchProposal,
    PipelinePatchStatus,
)
from models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workflow-shell", tags=["workflow-shell"])


class CommandRequest(BaseModel):
    text: str
    # Optional: ask the LLM to translate freeform NL → verb invocation
    nl: bool = False


@router.get("/grammar")
async def grammar(_: User = Depends(get_current_user)):
    """Returns the full verb registry — used by the UI for autocomplete + docs."""
    return success({
        "verbs": list_verbs(),
        "cheat_sheet": verb_doc_md(),
    })


def _can_mutate(user: User, agent: Agent) -> bool:
    return user.role == "admin" or str(agent.creator_id) == str(user.id)


async def _nl_translate(text: str) -> dict[str, Any]:
    """Use the workflow-shell model to translate a natural-language line
    into a verb invocation.  Cheap fast model; deterministic JSON output."""
    from app.core.platform_settings import get_setting
    try:
        from engine.llm_router import LLMRouter
    except ImportError:
        return {"ok": False, "error": "LLMRouter unavailable"}

    model = await get_setting("workflow_shell.model", default="claude-sonnet-4-5-20250929")
    grammar_doc = verb_doc_md()
    sys_prompt = (
        "You translate natural-language workflow commands into a single shell verb invocation.\n"
        "Reply with STRICT JSON: {\"command\": \"<verb> <args>\"} — nothing else.\n"
        "If the request is ambiguous or out of scope, return {\"command\": \"help\"}.\n"
        "Verbs and their argument shapes:\n\n" + grammar_doc
    )
    llm = LLMRouter()
    raw = await llm.complete(
        model=model,
        system=sys_prompt,
        messages=[{"role": "user", "content": text}],
        temperature=0.0,
        max_tokens=200,
        force_json=True,
    )
    try:
        s = (raw.get("text") or "").strip() if isinstance(raw, dict) else str(raw).strip()
        s = s.strip("` \n\t")
        if s.startswith("json\n"):
            s = s[5:]
        a = s.find("{"); b = s.rfind("}")
        return _json.loads(s[a:b + 1])
    except Exception as e:
        return {"ok": False, "error": f"NL translate failed: {e}"}


@router.post("/{pipeline_id}")
async def execute_command(
    pipeline_id: str,
    body: CommandRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pipeline = (await db.execute(
        select(Agent).where(Agent.id == uuid.UUID(pipeline_id), Agent.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not pipeline:
        return error("Pipeline not found", "not_found", status_code=404)

    text = body.text.strip()
    if body.nl and not GRAMMAR.get(text.split(" ", 1)[0].lower(), None):
        translated = await _nl_translate(text)
        cmd = translated.get("command") if isinstance(translated, dict) else None
        if cmd:
            text = cmd

    parsed = parse_command(text)
    if not parsed.get("ok"):
        return success({
            "kind": "error",
            "body": parsed.get("error"),
            "suggestion": parsed.get("suggestion"),
            "expected": parsed.get("expected"),
        })

    verb = parsed["verb"]
    args = parsed["args"]

    # ── INSPECT path ────────────────────────────────────────────────
    runtime = INSPECT_RUNTIMES.get(verb)
    if runtime is not None:
        try:
            result = await runtime(args=args, db=db, agent=pipeline, user=user)
            return success(result)
        except Exception as e:
            logger.exception("inspect verb '%s' failed", verb)
            return success({"kind": "error", "body": str(e)})

    # ── MUTATE path: produce a PipelinePatchProposal ──────────────
    if verb in MUTATING_VERBS:
        if not _can_mutate(user, pipeline):
            return error("Only admins or the pipeline owner can mutate", "forbidden", status_code=403)
        cfg = pipeline.model_config_ or {}
        if not cfg.get("pipeline_config"):
            return error("This agent has no pipeline DSL", "not_a_pipeline", status_code=400)
        dsl = {"pipeline_config": cfg["pipeline_config"]}
        try:
            proposal = build_mutation_patch(verb, args, dsl)
        except ValueError as e:
            return success({"kind": "error", "body": str(e)})

        rec = PipelinePatchProposal(
            tenant_id=user.tenant_id,
            pipeline_id=pipeline.id,
            title=proposal["title"],
            rationale=proposal["rationale"],
            confidence=proposal["confidence"],
            risk_level=proposal["risk_level"],
            dsl_before=proposal["dsl_before"],
            json_patch=proposal["json_patch"],
            dsl_after=proposal["dsl_after"],
            status=PipelinePatchStatus.PENDING,
        )
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
        return success({
            "kind": "patch_proposal",
            "id": str(rec.id),
            "title": rec.title,
            "rationale": rec.rationale,
            "risk_level": rec.risk_level,
            "json_patch": rec.json_patch,
            "dsl_before": rec.dsl_before,
            "dsl_after": rec.dsl_after,
            "next_step": "Open Healing tab and click Apply, or `approve <id>`",
        })

    # ── EXECUTE path: queue a run / replay / simulate / branch ───
    if verb in EXECUTE_VERBS:
        if verb == "run":
            return success({
                "kind": "execution",
                "queued": False,
                "body": "Run from the shell isn't wired to the executor yet — use the agent chat surface or POST /api/pipelines/{id}/execute directly.",
            })
        if verb == "replay":
            run_alias = args.get("run") or "last"
            return success({
                "kind": "execution",
                "queued": False,
                "body": f"Replay queued for `{run_alias}` — wire to /pipelines/{{id}}/replay in the next iteration.",
            })
        if verb == "simulate":
            return success({
                "kind": "execution",
                "queued": False,
                "body": f"Simulate against {args.get('source')} — dry-run executor lands in Phase 2.5.",
            })
        if verb == "branch":
            return success({
                "kind": "execution",
                "body": f"Branch '{args.get('name')}' from {args.get('from_run', 'last')} (coming soon — uses agent_revisions).",
            })
        if verb == "merge":
            return success({"kind": "execution", "body": f"Merge '{args.get('branch')}' (coming soon)."})
        if verb == "rollback":
            return success({"kind": "execution", "body": f"Rollback target '{args.get('target')}' — use the Healing tab Roll Back button for now."})

    # ── GOVERN path ────────────────────────────────────────────────
    if verb in GOVERN_VERBS:
        if verb == "approve":
            patch_id = args.get("patch_id")
            return success({
                "kind": "json",
                "title": f"approve {patch_id}",
                "body": f"Use POST /api/pipelines/{{pipeline}}/patches/{patch_id}/apply",
            })
        if verb == "reject":
            patch_id = args.get("patch_id")
            return success({
                "kind": "json",
                "title": f"reject {patch_id}",
                "body": f"Use POST /api/pipelines/{{pipeline}}/patches/{patch_id}/reject",
            })
        return success({
            "kind": "json",
            "title": verb,
            "body": {"verb": verb, "args": args, "note": "GOVERN verb registered; runtime persistence coming in Phase 2.5"},
        })

    # ── LEARN path ────────────────────────────────────────────────
    if verb in LEARN_VERBS:
        if verb == "diagnose":
            return success({
                "kind": "json",
                "title": "diagnose",
                "body": f"Use POST /api/pipelines/{pipeline_id}/diagnose (Healing tab → Diagnose latest failure).",
            })
        return success({
            "kind": "markdown",
            "body": f"`{verb}` produces a narrative answer; runtime lands in Phase 2.5 with the model under `workflow_shell.model`.",
        })

    return success({"kind": "error", "body": f"verb '{verb}' has no runtime"})
