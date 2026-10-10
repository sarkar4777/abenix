"""POST /api/pipelines/{id}/execute without nodes runs the agent's saved pipeline instead of a bare 422."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.routers import pipelines as router
from app.schemas.pipelines import ExecutePipelineRequest

pytestmark = pytest.mark.asyncio


def test_nodes_are_optional():
    body = ExecutePipelineRequest.model_validate({"context": {"goal": "x"}})
    assert body.nodes == []


async def test_no_nodes_runs_the_saved_pipeline():
    saved = AsyncMock(return_value="ran saved")
    body = ExecutePipelineRequest(context={"goal": "x"}, timeout_seconds=60)
    user, db = SimpleNamespace(), SimpleNamespace()
    with patch.object(router, "execute_saved_pipeline", saved):
        out = await router.execute_pipeline("a1", body, user, db)
    assert out == "ran saved"
    args = saved.await_args.args
    assert args[0] == "a1"
    assert args[1].context == {"goal": "x"} and args[1].timeout_seconds == 60
