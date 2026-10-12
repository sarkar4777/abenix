"""Signal rules over telemetry streams. Importing the package registers the ingest evaluator."""

from __future__ import annotations

try:
    from app.telemetry import evaluators as _ev
    from app.telemetry.rules.evaluator import RuleEvaluator

    _ev.register(RuleEvaluator())
except Exception:  # noqa: BLE001
    # the API imports the package for its helpers, the evaluator only matters on the ingest
    pass
