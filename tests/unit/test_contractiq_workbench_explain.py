"""ContractIQ workbench explain goes through the SDK's ml_models.explain, errors stay readable."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

CIQ_API = Path(__file__).resolve().parents[2] / "contractiq" / "api"

# contractiq's app package clashes with the platform's, so it runs in its own interpreter
SCRIPT = textwrap.dedent(
    """
    import asyncio, json, sys
    sys.path.insert(0, "sdk")
    from abenix_sdk import AbenixError
    from fastapi import HTTPException
    import app.routers.executions as ex

    calls = []

    class Models:
        def __init__(self, behaviour):
            self.behaviour = behaviour

        async def explain(self, name, row):
            calls.append([name, row])
            if self.behaviour == "missing":
                raise AbenixError(404, "No ML model called nope.", "NOT_FOUND")
            if self.behaviour == "down":
                raise ConnectionError("refused")
            return {"method": "linear", "prediction": 2.5, "contributions": [], "extra": 1}

    class Forge:
        def __init__(self, behaviour):
            self.ml_models = Models(behaviour)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    async def run(behaviour, payload):
        ex._sdk = lambda timeout=30.0: Forge(behaviour)
        try:
            r = await ex.run_workbench_explain(payload, user=None)
            return {"status": 200, "body": json.loads(r.body)}
        except HTTPException as e:
            return {"status": e.status_code, "detail": e.detail}

    row = {"a": 1.0}
    out = {
        "ok": asyncio.run(run("ok", {"model_name": "m", "feature_vector": row})),
        "missing": asyncio.run(run("missing", {"model_name": "nope", "feature_vector": row})),
        "down": asyncio.run(run("down", {"model_name": "m", "feature_vector": row})),
        "no_name": asyncio.run(run("ok", {"feature_vector": row})),
        "no_row": asyncio.run(run("ok", {"model_name": "m"})),
        "calls": calls,
    }
    print("RESULT" + json.dumps(out))
    """
)


def _run() -> dict:
    env = {**os.environ, "DATABASE_URL": "postgresql+asyncpg://t:t@localhost/t"}
    proc = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=CIQ_API,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    line = next(
        (ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT")), None
    )
    assert line, proc.stderr[-2000:]
    return json.loads(line[len("RESULT") :])


def test_workbench_explain_paths():
    out = _run()
    ok = out["ok"]
    assert ok["status"] == 200
    assert ok["body"]["ok"] is True and ok["body"]["method"] == "linear"
    assert ok["body"]["prediction"] == 2.5
    assert "extra" not in ok["body"]
    assert out["calls"][0] == ["m", {"a": 1.0}]
    assert out["missing"]["status"] == 404
    assert "No ML model called nope" in out["missing"]["detail"]
    assert out["down"]["status"] == 502
    assert out["no_name"]["status"] == 400
    assert out["no_row"]["status"] == 400


def test_the_code_asset_path_is_gone():
    src = (CIQ_API / "app" / "routers" / "executions.py").read_text(encoding="utf-8")
    assert "shap_explainer" not in src
    assert "feature-magnitude-fallback" not in src
