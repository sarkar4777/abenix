from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from app.core.deps import async_session

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
from models.llm_pricing import LLMModelPricing, ModelAvailability  # type: ignore  # noqa: E402

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 2
RECOVERY_THRESHOLD = 1
PING_TIMEOUT = 12.0


def _subscription_helper():
    """The runtime's credential helper, or None if it isn't importable.

    The api image ships apps/agent-runtime, so this normally resolves; the
    guard keeps the prober working if it ever doesn't.
    """
    try:
        sys.path.insert(
            0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime")
        )
        from engine import claude_subscription  # type: ignore

        return claude_subscription
    except Exception as exc:  # pragma: no cover - import-environment dependent
        logger.debug("claude_subscription helper unavailable: %s", exc)
        return None


async def _ping_anthropic(model: str) -> tuple[bool, str | None, int | None]:
    try:
        import anthropic

        # Probe with the credential the platform will actually use. On a
        # subscription-only install there is no ANTHROPIC_API_KEY, so a
        # bare client would fail and the prober would mark every Claude
        # model unavailable — which then makes model_resolver swap away
        # from the very models the subscription serves.
        helper = _subscription_helper()
        if helper is not None:
            client, used_sub = helper.build_async_client()
            if used_sub:
                # exclusive mode runs every request on its own model, probe that one
                model = helper.effective_model(model)
        else:
            client = anthropic.AsyncAnthropic()
        t0 = time.monotonic()
        await asyncio.wait_for(
            client.messages.create(
                model=model,
                max_tokens=1,
                messages=[{"role": "user", "content": "."}],
            ),
            timeout=PING_TIMEOUT,
        )
        return True, None, int((time.monotonic() - t0) * 1000)
    except Exception as exc:
        return False, str(exc)[:512], None


async def _ping_openai(model: str) -> tuple[bool, str | None, int | None]:
    try:
        import openai

        client = openai.AsyncOpenAI()
        t0 = time.monotonic()
        await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                max_tokens=1,
                messages=[{"role": "user", "content": "."}],
            ),
            timeout=PING_TIMEOUT,
        )
        return True, None, int((time.monotonic() - t0) * 1000)
    except Exception as exc:
        return False, str(exc)[:512], None


async def _ping_google(model: str) -> tuple[bool, str | None, int | None]:
    try:
        from google import genai as gg

        client = gg.Client()
        t0 = time.monotonic()
        await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=".",
            ),
            timeout=PING_TIMEOUT,
        )
        return True, None, int((time.monotonic() - t0) * 1000)
    except Exception as exc:
        return False, str(exc)[:512], None


async def _ping_azure(model: str) -> tuple[bool, str | None, int | None]:
    try:
        import openai

        endpoint = os.environ.get("AZURE_OPENAI_API_BASE", "").rstrip("/")
        if endpoint.endswith("/openai/deployments"):
            endpoint = endpoint[: -len("/openai/deployments")]
        if endpoint.endswith("/openai"):
            endpoint = endpoint[: -len("/openai")]
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-01-preview")
        if not endpoint or not api_key:
            return False, "azure_credentials_missing", None
        deployment = model[len("azure-") :] if model.startswith("azure-") else model
        client = openai.AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        t0 = time.monotonic()
        is_reasoning = (
            deployment.startswith("gpt-5")
            or deployment.startswith("o1")
            or deployment.startswith("o3")
        )
        kwargs: dict[str, Any] = {
            "model": deployment,
            "messages": [{"role": "user", "content": "."}],
        }
        if is_reasoning:
            kwargs["max_completion_tokens"] = 1
        else:
            kwargs["max_tokens"] = 1
        await asyncio.wait_for(
            client.chat.completions.create(**kwargs),
            timeout=PING_TIMEOUT,
        )
        return True, None, int((time.monotonic() - t0) * 1000)
    except Exception as exc:
        return False, str(exc)[:512], None


_PINGER = {
    "anthropic": _ping_anthropic,
    "openai": _ping_openai,
    "google": _ping_google,
    "azure": _ping_azure,
}


async def ping_one(model: str, provider: str) -> dict[str, Any]:
    try:
        from engine import llm_stub

        if llm_stub.enabled():
            return {
                "model": model,
                "ok": True,
                "error": None,
                "latency_ms": 0,
                "provider": provider,
            }
    except ImportError:
        pass
    pinger = _PINGER.get(provider)
    if not pinger:
        return {
            "model": model,
            "ok": False,
            "error": f"unknown_provider:{provider}",
            "latency_ms": None,
        }
    ok, err, lat = await pinger(model)
    return {
        "model": model,
        "ok": ok,
        "error": err,
        "latency_ms": lat,
        "provider": provider,
    }


async def _persist_result(db, row: dict[str, Any]) -> tuple[str | None, str | None]:
    """Update model_availability + emit transition events; return (old, new)."""
    now = datetime.now(timezone.utc)
    current = (
        await db.execute(
            select(ModelAvailability).where(ModelAvailability.model == row["model"])
        )
    ).scalar_one_or_none()
    if current is None:
        current = ModelAvailability(
            model=row["model"],
            provider=row["provider"],
            status="available" if row["ok"] else "unavailable",
            last_checked_at=now,
            last_ok_at=now if row["ok"] else None,
            last_error=row.get("error"),
            consecutive_failures=0 if row["ok"] else 1,
            latency_ms=row.get("latency_ms"),
            status_since=now,
        )
        db.add(current)
        return None, current.status

    old_status = current.status
    if row["ok"]:
        current.last_ok_at = now
        current.last_error = None
        current.latency_ms = row.get("latency_ms")
        new_failures = 0
        new_status = old_status
        if old_status != "available" and (current.consecutive_failures - 1 + 1) <= 0:
            new_status = "available"
        if old_status != "available":
            new_status = "available"
    else:
        current.last_error = row.get("error")
        new_failures = (current.consecutive_failures or 0) + 1
        new_status = old_status
        if old_status == "available" and new_failures >= FAILURE_THRESHOLD:
            new_status = "unavailable"

    current.consecutive_failures = new_failures
    current.last_checked_at = now
    if new_status != old_status:
        current.status = new_status
        current.status_since = now
        await db.execute(
            text(
                """
                INSERT INTO model_availability_events (model, from_status, to_status, error)
                VALUES (:m, :f, :t, :e)
                """
            ),
            {
                "m": row["model"],
                "f": old_status,
                "t": new_status,
                "e": row.get("error"),
            },
        )
        return old_status, new_status
    return old_status, old_status


_reprobe_task: Any = None

# keys that change which provider can serve a model
PROVIDER_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "AZURE_OPENAI_API_KEY",
)


def schedule_reprobe(delay: float = 3.0) -> None:
    """Re-check every model soon after a model connection changes, not at the next hourly run."""
    import asyncio

    global _reprobe_task
    if _reprobe_task is not None and not _reprobe_task.done():
        return

    async def _later() -> None:
        # settings snapshots refresh within a few seconds
        await asyncio.sleep(delay)
        try:
            await run_pings()
        except Exception as e:  # noqa: BLE001
            logger.warning("model re-check after a connection change failed: %s", e)

    try:
        _reprobe_task = asyncio.get_running_loop().create_task(_later())
    except RuntimeError:
        _reprobe_task = None


async def run_pings() -> dict[str, Any]:
    """Probe every active, non-deprecated model and persist availability."""
    async with async_session() as db:
        rows = (
            await db.execute(
                select(LLMModelPricing.model, LLMModelPricing.provider)
                .where(
                    LLMModelPricing.is_active.is_(True),
                    LLMModelPricing.is_deprecated.is_(False),
                )
                .order_by(LLMModelPricing.model)
            )
        ).all()
    seen: set[str] = set()
    targets: list[tuple[str, str]] = []
    for model, provider in rows:
        if model in seen:
            continue
        seen.add(model)
        targets.append((model, str(provider).lower()))

    results = await asyncio.gather(
        *[ping_one(m, p) for m, p in targets],
        return_exceptions=False,
    )

    transitions: list[dict[str, Any]] = []
    async with async_session() as db:
        for row in results:
            old, new = await _persist_result(db, row)
            if old is not None and old != new:
                transitions.append({"model": row["model"], "from": old, "to": new})
        await db.commit()

    if transitions:
        try:
            await _notify_transitions(transitions)
        except Exception as exc:
            logger.warning("notify_transitions failed: %s", exc)

    logger.info(
        "model_availability_ping ran=%d up=%d down=%d transitions=%d",
        len(results),
        sum(1 for r in results if r["ok"]),
        sum(1 for r in results if not r["ok"]),
        len(transitions),
    )
    try:
        from engine.model_resolver import invalidate_cache

        invalidate_cache()
    except Exception:
        pass
    return {"checked": len(results), "transitions": transitions}


async def _notify_transitions(transitions: list[dict[str, Any]]) -> None:
    if not transitions:
        return
    try:
        from models.notification import Notification, NotificationType
    except Exception:
        return
    async with async_session() as db:
        admins = (
            await db.execute(
                text(
                    "SELECT id, tenant_id FROM users WHERE role = 'admin' AND is_active = true"
                )
            )
        ).all()
        for t in transitions:
            title = (
                f"Model {t['model']} is unavailable"
                if t["to"] == "unavailable"
                else f"Model {t['model']} recovered"
            )
            msg = (
                f"Status transitioned {t['from']} → {t['to']}. "
                "Fallback chain will engage automatically for impacted runs."
            )
            for uid, tid in admins:
                nt_type = NotificationType.SYSTEM_ALERT
                n = Notification(
                    tenant_id=tid,
                    user_id=uid,
                    type=nt_type,
                    title=title,
                    message=msg,
                    link="/admin/llm-pricing",
                    metadata_={"model": t["model"], "from": t["from"], "to": t["to"]},
                )
                db.add(n)
        await db.commit()
