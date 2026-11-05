from __future__ import annotations

import base64
import os
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import has_capability, need_words
from app.core.platform_features import is_dev_environment, parse_bool

PLAYGROUND_EXECUTE = "playground.execute"
ENABLE_ENV = "PLAYGROUND_EXECUTE_ENABLED"
SANDBOX_IMAGE_ENV = "PLAYGROUND_SANDBOX_IMAGE"

DISABLED_MESSAGE = (
    "Running code in the playground is turned off on this deployment, because the "
    "code runs inside the API process. Copy it and run it on your own machine, or "
    f"ask an operator to set {ENABLE_ENV}=true."
)


def execute_enabled() -> bool:
    explicit = parse_bool(os.environ.get(ENABLE_ENV))
    return is_dev_environment() if explicit is None else explicit


async def sandbox_image(tenant_id: Any) -> str:
    """The image to run playground code in, empty when no sandboxed job can take it."""
    image = os.environ.get(SANDBOX_IMAGE_ENV, "").strip()
    if not image:
        return ""
    from engine.tools.sandboxed_job import SandboxedJobTool

    settings = await SandboxedJobTool(tenant_id=str(tenant_id))._resolve_settings()
    # the snippet calls the API, so a job with no network could not run it
    usable = (
        settings["enabled"]
        and settings["allow_network"]
        and image in settings["allowed_images"]
    )
    return image if usable else ""


async def run_in_sandbox(
    image: str,
    tenant_id: Any,
    code: str,
    env: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    from engine.tools.sandboxed_job import SandboxedJobTool

    result = await SandboxedJobTool(tenant_id=str(tenant_id)).execute(
        {
            "image": image,
            "command": "python /in/snippet.py",
            "timeout_seconds": timeout,
            "network": True,
            "env": env,
            "files_b64": {
                "snippet.py": base64.b64encode(code.encode("utf-8")).decode()
            },
        }
    )
    meta = result.metadata or {}
    return {
        "stdout": meta.get("logs") or meta.get("stdout") or "",
        "stderr": meta.get("stderr") or "",
        "exit_code": meta.get("exit_code"),
        "message": "" if meta else str(result.content),
    }


async def playground_denial(db: AsyncSession, user: Any) -> str | None:
    if not execute_enabled() and not await sandbox_image(user.tenant_id):
        return DISABLED_MESSAGE
    if not await has_capability(db, user, PLAYGROUND_EXECUTE):
        return need_words(PLAYGROUND_EXECUTE)
    return None
