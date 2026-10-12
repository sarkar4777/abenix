"""Record evaluators: code that sees every stored record on the ingest, such as signal rules.

observe() is called on the hot path right after the records are stored in the
batch, so it must be synchronous, quick, and never raise. Heavy work belongs in
the evaluator's own task, started from start(). A package at app.telemetry.rules
registers itself from its __init__ and is imported by load().
"""

from typing import Any, Protocol

from app.telemetry.decoders.base import Record
from app.telemetry.store import ConnInfo


class RecordEvaluator(Protocol):
    name: str

    # once per replica, after Ingest._setup
    async def start(self, host: Any) -> None: ...

    # sync, must not await or raise
    def observe(self, conn: ConnInfo, records: list[Record], t_recv: float) -> None: ...

    async def stop(self) -> None: ...


_REGISTRY: list[RecordEvaluator] = []


def register(ev: RecordEvaluator) -> None:
    if all(e.name != ev.name for e in _REGISTRY):
        _REGISTRY.append(ev)


def load() -> list[RecordEvaluator]:
    import importlib

    for mod in ("app.telemetry.rules",):
        try:
            importlib.import_module(mod)
        except Exception:  # noqa: BLE001
            pass
    return list(_REGISTRY)
