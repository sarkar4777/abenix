"""Lessons: capture from every signal, incremental clustering, suggested test cases, views and retention."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

from engine import lessons as L  # noqa: E402
from models.agent import Agent  # noqa: E402
from models.evals import EvalCase, EvalSuite  # noqa: E402
from models.improvement import (  # noqa: E402
    Feedback,
    ImprovementProposal,
    Lesson,
    LessonCluster,
)
from models.user import User  # noqa: E402

logger = logging.getLogger(__name__)

SOURCE_LABEL = {
    "thumbs": "Thumbs down",
    "correction": "Correction",
    "autonomy_reject": "Rejected action",
    "autonomy_edit": "Edited action",
    "autonomy_alternative": "Reviewer did something else",
    "harm": "Harm flagged",
    "band_miss": "Outcome outside the prediction",
    "run_failed": "Failed run",
    "pipeline_failed": "Pipeline step failed",
    "drift": "Drift alert",
    "eval_failed": "Failing test case",
    "note": "Note",
    "sdk": "Reported by an app",
    "positive": "Good answer",
}
SOURCES = tuple(SOURCE_LABEL)
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}
OPEN_STATES = ("open", "proposing", "proposed")
CASE_ACTIONS = ("accept", "drop")
IMPROVEMENT_SUITE = "Improvement tests"
IMPROVEMENT_SUITE_TEXT = (
    "Test cases written from this agent's lessons. Suggested cases run only once a "
    "person accepts them. They gate changes only when the owner turns that on."
)
CLUSTER_LOCK_KEY = 0x4C534E43  # "LSNC"
RETAIN_LOCK_KEY = 0x4C534E52  # "LSNR"
CLUSTER_BATCH = 500
HARVEST_BATCH = 500
HARVEST_WINDOW_MINUTES = 30
TITLE_CALLS_PER_TICK = 10
TITLE_TIMEOUT = 15.0
JACCARD_MIN = 0.5
TREND_DAYS = 14
MAX_CASES_PER_CLUSTER = 5
MAX_POSITIVE_CASES = 10
MAX_BULK = 100
PAGE_MAX = 200
RETENTION_DEFAULT = 180
RETENTION_LIMITS = (7, 3650)
PURGE_BATCH = 1000
EXCERPT = 600

_STOP = frozenset(
    "the a an and or but if then than that this these those to of in on at for from by "
    "with without about into over under is are was were be been being it its it's as "
    "i me my we our you your he she they them their what which who whom when where why "
    "how do does did done can could should would will shall may might must not no yes "
    "please answer said say says tell told give gave get got make made use used also just "
    "only very more most some any all each every there here have has had".split()
)
_WORD = re.compile(r"[a-z][a-z0-9_'-]{2,}")
_NOISE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\b\d[\d.,:/-]*\b",
    re.I,
)


class LessonError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "BAD_REQUEST"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else (str(v) if v else None)


def _s(v: Any) -> str | None:
    return str(v) if v is not None else None


def _uuid(v: Any) -> uuid.UUID | None:
    if not v:
        return None
    try:
        return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
    except (ValueError, AttributeError, TypeError):
        return None


# grouping, pure


def tokens(*texts: Any, limit: int = 8) -> list[str]:
    """Content words in order of first use, numbers and ids dropped."""
    out: list[str] = []
    for t in texts:
        if not t:
            continue
        for w in _WORD.findall(_NOISE.sub(" ", str(t).lower())):
            w = w.strip("'-")
            if len(w) < 3 or w in _STOP or w in out:
                continue
            out.append(w)
            if len(out) >= limit:
                return out
    return out


def family(source: str, polarity: str = "negative") -> str:
    if polarity == "positive" or source == "positive":
        return "positive"
    if source in (
        "autonomy_reject",
        "autonomy_edit",
        "autonomy_alternative",
        "harm",
        "band_miss",
    ):
        return "action"
    if source == "run_failed":
        return "failure"
    if source == "pipeline_failed":
        return "pipeline"
    if source == "drift":
        return "drift"
    if source == "eval_failed":
        return "eval"
    return "answer"


def grouping(lesson: Any) -> dict[str, Any]:
    """What a lesson is grouped on: a base that must match and keywords compared loosely."""
    src = lesson.source
    fam = family(src, getattr(lesson, "polarity", "negative"))
    meta = getattr(lesson, "meta", None) or {}
    rule = ""
    keys: list[str] = []
    if fam == "positive":
        pass
    elif fam == "action":
        rule = str(meta.get("action_key") or "")
        keys = tokens(lesson.note, lesson.expected, limit=4)
    elif fam == "failure":
        keys = tokens(lesson.note, limit=4)
    elif fam == "pipeline":
        rule = str(meta.get("node_id") or "")
        keys = tokens(meta.get("error_class"), limit=2)
    elif fam == "drift":
        rule = str(meta.get("metric") or "")
    elif fam == "eval":
        rule = str(meta.get("case_name") or "")
    else:
        keys = tokens(lesson.input_text, lesson.note, lesson.expected)
    base = "|".join(
        [fam, str(lesson.failure_code or ""), str(lesson.tool_name or ""), rule]
    )
    return {"family": fam, "base": base, "keys": keys}


def signature(g: dict[str, Any]) -> str:
    raw = g["base"] + "|" + " ".join(sorted(g["keys"]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def jaccard(a: list[str] | set[str], b: list[str] | set[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def best_match(
    g: dict[str, Any], clusters: list[Any], minimum: float = JACCARD_MIN
) -> Any:
    """The most similar cluster with the same base, or None."""
    best, best_score = None, 0.0
    for c in clusters:
        m = c.meta or {}
        if m.get("base") != g["base"]:
            continue
        score = jaccard(g["keys"], m.get("keys") or [])
        if score >= minimum and score > best_score:
            best, best_score = c, score
    return best


def trend_add(trend: list[dict[str, Any]] | None, day: str) -> list[dict[str, Any]]:
    """Daily counts for the last TREND_DAYS days, oldest first."""
    rows = {r["day"]: int(r["count"]) for r in (trend or []) if r.get("day")}
    rows[day] = rows.get(day, 0) + 1
    cutoff = (
        (datetime.fromisoformat(max(rows)) - timedelta(days=TREND_DAYS - 1))
        .date()
        .isoformat()
    )
    return [{"day": d, "count": n} for d, n in sorted(rows.items()) if d >= cutoff]


def trend_series(
    trend: list[dict[str, Any]] | None, today: datetime | None = None
) -> list[int]:
    """TREND_DAYS counts ending today, zeros where nothing came in."""
    today = (today or _now()).date()
    rows = {r.get("day"): int(r.get("count") or 0) for r in (trend or [])}
    return [
        rows.get((today - timedelta(days=i)).isoformat(), 0)
        for i in range(TREND_DAYS - 1, -1, -1)
    ]


def severity_for(meta: dict[str, Any], negative: int) -> str:
    src = meta.get("sources") or {}
    if src.get("harm") or negative >= 10:
        return "high"
    strong = ("correction", "autonomy_reject", "autonomy_edit", "autonomy_alternative")
    if negative >= 3 or any(src.get(s) for s in strong) or src.get("band_miss"):
        return "medium"
    return "low"


def fallback_title(lesson: Any) -> str:
    fam = family(lesson.source, lesson.polarity)
    meta = lesson.meta or {}
    if fam == "positive":
        return "Answers people liked"
    if fam == "failure":
        code = (lesson.failure_code or "an error").replace("_", " ").lower()
        return f"Runs fail with {code}"
    if fam == "pipeline":
        return f"Pipeline step {meta.get('node_id') or 'unknown'} fails"
    if fam == "drift":
        return f"{str(meta.get('metric') or 'A measure').replace('_', ' ').capitalize()} drifts from normal"
    if fam == "eval":
        return f"Test case \"{meta.get('case_name') or 'unnamed'}\" fails"
    if fam == "action":
        what = meta.get("action_label") or lesson.tool_name or "an action"
        return f"{SOURCE_LABEL.get(lesson.source, 'Lesson')} on {what}"
    words = tokens(lesson.input_text, limit=6)
    about = " ".join(words) if words else "its answers"
    return f"Wrong answers about {about}"[:200]


def _clip(t: Any, n: int) -> str:
    s = "" if t is None else str(t)
    return s if len(s) <= n else s[: n - 1] + "…"


def case_for(lesson: Any) -> dict[str, Any] | None:
    """A suggested test case from a lesson, or None when there is nothing to replay."""
    inp = (lesson.input_text or "").strip()
    if not inp or lesson.source in ("drift", "eval_failed"):
        return None
    label = SOURCE_LABEL.get(lesson.source, "Lesson")
    name = f"{label}: {_clip(' '.join(inp.split()), 70)}"
    reference = None
    confirm = False
    if lesson.polarity == "positive":
        reference = lesson.output_text or None
        rubric = (
            "A person approved an earlier answer to this input. Pass only if the new "
            "answer is at least as correct and helpful as this one:\n"
            + _clip(lesson.output_text, 3000)
        )
    elif lesson.expected:
        reference = lesson.expected
        rubric = (
            "A person said the answer to this input should be:\n"
            + _clip(lesson.expected, 3000)
            + "\nPass only if the answer agrees with that."
        )
        if lesson.note:
            rubric += "\nTheir note: " + _clip(lesson.note, 800)
    elif lesson.note:
        confirm = True
        rubric = (
            "A person flagged an earlier answer to this input as wrong because: "
            + _clip(lesson.note, 1500)
            + "\nPass only if the answer avoids that problem."
        )
    elif lesson.source == "run_failed":
        confirm = True
        rubric = (
            "An earlier run on this input failed"
            + (f" with {lesson.failure_code}" if lesson.failure_code else "")
            + ". Pass only if the agent gives a complete, useful answer."
        )
    else:
        confirm = True
        rubric = (
            "A person marked an earlier answer to this input as unhelpful. The earlier "
            "answer was:\n"
            + _clip(lesson.output_text, 1500)
            + "\nPass only if the new answer is clearly more helpful and correct."
        )
    tags = ["improvement", lesson.source]
    if confirm:
        tags.append("needs_confirmation")
    return {
        "name": name[:255],
        "input_message": inp,
        "assertions": [{"type": "judge", "rubric": rubric, "min_score": 0.7}],
        "reference_output": reference,
        "tags": tags,
    }


def wants_cases(cluster: Any) -> bool:
    """Two or more lessons, or one harm, correction or alternative, earn test cases."""
    if (cluster.meta or {}).get("family") == "positive":
        return True
    src = (cluster.meta or {}).get("sources") or {}
    return int(cluster.negative_count or 0) >= 2 or any(
        src.get(s) for s in ("harm", "correction", "autonomy_alternative")
    )


# capture

_dlp: dict[str, tuple[float, dict[str, Any] | None]] = {}
_DLP_TTL = 60.0


async def tenant_dlp(db: AsyncSession, tenant_id: Any) -> dict[str, Any] | None:
    key = str(tenant_id)
    hit = _dlp.get(key)
    if hit and time.monotonic() - hit[0] < _DLP_TTL:
        return hit[1]
    raw = (
        await db.execute(
            text("SELECT settings->'dlp' FROM tenants WHERE id = :t"), {"t": key}
        )
    ).scalar()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    out = raw if isinstance(raw, dict) else None
    _dlp[key] = (time.monotonic(), out)
    return out


def _count(source: str) -> None:
    try:
        from app.core import telemetry

        telemetry.improvement_lessons_captured_total.labels(source=source).inc()
    except Exception:  # noqa: BLE001
        pass


_INSERT = text(
    "INSERT INTO lessons (id, tenant_id, agent_id, agent_config_hash, execution_id, source, "
    "polarity, input_text, output_text, expected, note, failure_code, tool_name, capture_key, "
    "by_user, meta, created_at) VALUES (:id, :tenant_id, :agent_id, :agent_config_hash, "
    ":execution_id, :source, :polarity, :input_text, :output_text, :expected, :note, "
    ":failure_code, :tool_name, :capture_key, :by_user, CAST(:meta AS jsonb), now()) "
    "ON CONFLICT (source, capture_key) DO NOTHING RETURNING id"
)


async def capture(db: AsyncSession, **fields: Any) -> uuid.UUID | None:
    """Insert one lesson inside a savepoint of the caller's transaction. Never raises."""
    if fields.get("source") not in SOURCES:
        return None
    if not fields.get("tenant_id") or not fields.get("agent_id"):
        return None
    nested = getattr(db, "begin_nested", None)
    if nested is None:
        return None
    try:
        async with nested():
            dlp = await tenant_dlp(db, fields["tenant_id"])
            r = L.row(**fields, dlp=dlp)
            params = {
                k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in r.items()
            }
            params["meta"] = json.dumps(r["meta"], default=str)
            for k in ("tenant_id", "agent_id", "execution_id", "by_user"):
                params[k] = _s(_uuid(r[k]))
            new_id = (await db.execute(_INSERT, params)).scalar()
            if new_id is not None:
                _count(r["source"])
                from app.services import events

                await events.emit(
                    db,
                    fields["tenant_id"],
                    "lesson.captured",
                    {
                        "lesson_id": str(new_id),
                        "agent_id": str(fields["agent_id"]),
                        "source": r["source"],
                        "polarity": r["polarity"],
                        "execution_id": _s(r["execution_id"]),
                    },
                )
            return _uuid(new_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("lesson capture skipped (%s): %s", fields.get("source"), exc)
        return None


async def capture_action(
    db: AsyncSession,
    action: Any,
    source: str,
    *,
    expected: Any = None,
    note: Any = None,
    by: Any = None,
    key_suffix: str = "",
) -> uuid.UUID | None:
    """An autonomy signal on an action becomes a lesson. Never raises."""
    if action is None or not getattr(action, "agent_id", None):
        return None
    try:
        inp = action.intent or ""
        if action.execution_id and getattr(db, "begin_nested", None) is not None:
            async with db.begin_nested():
                inp = (
                    await db.execute(
                        text("SELECT input_message FROM executions WHERE id = :e"),
                        {"e": str(action.execution_id)},
                    )
                ).scalar() or inp
        args = json.dumps(action.arguments or {}, default=str)
        return await capture(
            db,
            tenant_id=action.tenant_id,
            agent_id=action.agent_id,
            source=source,
            execution_id=action.execution_id,
            input_text=inp,
            output_text=f"{action.tool_name}({args})",
            expected=expected,
            note=note,
            tool_name=action.tool_name,
            agent_config_hash=getattr(action, "agent_config_hash", None),
            by_user=by,
            key=L.capture_key("action", action.id, key_suffix),
            meta={"action_id": str(action.id), "action_key": action.tool_name},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("action lesson skipped: %s", exc)
        return None


# harvest: signals already stored elsewhere become lessons, behind the run

_HARVEST_RUNS = text(
    "SELECT e.id, e.tenant_id, e.agent_id, e.input_message, e.output_message, "
    "e.error_message, e.failure_code, e.provenance->>'config_hash' AS config_hash "
    "FROM executions e WHERE e.status = 'FAILED' AND e.completed_at >= :since "
    "AND e.agent_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM lessons l "
    "WHERE l.source = 'run_failed' AND l.capture_key = e.id::text) "
    "ORDER BY e.completed_at LIMIT :n"
)
_HARVEST_DRIFT = text(
    "SELECT d.id, d.tenant_id, d.agent_id, d.execution_id, d.metric, d.severity, "
    "d.baseline_value, d.current_value, d.deviation_pct FROM drift_alerts d "
    "WHERE d.created_at >= :since AND NOT EXISTS (SELECT 1 FROM lessons l "
    "WHERE l.source = 'drift' AND l.capture_key = d.id::text) ORDER BY d.created_at LIMIT :n"
)
_HARVEST_PIPELINE = text(
    "SELECT p.id, p.tenant_id, p.pipeline_id, p.execution_id, p.node_id, p.node_target, "
    "p.error_class, p.error_message, e.input_message FROM pipeline_run_diffs p "
    "LEFT JOIN executions e ON e.id = p.execution_id WHERE p.created_at >= :since "
    "AND NOT EXISTS (SELECT 1 FROM lessons l WHERE l.source = 'pipeline_failed' "
    "AND l.capture_key = p.id::text) ORDER BY p.created_at LIMIT :n"
)
_HARVEST_EVALS = text(
    "SELECT r.id, r.tenant_id, run.agent_id, r.case_name, r.output_excerpt, r.error, "
    "r.assertion_results, c.input_message, c.reference_output, run.config_hash "
    "FROM eval_results r JOIN eval_runs run ON run.id = r.run_id "
    "LEFT JOIN eval_cases c ON c.id = r.case_id "
    "WHERE r.created_at >= :since AND r.passed IS FALSE AND run.triggered_by = 'schedule' "
    "AND run.agent_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM lessons l "
    "WHERE l.source = 'eval_failed' AND l.capture_key = r.id::text) "
    "ORDER BY r.created_at LIMIT :n"
)


def _failed_reasons(results: Any) -> str:
    out = []
    for a in results or []:
        if isinstance(a, dict) and not a.get("passed"):
            out.append(str(a.get("detail") or a.get("label") or a.get("type") or ""))
    return "; ".join(x for x in out if x)[:1500]


async def harvest(db: AsyncSession, *, minutes: int = HARVEST_WINDOW_MINUTES) -> dict:
    """Failed runs, drift alerts, pipeline failures and scheduled eval failures since the window."""
    since = _now() - timedelta(minutes=minutes)
    out = {"run_failed": 0, "drift": 0, "pipeline_failed": 0, "eval_failed": 0}
    p = {"since": since, "n": HARVEST_BATCH}

    async def rows(sql: Any) -> list[Any]:
        try:
            async with db.begin_nested():
                return list((await db.execute(sql, p)).mappings().all())
        except Exception as exc:  # noqa: BLE001
            logger.warning("lesson harvest query skipped: %s", exc)
            return []

    for r in await rows(_HARVEST_RUNS):
        ok = await capture(
            db,
            tenant_id=r["tenant_id"],
            agent_id=r["agent_id"],
            source="run_failed",
            execution_id=r["id"],
            input_text=r["input_message"] or "",
            output_text=r["output_message"] or r["error_message"] or "",
            note=r["error_message"],
            failure_code=r["failure_code"],
            agent_config_hash=r["config_hash"],
            key=str(r["id"]),
        )
        out["run_failed"] += int(ok is not None)
    for r in await rows(_HARVEST_DRIFT):
        metric = str(r["metric"] or "")
        ok = await capture(
            db,
            tenant_id=r["tenant_id"],
            agent_id=r["agent_id"],
            source="drift",
            execution_id=r["execution_id"],
            note=(
                f"{metric.replace('_', ' ')} moved {float(r['deviation_pct'] or 0):.0f}% "
                f"from its usual {float(r['baseline_value'] or 0):.4g} "
                f"to {float(r['current_value'] or 0):.4g}"
            ),
            key=str(r["id"]),
            meta={"metric": metric, "drift_severity": r["severity"]},
        )
        out["drift"] += int(ok is not None)
    for r in await rows(_HARVEST_PIPELINE):
        ok = await capture(
            db,
            tenant_id=r["tenant_id"],
            agent_id=r["pipeline_id"],
            source="pipeline_failed",
            execution_id=r["execution_id"],
            input_text=r["input_message"] or "",
            output_text=r["error_message"] or "",
            note=f"{r['error_class']} at {r['node_id']}",
            tool_name=r["node_target"],
            key=str(r["id"]),
            meta={
                "node_id": r["node_id"],
                "error_class": r["error_class"],
                "diff_id": str(r["id"]),
            },
        )
        out["pipeline_failed"] += int(ok is not None)
    for r in await rows(_HARVEST_EVALS):
        ok = await capture(
            db,
            tenant_id=r["tenant_id"],
            agent_id=r["agent_id"],
            source="eval_failed",
            input_text=r["input_message"] or "",
            output_text=r["output_excerpt"] or r["error"] or "",
            expected=r["reference_output"],
            note=_failed_reasons(r["assertion_results"]) or r["error"],
            agent_config_hash=r["config_hash"],
            key=str(r["id"]),
            meta={"case_name": r["case_name"]},
        )
        out["eval_failed"] += int(ok is not None)
    await db.commit()
    return out


# visibility


async def _caps(db: AsyncSession, user: Any) -> frozenset[str]:
    from app.core import capabilities as caps

    try:
        return await caps.capabilities_for(db, user)
    except Exception:  # noqa: BLE001
        return frozenset()


def _holds(granted: frozenset[str], cap: str) -> bool:
    from app.core.capabilities import holds

    return holds(granted, cap)


async def visible_agents(db: AsyncSession, user: Any) -> set[uuid.UUID] | None:
    """None means every agent in the tenant. Owners see their own and shared ones."""
    from app.core.permissions import (
        accessible_resource_ids,
        is_admin,
        sees_other_users_resources,
    )

    granted = await _caps(db, user)
    if is_admin(user) or (
        sees_other_users_resources(user) and _holds(granted, "improvements.view")
    ):
        return None
    own = {
        r[0]
        for r in (
            await db.execute(
                select(Agent.id).where(
                    Agent.tenant_id == user.tenant_id, Agent.creator_id == user.id
                )
            )
        ).all()
    }
    if _holds(granted, "improvements.view"):
        own |= set(await accessible_resource_ids(db, user, kind="agent"))
    return own


async def _agent(db: AsyncSession, user: Any, agent_id: Any) -> Agent:
    aid = _uuid(agent_id)
    agent = (
        (
            await db.execute(
                select(Agent).where(Agent.id == aid, Agent.tenant_id == user.tenant_id)
            )
        ).scalar_one_or_none()
        if aid
        else None
    )
    if agent is None:
        raise LessonError("This agent was not found.", 404, "NOT_FOUND")
    scope = await visible_agents(db, user)
    if scope is not None and agent.id not in scope:
        raise LessonError(
            "Only the agent's owner, people it is shared with and admins see its lessons.",
            403,
            "FORBIDDEN",
        )
    return agent


async def can_manage(db: AsyncSession, user: Any, agent: Any) -> bool:
    if getattr(agent, "creator_id", None) == user.id:
        return True
    return _holds(await _caps(db, user), "improvements.propose")


# feedback and notes


async def _execution_target(db: AsyncSession, user: Any, execution_id: Any) -> dict:
    row = (
        (
            await db.execute(
                text(
                    "SELECT id, tenant_id, agent_id, user_id, input_message, output_message, "
                    "provenance->>'config_hash' AS config_hash FROM executions WHERE id = :e"
                ),
                {"e": str(execution_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None or str(row["tenant_id"]) != str(user.tenant_id):
        raise LessonError("This run was not found.", 404, "NOT_FOUND")
    if row["user_id"] != user.id and not await _sees_agent(db, user, row["agent_id"]):
        raise LessonError("This run was not found.", 404, "NOT_FOUND")
    return dict(row)


async def _sees_agent(db: AsyncSession, user: Any, agent_id: Any) -> bool:
    """Someone else's run is open to the agent's owner, its shares and admins."""
    scope = await visible_agents(db, user)
    return scope is None or _uuid(agent_id) in scope


async def _message_target(
    db: AsyncSession, user: Any, message_id: Any, conversation_id: Any
) -> dict:
    row = (
        (
            await db.execute(
                text(
                    "SELECT m.id, m.content, m.created_at, m.role, c.id AS conversation_id, "
                    "c.agent_id, c.user_id, c.tenant_id FROM messages m "
                    "JOIN conversations c ON c.id = m.conversation_id WHERE m.id = :m"
                ),
                {"m": str(message_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None or str(row["tenant_id"]) != str(user.tenant_id):
        raise LessonError("This message was not found.", 404, "NOT_FOUND")
    if row["user_id"] != user.id and not await _sees_agent(db, user, row["agent_id"]):
        raise LessonError("This message was not found.", 404, "NOT_FOUND")
    if conversation_id and str(row["conversation_id"]) != str(conversation_id):
        raise LessonError("This message is not in that conversation.", 400, "MISMATCH")
    prev = (
        await db.execute(
            text(
                "SELECT content FROM messages WHERE conversation_id = :c AND role = 'user' "
                "AND created_at <= :t ORDER BY created_at DESC LIMIT 1"
            ),
            {"c": str(row["conversation_id"]), "t": row["created_at"]},
        )
    ).scalar()
    return {**dict(row), "input_message": prev or "", "output_message": row["content"]}


FEEDBACK_SOURCES = ("thumbs", "correction", "positive")


def _unapply(cluster: Any, lesson: Any) -> None:
    """The reverse of _apply, for a lesson taken back out of its group."""
    meta = dict(cluster.meta or {})
    src = dict(meta.get("sources") or {})
    left = int(src.get(lesson.source) or 0) - 1
    if left > 0:
        src[lesson.source] = left
    else:
        src.pop(lesson.source, None)
    meta["sources"] = src
    cluster.meta = meta
    cluster.count = max(0, int(cluster.count or 0) - 1)
    if lesson.polarity == "negative":
        cluster.negative_count = max(0, int(cluster.negative_count or 0) - 1)
    day = (lesson.created_at or _now()).date().isoformat()
    trend = []
    for r in cluster.trend or []:
        n = int(r.get("count") or 0) - (1 if r.get("day") == day else 0)
        if n > 0:
            trend.append({**r, "count": n})
    cluster.trend = trend
    cluster.severity = severity_for(meta, int(cluster.negative_count or 0))


async def _feedback_lessons(db: AsyncSession, tenant_id: Any, key: str) -> list[Any]:
    # waits for a grouping pass holding these rows, then reads where it put them
    return list(
        (
            await db.execute(
                select(Lesson)
                .where(
                    Lesson.tenant_id == tenant_id,
                    Lesson.capture_key == key,
                    Lesson.source.in_(FEEDBACK_SOURCES),
                )
                .order_by(Lesson.created_at)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )


async def revise_feedback_lesson(
    db: AsyncSession,
    agent: Any,
    key: str,
    source: str,
    expected: str | None,
) -> uuid.UUID | None:
    """A thumbs down that gains a correction keeps its lesson and its place in the group."""
    rows = await _feedback_lessons(db, agent.tenant_id, key)
    if not rows or L.polarity_for(source) != rows[0].polarity:
        return None
    x, extra = rows[0], rows[1:]
    if extra:
        await forget_feedback_lessons_rows(db, extra)
    old = x.source
    x.source = source
    x.expected = (
        L.row(
            tenant_id=agent.tenant_id,
            agent_id=agent.id,
            source=source,
            expected=expected,
            dlp=await tenant_dlp(db, agent.tenant_id),
        )["expected"]
        if expected
        else None
    )
    c = await db.get(LessonCluster, x.cluster_id) if x.cluster_id else None
    if c is not None and old != source:
        meta = dict(c.meta or {})
        src = dict(meta.get("sources") or {})
        if int(src.get(old) or 0) > 1:
            src[old] = int(src[old]) - 1
        else:
            src.pop(old, None)
        src[source] = int(src.get(source) or 0) + 1
        meta["sources"] = src
        c.meta = meta
        c.severity = severity_for(meta, int(c.negative_count or 0))
    case = await db.get(EvalCase, x.case_id) if x.case_id else None
    if case is not None and case.state == "suggested":
        spec = case_for(x)
        if spec is None:
            await db.delete(case)
            x.case_id = None
        else:
            case.name = spec["name"]
            case.assertions = spec["assertions"]
            case.reference_output = spec["reference_output"]
            case.tags = spec["tags"]
    await db.flush()
    if c is not None:
        await _suggest(db, c, agent)
    return x.id


async def forget_feedback_lessons(db: AsyncSession, tenant_id: Any, key: str) -> int:
    """Take a person's earlier feedback lesson out of its group and its suggested case, then drop it."""
    return await forget_feedback_lessons_rows(
        db, await _feedback_lessons(db, tenant_id, key)
    )


async def forget_feedback_lessons_rows(db: AsyncSession, rows: list[Any]) -> int:
    for x in rows:
        c = await db.get(LessonCluster, x.cluster_id) if x.cluster_id else None
        case = await db.get(EvalCase, x.case_id) if x.case_id else None
        dropped = case is not None and case.state == "suggested"
        if dropped:
            await db.delete(case)
        if c is not None:
            _unapply(c, x)
            if dropped and int((c.meta or {}).get("cases") or 0) > 0:
                c.meta = {**c.meta, "cases": int(c.meta["cases"]) - 1}
            if c.count <= 0 and c.state == "open":
                await db.delete(c)
        await db.delete(x)
    if rows:
        await db.flush()
    return len(rows)


def _feedback_source(rating: int, correction: str | None) -> str:
    if rating > 0:
        return "positive"
    return "correction" if correction else "thumbs"


async def give_feedback(
    db: AsyncSession, user: Any, body: dict[str, Any]
) -> dict[str, Any]:
    rating = body.get("rating")
    if rating not in (1, -1):
        raise LessonError("rating must be 1 or -1.", 400, "BAD_RATING")
    correction = (body.get("correction") or "").strip() or None
    if correction and rating > 0:
        correction = None
    exec_id = _uuid(body.get("execution_id"))
    msg_id = _uuid(body.get("message_id"))
    conv_id = _uuid(body.get("conversation_id"))
    if body.get("execution_id") and exec_id is None:
        raise LessonError("execution_id is not a valid id.", 400, "BAD_ID")
    target: dict[str, Any] = {}
    if exec_id:
        target = await _execution_target(db, user, exec_id)
    elif msg_id:
        target = await _message_target(db, user, msg_id, conv_id)
        conv_id = target["conversation_id"]
    agent_id = _uuid(target.get("agent_id")) or _uuid(body.get("agent_id"))
    if agent_id is None:
        raise LessonError(
            "Say which answer this is about: a run, a chat message or an agent.",
            400,
            "NO_TARGET",
        )
    agent = (
        await db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if agent is None or (not target and not await _sees_agent(db, user, agent.id)):
        raise LessonError("This agent was not found.", 404, "NOT_FOUND")

    target_key = str(exec_id or msg_id or "")
    existing = None
    if target_key:
        q = select(Feedback).where(
            Feedback.tenant_id == user.tenant_id, Feedback.user_id == user.id
        )
        q = q.where(
            Feedback.execution_id == exec_id
            if exec_id
            else Feedback.message_id == msg_id
        )
        existing = (await db.execute(q.limit(1))).scalar_one_or_none()
    if existing is not None:
        fb = existing
        fb.rating = rating
        fb.correction = correction
    else:
        fb = Feedback(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            user_id=user.id,
            execution_id=exec_id,
            conversation_id=conv_id,
            message_id=msg_id,
            agent_id=agent_id,
            rating=rating,
            correction=correction,
        )
        db.add(fb)
    await db.flush()
    source = _feedback_source(rating, correction)
    key = L.capture_key("fb", target_key or fb.id, user.id)
    lesson_id = None
    if existing is not None:
        lesson_id = await revise_feedback_lesson(db, agent, key, source, correction)
        if lesson_id is None:
            # a changed mind replaces the lesson it left, even after it was grouped
            await forget_feedback_lessons(db, user.tenant_id, key)
    lesson_id = lesson_id or await capture(
        db,
        tenant_id=user.tenant_id,
        agent_id=agent_id,
        source=source,
        execution_id=exec_id,
        input_text=target.get("input_message") or "",
        output_text=target.get("output_message") or "",
        expected=correction,
        by_user=user.id,
        agent_config_hash=target.get("config_hash"),
        key=key,
        meta={
            "feedback_id": str(fb.id),
            "message_id": _s(msg_id),
            "conversation_id": _s(conv_id),
        },
    )
    await db.commit()
    scope = await visible_agents(db, user)
    return {
        "id": str(fb.id),
        "lesson_id": _s(lesson_id),
        "agent_id": str(agent_id),
        "rating": rating,
        "can_view_lessons": scope is None or agent_id in scope,
    }


async def add_note(db: AsyncSession, user: Any, body: dict[str, Any]) -> dict[str, Any]:
    note = (body.get("note") or "").strip()
    if not note:
        raise LessonError("Say what was wrong.", 400, "NOTE_REQUIRED")
    if len(note) > L.NOTE_CAP:
        raise LessonError(
            f"Keep the note under {L.NOTE_CAP} characters.", 400, "TOO_LONG"
        )
    source = body.get("source") or "note"
    if source not in ("note", "sdk"):
        raise LessonError("source must be note or sdk.", 400, "BAD_SOURCE")
    exec_id = _uuid(body.get("execution_id"))
    target: dict[str, Any] = {}
    if exec_id:
        target = await _execution_target(db, user, exec_id)
    agent_id = _uuid(target.get("agent_id")) or _uuid(body.get("agent_id"))
    if agent_id is None:
        raise LessonError("agent_id is required.", 400, "NO_AGENT")
    if target and str(target.get("agent_id")) != str(agent_id) and body.get("agent_id"):
        raise LessonError("That run belongs to another agent.", 400, "MISMATCH")
    agent = (
        await db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if agent is None or (not target and not await _sees_agent(db, user, agent.id)):
        raise LessonError("This agent was not found.", 404, "NOT_FOUND")
    expected = (body.get("expected") or "").strip() or None
    lesson_id = await capture(
        db,
        tenant_id=user.tenant_id,
        agent_id=agent_id,
        source=source,
        execution_id=exec_id,
        input_text=body.get("input") or target.get("input_message") or "",
        output_text=body.get("output") or target.get("output_message") or "",
        expected=expected,
        note=note,
        by_user=user.id,
        agent_config_hash=target.get("config_hash"),
        key=L.capture_key("note", uuid.uuid4()),
    )
    await db.commit()
    if lesson_id is None:
        raise LessonError(
            "The note could not be saved right now. Try again in a minute.",
            503,
            "NOT_SAVED",
        )
    return {"lesson_id": str(lesson_id), "agent_id": str(agent_id)}


# clustering


async def _title(lessons: list[Any], model: str) -> str | None:
    from engine.llm_router import LLMRouter

    examples = "\n".join(
        f"- {SOURCE_LABEL.get(x.source, x.source)}. Input: {_clip(x.input_text, 200)} "
        f"| Answer: {_clip(x.output_text, 200)} | Should be: {_clip(x.expected, 200)} "
        f"| Note: {_clip(x.note, 200)}"
        for x in lessons[:3]
    )
    resp = await LLMRouter().complete(
        messages=[{"role": "user", "content": examples}],
        system=(
            "These are things an AI agent got wrong. Write one plain sentence of at most "
            "12 words naming the shared mistake, like: Uses last month's price when asked "
            "for today's. Reply with the sentence only."
        ),
        model=model,
        temperature=0.0,
        max_tokens=60,
    )
    t = " ".join(str(resp.content or "").split()).strip("\"' .")
    return t[:200] if 3 <= len(t) else None


async def _default_model(db: AsyncSession) -> str | None:
    try:
        from app.services.autonomy import default_model

        return await default_model(db)
    except Exception:  # noqa: BLE001
        return None


async def improvement_suite(db: AsyncSession, agent: Any) -> EvalSuite:
    suite = (
        await db.execute(
            select(EvalSuite)
            .where(
                EvalSuite.tenant_id == agent.tenant_id,
                EvalSuite.agent_id == agent.id,
                EvalSuite.name == IMPROVEMENT_SUITE,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if suite is None:
        suite = EvalSuite(
            id=uuid.uuid4(),
            tenant_id=agent.tenant_id,
            agent_id=agent.id,
            name=IMPROVEMENT_SUITE,
            description=IMPROVEMENT_SUITE_TEXT,
            gating=False,
            pass_threshold=0.9,
            concurrency=4,
            rerun_on_model_change=False,
            created_by=agent.creator_id,
        )
        db.add(suite)
        await db.flush()
    return suite


async def _suggest(db: AsyncSession, cluster: Any, agent: Any) -> int:
    if not wants_cases(cluster):
        return 0
    meta = dict(cluster.meta or {})
    cap = (
        MAX_POSITIVE_CASES
        if meta.get("family") == "positive"
        else MAX_CASES_PER_CLUSTER
    )
    have = int(meta.get("cases") or 0)
    if have >= cap:
        return 0
    pending = (
        (
            await db.execute(
                select(Lesson)
                .where(Lesson.cluster_id == cluster.id, Lesson.case_id.is_(None))
                .order_by(Lesson.created_at.desc())
                .limit((cap - have) * 3)
            )
        )
        .scalars()
        .all()
    )
    made = 0
    suite = None
    for lesson in pending:
        spec = case_for(lesson)
        if spec is None:
            continue
        if suite is None:
            suite = await improvement_suite(db, agent)
        case = EvalCase(
            id=uuid.uuid4(),
            tenant_id=cluster.tenant_id,
            suite_id=suite.id,
            name=spec["name"],
            input_message=spec["input_message"],
            context={},
            assertions=spec["assertions"],
            weight=1.0,
            tags=spec["tags"],
            source_execution_id=lesson.execution_id,
            reference_output=spec["reference_output"],
            state="suggested",
            source_lesson_id=lesson.id,
        )
        db.add(case)
        lesson.case_id = case.id
        made += 1
        if have + made >= cap:
            break
    if made:
        meta["cases"] = have + made
        cluster.meta = meta
    return made


def _apply(cluster: Any, lesson: Any) -> None:
    meta = dict(cluster.meta or {})
    src = dict(meta.get("sources") or {})
    src[lesson.source] = int(src.get(lesson.source) or 0) + 1
    meta["sources"] = src
    cluster.meta = meta
    cluster.count = int(cluster.count or 0) + 1
    if lesson.polarity == "negative":
        cluster.negative_count = int(cluster.negative_count or 0) + 1
        if cluster.state == "fixed":
            cluster.state = "open"
    created = lesson.created_at or _now()
    cluster.trend = trend_add(cluster.trend, created.date().isoformat())
    if cluster.last_lesson_at is None or created > cluster.last_lesson_at:
        cluster.last_lesson_at = created
    cluster.severity = severity_for(meta, int(cluster.negative_count or 0))
    cluster.summary = summary_for(cluster)


def summary_for(cluster: Any) -> str:
    src = (cluster.meta or {}).get("sources") or {}
    parts = [
        f"{n} {SOURCE_LABEL.get(s, s).lower()}"
        for s, n in sorted(src.items(), key=lambda kv: -kv[1])
    ]
    return ", ".join(parts[:4])


async def cluster_tick(
    db: AsyncSession, *, tenant_id: Any = None, batch: int = CLUSTER_BATCH
) -> dict[str, int]:
    """Group lessons nobody has grouped yet. Old lessons are never read again."""
    q = select(Lesson).where(Lesson.cluster_id.is_(None))
    if tenant_id is not None:
        q = q.where(Lesson.tenant_id == tenant_id)
    # rows locked until the grouping commits, so a changed mind waits instead of racing it
    q = q.order_by(Lesson.created_at).limit(batch).with_for_update(skip_locked=True)
    new_lessons = (await db.execute(q)).scalars().all()
    out = {"lessons": 0, "clusters_opened": 0, "cases": 0, "titled": 0}
    if not new_lessons:
        return out
    by_agent: dict[tuple, list[Any]] = defaultdict(list)
    for x in new_lessons:
        by_agent[(x.tenant_id, x.agent_id)].append(x)
    agents = {
        a.id: a
        for a in (
            await db.execute(
                select(Agent).where(Agent.id.in_([k[1] for k in by_agent]))
            )
        )
        .scalars()
        .all()
    }
    opened: list[tuple[Any, list[Any]]] = []
    touched: dict[uuid.UUID, Any] = {}
    for (tid, aid), group in by_agent.items():
        if aid not in agents:
            # the agent is gone, its lessons have nothing left to improve
            for x in group:
                await db.delete(x)
            continue
        existing = (
            (
                await db.execute(
                    select(LessonCluster)
                    .where(
                        LessonCluster.tenant_id == tid, LessonCluster.agent_id == aid
                    )
                    .order_by(LessonCluster.last_lesson_at.desc().nulls_last())
                    .limit(1000)
                )
            )
            .scalars()
            .all()
        )
        by_sig = {c.signature: c for c in existing}
        pool = list(existing)
        fresh: dict[uuid.UUID, list[Any]] = {}
        for x in group:
            g = grouping(x)
            sig = signature(g)
            c = by_sig.get(sig) or best_match(g, pool)
            if c is None:
                c = LessonCluster(
                    id=uuid.uuid4(),
                    tenant_id=tid,
                    agent_id=aid,
                    title=fallback_title(x),
                    summary="",
                    signature=sig,
                    count=0,
                    negative_count=0,
                    severity="low",
                    trend=[],
                    state="open",
                    meta={"family": g["family"], "base": g["base"], "keys": g["keys"]},
                )
                db.add(c)
                # no relationship links the two tables, so the cluster row must exist first
                await db.flush()
                by_sig[sig] = c
                pool.append(c)
                fresh[c.id] = []
                opened.append((c, fresh[c.id]))
            _apply(c, x)
            x.cluster_id = c.id
            if c.id in fresh:
                fresh[c.id].append(x)
            touched[c.id] = c
            out["lessons"] += 1
    await db.flush()

    for c in touched.values():
        agent = agents.get(c.agent_id)
        if agent is not None:
            out["cases"] += await _suggest(db, c, agent)
    await db.commit()

    model = await _default_model(db) if opened else None
    calls = 0
    for c, members in opened:
        if c.meta.get("family") == "positive" or not model:
            continue
        if calls >= TITLE_CALLS_PER_TICK:
            break
        calls += 1
        try:
            t = await asyncio.wait_for(_title(members, model), TITLE_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            logger.debug("cluster title fell back: %s", exc)
            t = None
        if t:
            c.title = t
            out["titled"] += 1

    from app.services import events

    for c, _members in opened:
        if c.negative_count:
            out["clusters_opened"] += 1
            await events.emit(
                db,
                c.tenant_id,
                "cluster.opened",
                {
                    "cluster_id": str(c.id),
                    "agent_id": str(c.agent_id),
                    "title": c.title,
                    "count": c.count,
                    "severity": c.severity,
                },
            )
    await db.commit()
    return out


_soon: dict[str, float] = {}
SOON_SECONDS = 5.0


async def cluster_soon(tenant_id: Any) -> None:
    """Group a tenant's new lessons right after feedback, so the tab shows them at once."""
    key = str(tenant_id)
    if time.monotonic() - _soon.get(key, 0.0) < SOON_SECONDS:
        return
    _soon[key] = time.monotonic()
    try:
        from app.core.deps import async_session
        from app.core.scheduler import advisory_lock

        async with advisory_lock(CLUSTER_LOCK_KEY) as held:
            if not held:
                return
            async with async_session() as db:
                await cluster_tick(db, tenant_id=_uuid(tenant_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("lesson grouping after feedback skipped: %s", exc)


async def run_tick(db_factory: Any) -> dict[str, Any]:
    """The scheduled job: harvest stored signals, then group what is new."""
    async with db_factory() as db:
        h = await harvest(db)
    async with db_factory() as db:
        c = await cluster_tick(db)
    return {**h, **c}


# rows


def lesson_row(x: Any, names: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "id": str(x.id),
        "source": x.source,
        "source_label": SOURCE_LABEL.get(x.source, x.source),
        "polarity": x.polarity,
        "input_text": _clip(x.input_text, EXCERPT * 2),
        "output_text": _clip(x.output_text, EXCERPT * 2),
        "expected": x.expected,
        "note": x.note,
        "failure_code": x.failure_code,
        "tool_name": x.tool_name,
        "execution_id": _s(x.execution_id),
        "cluster_id": _s(x.cluster_id),
        "case_id": _s(x.case_id),
        "by_user_name": (names or {}).get(str(x.by_user)) if x.by_user else None,
        "created_at": _iso(x.created_at),
    }


def proposal_row(p: Any, agent: Any = None, cluster: Any = None) -> dict[str, Any]:
    from app.services.improvements import proposal_row as shaped

    return shaped(p, agent, cluster)


async def _names(db: AsyncSession, ids: set[Any]) -> dict[str, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.full_name, User.email).where(User.id.in_(ids))
        )
    ).all()
    return {str(r[0]): (r[1] or r[2] or "") for r in rows}


async def _examples(db: AsyncSession, cluster_ids: list[Any]) -> dict[str, list[Any]]:
    if not cluster_ids:
        return {}
    ranked = (
        select(
            Lesson,
            func.row_number()
            .over(partition_by=Lesson.cluster_id, order_by=Lesson.created_at.desc())
            .label("rn"),
        )
        .where(Lesson.cluster_id.in_(cluster_ids))
        .subquery()
    )
    from sqlalchemy.orm import aliased

    alias = aliased(Lesson, ranked)
    rows = (await db.execute(select(alias).where(ranked.c.rn <= 3))).scalars().all()
    out: dict[str, list[Any]] = defaultdict(list)
    for x in rows:
        out[str(x.cluster_id)].append(x)
    for k in out:
        out[k].sort(key=lambda x: x.created_at or _now(), reverse=True)
    return out


async def _latest_proposals(db: AsyncSession, cluster_ids: list[Any]) -> dict[str, Any]:
    if not cluster_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(ImprovementProposal)
                .where(ImprovementProposal.cluster_id.in_(cluster_ids))
                .order_by(
                    ImprovementProposal.cluster_id,
                    ImprovementProposal.created_at.desc(),
                )
                .distinct(ImprovementProposal.cluster_id)
            )
        )
        .scalars()
        .all()
    )
    return {str(p.cluster_id): p for p in rows}


async def cluster_rows(
    db: AsyncSession, clusters: list[Any], agents: dict[Any, Any]
) -> list[dict[str, Any]]:
    ids = [c.id for c in clusters]
    examples = await _examples(db, ids)
    proposals = await _latest_proposals(db, ids)
    names = await _names(
        db, {x.by_user for xs in examples.values() for x in xs if x.by_user}
    )
    out = []
    for c in clusters:
        agent = agents.get(c.agent_id)
        p = proposals.get(str(c.id))
        out.append(
            {
                "id": str(c.id),
                "agent": {"id": str(c.agent_id), "name": getattr(agent, "name", "")},
                "title": c.title,
                "summary": c.summary,
                "count": int(c.count or 0),
                "negative_count": int(c.negative_count or 0),
                "severity": c.severity,
                "trend": trend_series(c.trend),
                "state": c.state,
                "last_lesson_at": _iso(c.last_lesson_at),
                "examples": [lesson_row(x, names) for x in examples.get(str(c.id), [])],
                "proposal": proposal_row(p, agent, c) if p is not None else None,
            }
        )
    return out


async def case_rows(db: AsyncSession, cases: list[Any]) -> list[dict[str, Any]]:
    lesson_ids = [c.source_lesson_id for c in cases if c.source_lesson_id]
    titles: dict[str, str] = {}
    if lesson_ids:
        rows = (
            await db.execute(
                select(Lesson.id, LessonCluster.title)
                .join(LessonCluster, LessonCluster.id == Lesson.cluster_id)
                .where(Lesson.id.in_(lesson_ids))
            )
        ).all()
        titles = {str(r[0]): r[1] for r in rows}
    return [
        {
            "id": str(c.id),
            "suite_id": str(c.suite_id),
            "name": c.name,
            "input_message": c.input_message or "",
            "assertions": c.assertions or [],
            "reference_output": c.reference_output,
            "tags": c.tags or [],
            "state": c.state,
            "source_lesson_id": _s(c.source_lesson_id),
            "lesson_title": titles.get(str(c.source_lesson_id)),
        }
        for c in cases
    ]


def _severity_sort(c: Any) -> tuple:
    return (
        -SEVERITY_RANK.get(c.severity, 0),
        -int(c.negative_count or 0),
        -(c.last_lesson_at.timestamp() if c.last_lesson_at else 0),
    )


# views


async def overview(
    db: AsyncSession, user: Any, *, q: str | None = None, limit: int = 100
) -> dict[str, Any]:
    tid = user.tenant_id
    scope = await visible_agents(db, user)

    def scoped(stmt: Any, col: Any) -> Any:
        if scope is None:
            return stmt
        return stmt.where(col.in_(list(scope) or [uuid.UUID(int=0)]))

    open_clusters = (
        (
            await db.execute(
                scoped(
                    select(LessonCluster).where(
                        LessonCluster.tenant_id == tid,
                        LessonCluster.state.in_(OPEN_STATES),
                        LessonCluster.negative_count > 0,
                    ),
                    LessonCluster.agent_id,
                ).limit(5000)
            )
        )
        .scalars()
        .all()
    )
    unclustered = int(
        (
            await db.execute(
                scoped(
                    select(func.count())
                    .select_from(Lesson)
                    .where(
                        Lesson.tenant_id == tid,
                        Lesson.cluster_id.is_(None),
                        Lesson.polarity == "negative",
                    ),
                    Lesson.agent_id,
                )
            )
        ).scalar()
        or 0
    )
    since = _now() - timedelta(days=30)
    prop_counts = dict(
        (
            await db.execute(
                scoped(
                    select(ImprovementProposal.state, func.count())
                    .where(
                        ImprovementProposal.tenant_id == tid,
                        or_(
                            ImprovementProposal.state.in_(
                                ["awaiting_approval", "released"]
                            ),
                            and_(
                                ImprovementProposal.state == "rolled_back",
                                ImprovementProposal.updated_at >= since,
                            ),
                        ),
                    )
                    .group_by(ImprovementProposal.state),
                    ImprovementProposal.agent_id,
                )
            )
        ).all()
    )
    per_agent: dict[Any, list[Any]] = defaultdict(list)
    for c in open_clusters:
        per_agent[c.agent_id].append(c)
    agents = {
        a.id: a
        for a in (
            await db.execute(select(Agent).where(Agent.id.in_(list(per_agent) or [])))
        )
        .scalars()
        .all()
    }
    rows = []
    needle = (q or "").strip().lower()
    for aid, cs in per_agent.items():
        a = agents.get(aid)
        if a is None or (needle and needle not in (a.name or "").lower()):
            continue
        series = [0] * TREND_DAYS
        for c in cs:
            for i, n in enumerate(trend_series(c.trend)):
                series[i] += n
        worst = max(cs, key=lambda c: SEVERITY_RANK.get(c.severity, 0)).severity
        rows.append(
            {
                "agent": {"id": str(aid), "name": a.name},
                "open_clusters": len(cs),
                "open_lessons": sum(int(c.negative_count or 0) for c in cs),
                "worst_severity": worst,
                "trend": series,
                "last_lesson_at": _iso(
                    max(
                        (c.last_lesson_at for c in cs if c.last_lesson_at), default=None
                    )
                ),
            }
        )
    rows.sort(
        key=lambda r: (-SEVERITY_RANK.get(r["worst_severity"], 0), -r["open_lessons"])
    )
    return {
        "counts": {
            "open_lessons": sum(int(c.negative_count or 0) for c in open_clusters)
            + unclustered,
            "open_clusters": len(open_clusters),
            "proposals_waiting": int(prop_counts.get("awaiting_approval") or 0),
            "releases_watching": int(prop_counts.get("released") or 0),
            "rolled_back_30d": int(prop_counts.get("rolled_back") or 0),
        },
        "agents": rows[:limit],
        "total_agents": len(rows),
    }


async def agent_view(db: AsyncSession, user: Any, agent_id: Any) -> dict[str, Any]:
    agent = await _agent(db, user, agent_id)
    clusters = (
        (
            await db.execute(
                select(LessonCluster)
                .where(
                    LessonCluster.tenant_id == user.tenant_id,
                    LessonCluster.agent_id == agent.id,
                )
                .order_by(LessonCluster.last_lesson_at.desc().nulls_last())
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    open_ = sorted(
        [c for c in clusters if c.state in OPEN_STATES and c.negative_count],
        key=_severity_sort,
    )[:100]
    positive = sum(
        int(c.count or 0)
        for c in clusters
        if (c.meta or {}).get("family") == "positive"
    )
    closed = sum(
        1 for c in clusters if c.state in ("fixed", "dismissed") and c.negative_count
    )
    cases = (
        (
            await db.execute(
                select(EvalCase)
                .join(EvalSuite, EvalSuite.id == EvalCase.suite_id)
                .where(
                    EvalSuite.tenant_id == user.tenant_id,
                    EvalSuite.agent_id == agent.id,
                    EvalCase.state == "suggested",
                )
                .order_by(EvalCase.created_at.desc())
                .limit(PAGE_MAX)
            )
        )
        .scalars()
        .all()
    )
    props = (
        (
            await db.execute(
                select(ImprovementProposal)
                .where(
                    ImprovementProposal.tenant_id == user.tenant_id,
                    ImprovementProposal.agent_id == agent.id,
                )
                .order_by(ImprovementProposal.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    by_id = {c.id: c for c in clusters}
    release_states = ("released", "kept", "rolled_back")
    unclustered = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Lesson)
                .where(
                    Lesson.tenant_id == user.tenant_id,
                    Lesson.agent_id == agent.id,
                    Lesson.cluster_id.is_(None),
                )
            )
        ).scalar()
        or 0
    )
    return {
        "agent": {"id": str(agent.id), "name": agent.name},
        "can_manage": await can_manage(db, user, agent),
        "clusters": await cluster_rows(db, open_, {agent.id: agent}),
        "suggested_cases": await case_rows(db, cases),
        "proposals": [
            proposal_row(p, agent, by_id.get(p.cluster_id))
            for p in props
            if p.state not in release_states
        ],
        "releases": [
            proposal_row(p, agent, by_id.get(p.cluster_id))
            for p in props
            if p.state in release_states
        ],
        "counts": {
            "good_examples": positive,
            "closed_clusters": closed,
            "waiting_to_group": unclustered,
        },
        "gate": await gate_state(db, agent),
    }


async def _find_suite(db: AsyncSession, agent: Any) -> Any:
    return (
        await db.execute(
            select(EvalSuite)
            .where(
                EvalSuite.tenant_id == agent.tenant_id,
                EvalSuite.agent_id == agent.id,
                EvalSuite.name == IMPROVEMENT_SUITE,
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def gate_state(db: AsyncSession, agent: Any) -> dict[str, Any]:
    """Whether the improvement tests gate changes, how many there are and how many fail now."""
    from models.evals import EvalRun

    suite = await _find_suite(db, agent)
    if suite is None:
        return {
            "suite_id": None,
            "gating": False,
            "accepted": 0,
            "failing": None,
            "last_run_at": None,
        }
    accepted = int(
        (
            await db.execute(
                select(func.count())
                .select_from(EvalCase)
                .where(EvalCase.suite_id == suite.id, EvalCase.state == "accepted")
            )
        ).scalar()
        or 0
    )
    run = (
        await db.execute(
            select(EvalRun)
            .where(EvalRun.suite_id == suite.id, EvalRun.status == "completed")
            .order_by(EvalRun.completed_at.desc().nulls_last())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "suite_id": str(suite.id),
        "gating": bool(suite.gating),
        "accepted": accepted,
        "failing": (
            int(run.failed or 0) + int(run.errored or 0) if run is not None else None
        ),
        "last_run_at": _iso(run.completed_at) if run is not None else None,
    }


async def set_gate(
    db: AsyncSession, user: Any, agent_id: Any, gating: bool
) -> dict[str, Any]:
    """The owner's switch: require the improvement tests to pass before changes go live."""
    agent = await _agent(db, user, agent_id)
    if not await can_manage(db, user, agent):
        raise LessonError(
            'Only the agent\'s owner, or someone with the "Propose improvements" permission, can change this.',
            403,
            "FORBIDDEN",
        )
    suite = await _find_suite(db, agent)
    if suite is None:
        if not gating:
            return await gate_state(db, agent)
        raise LessonError(
            "There are no improvement tests yet. Accept a suggested case first.",
            409,
            "NO_TESTS",
        )
    suite.gating = bool(gating)
    await db.commit()
    return await gate_state(db, agent)


async def _cluster(db: AsyncSession, user: Any, cluster_id: Any) -> tuple[Any, Any]:
    cid = _uuid(cluster_id)
    c = (
        (
            await db.execute(
                select(LessonCluster).where(
                    LessonCluster.id == cid, LessonCluster.tenant_id == user.tenant_id
                )
            )
        ).scalar_one_or_none()
        if cid
        else None
    )
    if c is None:
        raise LessonError("This group of lessons was not found.", 404, "NOT_FOUND")
    agent = await _agent(db, user, c.agent_id)
    return c, agent


def _before(before: str | None) -> datetime | None:
    if not before:
        return None
    try:
        return datetime.fromisoformat(before.replace("Z", "+00:00"))
    except ValueError:
        raise LessonError(
            "before must be a time like 2026-01-01T00:00:00Z.", 400, "BAD_REQUEST"
        ) from None


async def cluster_detail(
    db: AsyncSession,
    user: Any,
    cluster_id: Any,
    *,
    before: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    c, agent = await _cluster(db, user, cluster_id)
    limit = max(1, min(int(limit), PAGE_MAX))
    q = select(Lesson).where(Lesson.cluster_id == c.id)
    b = _before(before)
    if b is not None:
        q = q.where(Lesson.created_at < b)
    rows = (
        (await db.execute(q.order_by(Lesson.created_at.desc()).limit(limit + 1)))
        .scalars()
        .all()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    names = await _names(db, {x.by_user for x in rows})
    row = (await cluster_rows(db, [c], {agent.id: agent}))[0]
    row["lessons"] = [lesson_row(x, names) for x in rows]
    row["next_before"] = _iso(rows[-1].created_at) if more and rows else None
    row["can_manage"] = await can_manage(db, user, agent)
    return row


async def dismiss_cluster(
    db: AsyncSession, user: Any, cluster_id: Any, reason: str
) -> dict[str, Any]:
    c, agent = await _cluster(db, user, cluster_id)
    if not await can_manage(db, user, agent):
        raise LessonError(
            "Only the agent's owner or someone who can propose improvements can dismiss this.",
            403,
            "FORBIDDEN",
        )
    reason = (reason or "").strip()
    if not reason:
        raise LessonError("Say why this does not need fixing.", 400, "REASON_REQUIRED")
    if c.state in ("proposing", "proposed"):
        raise LessonError(
            "A fix is being worked on for this. Reject or wait for the proposal first.",
            409,
            "IN_PROGRESS",
        )
    meta = dict(c.meta or {})
    meta["dismissed"] = {
        "by": str(user.id),
        "reason": reason[:1000],
        "at": _iso(_now()),
    }
    c.meta = meta
    c.state = "dismissed"
    await db.commit()
    return (await cluster_rows(db, [c], {agent.id: agent}))[0]


async def list_lessons(
    db: AsyncSession,
    user: Any,
    *,
    agent_id: str | None = None,
    source: str | None = None,
    before: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), PAGE_MAX))
    if source and source not in SOURCES:
        raise LessonError(
            f"source must be one of {', '.join(SOURCES)}.", 400, "BAD_SOURCE"
        )
    q = select(Lesson).where(Lesson.tenant_id == user.tenant_id)
    if agent_id:
        agent = await _agent(db, user, agent_id)
        q = q.where(Lesson.agent_id == agent.id)
    else:
        scope = await visible_agents(db, user)
        if scope is not None:
            q = q.where(Lesson.agent_id.in_(list(scope) or [uuid.UUID(int=0)]))
    if source:
        q = q.where(Lesson.source == source)
    b = _before(before)
    if b is not None:
        q = q.where(Lesson.created_at < b)
    rows = (
        (await db.execute(q.order_by(Lesson.created_at.desc()).limit(limit + 1)))
        .scalars()
        .all()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    names = await _names(db, {x.by_user for x in rows})
    return {
        "items": [lesson_row(x, names) for x in rows],
        "next_before": _iso(rows[-1].created_at) if more and rows else None,
    }


# suggested cases


async def _case(db: AsyncSession, user: Any, case_id: Any) -> tuple[Any, Any, Any]:
    cid = _uuid(case_id)
    row = (
        (
            await db.execute(
                select(EvalCase, EvalSuite)
                .join(EvalSuite, EvalSuite.id == EvalCase.suite_id)
                .where(EvalCase.id == cid, EvalCase.tenant_id == user.tenant_id)
            )
        ).first()
        if cid
        else None
    )
    if row is None:
        raise LessonError("This test case was not found.", 404, "NOT_FOUND")
    case, suite = row
    agent = await _agent(db, user, suite.agent_id)
    if not await can_manage(db, user, agent):
        raise LessonError(
            "Only the agent's owner or someone who can propose improvements can change its test cases.",
            403,
            "FORBIDDEN",
        )
    return case, suite, agent


def _set_state(case: Any, suite: Any, action: str) -> None:
    if case.state not in ("suggested", "dropped") and action == "drop":
        raise LessonError(
            "Accepted cases are changed on the agent's Evaluations page.",
            409,
            "NOT_SUGGESTED",
        )
    if action == "accept":
        # the suite only gates when the owner turns that on, these cases fail until the fix lands
        case.state = "accepted"
    else:
        case.state = "dropped"


async def case_action(
    db: AsyncSession, user: Any, case_id: Any, action: str
) -> dict[str, Any]:
    if action not in CASE_ACTIONS:
        raise LessonError("action must be accept or drop.", 400, "BAD_ACTION")
    case, suite, _agent_ = await _case(db, user, case_id)
    if case.state == "accepted" and action == "accept":
        return (await case_rows(db, [case]))[0]
    _set_state(case, suite, action)
    await db.commit()
    return (await case_rows(db, [case]))[0]


async def bulk_cases(
    db: AsyncSession, user: Any, ids: list[Any], action: str
) -> dict[str, Any]:
    if action not in CASE_ACTIONS:
        raise LessonError("action must be accept or drop.", 400, "BAD_ACTION")
    if not ids:
        raise LessonError("Pick at least one case.", 400, "EMPTY")
    if len(ids) > MAX_BULK:
        raise LessonError(f"Up to {MAX_BULK} cases at a time.", 400, "TOO_MANY")
    done, skipped = [], []
    for cid in dict.fromkeys(str(i) for i in ids):
        try:
            case, suite, _a = await _case(db, user, cid)
            if not (case.state == "accepted" and action == "accept"):
                _set_state(case, suite, action)
            done.append(case)
        except LessonError as e:
            skipped.append({"id": cid, "reason": e.message})
    await db.commit()
    return {"done": await case_rows(db, done), "skipped": skipped}


async def patch_case(
    db: AsyncSession, user: Any, case_id: Any, body: dict[str, Any]
) -> dict[str, Any]:
    from app.services import eval_assertions as EA

    case, _suite, _agent_ = await _case(db, user, case_id)
    if case.state != "suggested":
        raise LessonError(
            "Only suggested cases are edited here. Accepted ones are on the agent's Evaluations page.",
            409,
            "NOT_SUGGESTED",
        )
    if "name" in body and body["name"] is not None:
        name = str(body["name"]).strip()
        if not name:
            raise LessonError("Give the case a name.", 400, "NAME_REQUIRED")
        case.name = name[:255]
    if "input_message" in body and body["input_message"] is not None:
        inp = str(body["input_message"]).strip()
        if not inp:
            raise LessonError("The input cannot be empty.", 400, "INPUT_REQUIRED")
        case.input_message = inp
    if "reference_output" in body:
        ref = body["reference_output"]
        case.reference_output = (str(ref).strip() or None) if ref is not None else None
    if "assertions" in body and body["assertions"] is not None:
        a = body["assertions"]
        if not isinstance(a, list) or not a:
            raise LessonError("Keep at least one check.", 400, "ASSERTIONS_REQUIRED")
        problems = [p for item in a for p in EA.validate(item)]
        if problems:
            raise LessonError(" ".join(problems), 400, "BAD_ASSERTION")
        case.assertions = a
    await db.commit()
    return (await case_rows(db, [case]))[0]


# retention


def retention_days(settings: dict[str, Any] | None) -> int:
    raw = ((settings or {}).get("improvements") or {}).get("retention_days")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return RETENTION_DEFAULT
    lo, hi = RETENTION_LIMITS
    return max(lo, min(hi, n))


_DAYS = (
    "make_interval(days => LEAST(GREATEST(COALESCE((t2.settings->'improvements'->>"
    f"'retention_days')::int, {RETENTION_DEFAULT}), {RETENTION_LIMITS[0]}), {RETENTION_LIMITS[1]}))"
)
_PURGE_LESSONS = text(
    "DELETE FROM lessons l WHERE l.id IN (SELECT l2.id FROM lessons l2 "
    "JOIN tenants t2 ON t2.id = l2.tenant_id "
    f"WHERE l2.created_at < now() - {_DAYS} LIMIT :batch)"
)
_PURGE_FEEDBACK = text(
    "DELETE FROM feedback f WHERE f.id IN (SELECT f2.id FROM feedback f2 "
    "JOIN tenants t2 ON t2.id = f2.tenant_id "
    f"WHERE f2.created_at < now() - {_DAYS} LIMIT :batch)"
)
_PURGE_CLUSTERS = text(
    "DELETE FROM lesson_clusters c WHERE c.id IN (SELECT c2.id FROM lesson_clusters c2 "
    "JOIN tenants t2 ON t2.id = c2.tenant_id WHERE c2.state IN ('fixed', 'dismissed') "
    f"AND COALESCE(c2.last_lesson_at, c2.updated_at) < now() - {_DAYS} "
    "AND NOT EXISTS (SELECT 1 FROM improvement_proposals p WHERE p.cluster_id = c2.id "
    "AND p.state IN ('released', 'awaiting_approval', 'proving', 'drafting', 'approved')) "
    "LIMIT :batch)"
)


async def purge_retention(db: AsyncSession, batch: int = PURGE_BATCH) -> dict[str, int]:
    """Drop lessons, feedback and closed groups past each tenant's retention, in batches."""
    out = {"lessons": 0, "feedback": 0, "clusters": 0}
    for key, sql in (
        ("lessons", _PURGE_LESSONS),
        ("feedback", _PURGE_FEEDBACK),
        ("clusters", _PURGE_CLUSTERS),
    ):
        for _ in range(50):
            n = (await db.execute(sql, {"batch": batch})).rowcount or 0
            await db.commit()
            out[key] += n
            if n < batch:
                break
    return out


# GDPR erase, run inside gdpr_purge's own transaction

ERASE_SQL = (
    text(
        "UPDATE eval_cases SET input_message = :erased, reference_output = NULL "
        "WHERE tenant_id = :t AND source_lesson_id IN (SELECT id FROM lessons WHERE "
        "tenant_id = :t AND (by_user = :uid OR execution_id IN (SELECT id FROM executions "
        "WHERE user_id = :uid AND tenant_id = :t))) AND input_message <> :erased"
    ),
    text(
        "UPDATE improvement_proposals SET proof = proof - 'examples', updated_at = now() "
        "WHERE tenant_id = :t AND (proof -> 'examples') IS NOT NULL AND cluster_id IN "
        "(SELECT cluster_id FROM lessons WHERE tenant_id = :t AND cluster_id IS NOT NULL "
        "AND (by_user = :uid OR execution_id IN (SELECT id FROM executions WHERE "
        "user_id = :uid AND tenant_id = :t)))"
    ),
    text(
        "UPDATE improvement_proposals SET created_by = NULL "
        "WHERE tenant_id = :t AND created_by = :uid"
    ),
    text(
        "UPDATE lessons SET input_text = :erased, output_text = :erased, expected = NULL, "
        "note = NULL, by_user = NULL WHERE tenant_id = :t AND (by_user = :uid OR "
        "execution_id IN (SELECT id FROM executions WHERE user_id = :uid AND tenant_id = :t)) "
        "AND (input_text <> :erased OR output_text <> :erased OR expected IS NOT NULL "
        "OR note IS NOT NULL OR by_user IS NOT NULL)"
    ),
    text("DELETE FROM feedback WHERE tenant_id = :t AND user_id = :uid"),
)


__all__ = [
    "CLUSTER_LOCK_KEY",
    "ERASE_SQL",
    "LessonError",
    "RETAIN_LOCK_KEY",
    "add_note",
    "agent_view",
    "bulk_cases",
    "capture",
    "capture_action",
    "case_action",
    "case_for",
    "cluster_detail",
    "cluster_soon",
    "cluster_tick",
    "dismiss_cluster",
    "give_feedback",
    "harvest",
    "list_lessons",
    "overview",
    "patch_case",
    "purge_retention",
    "run_tick",
]
