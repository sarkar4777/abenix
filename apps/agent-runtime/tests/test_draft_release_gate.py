"""High and critical tier drafts only run for people testing them, never from pipelines, triggers or API keys."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from engine.risk import DRAFT_NOT_RELEASED, draft_needs_release, draft_release_message


@pytest.mark.parametrize(
    "status,tier,blocked",
    [
        ("draft", "high", True),
        ("draft", "critical", True),
        ("DRAFT", "High", True),
        ("draft", "low", False),
        ("draft", "medium", False),
        ("draft", None, False),
        ("active", "critical", False),
    ],
)
def test_only_high_and_critical_drafts_need_release(status, tier, blocked):
    assert draft_needs_release(status, tier) is blocked


def test_message_says_how_to_fix_it():
    msg = draft_release_message("Dispatch", "critical")
    assert (
        "critical risk draft" in msg
        and "Publish it first" in msg
        and "builder and chat" in msg
    )


def test_pipeline_agent_step_refuses_an_unreleased_high_tier_agent():
    from engine.tools import agent_step as mod

    tool = mod.AgentStepTool() if hasattr(mod, "AgentStepTool") else None
    if tool is None:
        pytest.skip("agent step tool class not found")
    args = {
        "__agent_id__": "a1",
        "__tenant_id__": "t1",
        "input_message": "go",
        "system_prompt": "x",
    }
    with patch.object(
        mod, "_budget_breach", AsyncMock(return_value=None)
    ), patch.object(
        mod,
        "_agent_settings",
        AsyncMock(return_value=({"risk_tier": "high"}, None, "draft")),
    ):
        res = asyncio.run(tool.execute(args))
    assert res.is_error
    assert res.metadata["failure_code"] == DRAFT_NOT_RELEASED
