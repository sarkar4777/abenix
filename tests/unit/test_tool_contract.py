"""Every registry tool must satisfy the BaseTool contract.

atlas_cypher shipped two tools that subclassed BaseTool but implemented `run`
instead of the abstract `execute`, so neither could be instantiated — every
call ended as an uncaught TypeError and a bare 500 from the API. Nothing in the
suite noticed, because nothing asserted the contract itself.
"""

from __future__ import annotations

import inspect
import pkgutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "apps" / "agent-runtime"
for p in (str(RUNTIME), str(ROOT / "apps" / "api")):
    if p not in sys.path:
        sys.path.insert(0, p)

from engine.tools.base import BaseTool  # noqa: E402


def _tool_classes() -> list[type]:
    """Import every engine.tools module and collect concrete BaseTool subclasses."""
    import engine.tools as tools_pkg

    found: dict[str, type] = {}
    for mod in pkgutil.iter_modules(tools_pkg.__path__):
        if mod.name.startswith("_"):
            continue
        try:
            module = __import__(f"engine.tools.{mod.name}", fromlist=["*"])
        except Exception:
            # A module whose optional third-party import is absent in this
            # environment is out of scope for a contract check.
            continue
        for name, obj in vars(module).items():
            # Abstract subclasses are deliberately included: filtering them out
            # here would let a tool that regresses to abstract vanish from the
            # parametrised list and "pass" by not being tested at all.
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseTool)
                and obj is not BaseTool
                and getattr(obj, "__module__", "").startswith("engine.tools")
            ):
                found[f"{obj.__module__}.{name}"] = obj
    return list(found.values())


TOOL_CLASSES = _tool_classes()


def test_tool_classes_were_discovered() -> None:
    assert len(TOOL_CLASSES) > 20, f"only found {len(TOOL_CLASSES)} tool classes"


@pytest.mark.parametrize("cls", TOOL_CLASSES, ids=lambda c: f"{c.__module__}.{c.__name__}")
def test_tool_implements_execute(cls: type) -> None:
    """execute must be defined somewhere other than the abstract base."""
    assert hasattr(cls, "execute"), f"{cls.__name__} has no execute"
    owner = next(
        (k for k in cls.__mro__ if "execute" in vars(k)),
        None,
    )
    assert owner is not None and owner is not BaseTool, (
        f"{cls.__name__} inherits execute only from BaseTool — it defines "
        f"{[m for m in vars(cls) if not m.startswith('_')]} instead"
    )


@pytest.mark.parametrize("cls", TOOL_CLASSES, ids=lambda c: f"{c.__module__}.{c.__name__}")
def test_tool_is_not_abstract(cls: type) -> None:
    """An abstract leftover cannot be constructed, so it can never be called."""
    assert not inspect.isabstract(cls), (
        f"{cls.__name__} still has abstract methods: "
        f"{sorted(getattr(cls, '__abstractmethods__', ()))}"
    )


# Mirrors the kwarg set apps/api/app/routers/tools.py::execute_tool builds, so
# this checks the shape the endpoint really uses rather than an invented one.
ENDPOINT_KWARGS = {
    "tenant_id": "00000000-0000-0000-0000-000000000000",
    "execution_id": "",
    "agent_id": "",
    "api_key": "",
    "api_base": "",
    "db_url": "",
    "kb_ids": [],
    "kb_id": "",
}

# Internal plumbing rather than callable registry entries, so none of these is
# reachable through /api/tools/{slug}/execute: _DefaultedTool wraps another
# tool, DynamicTool is built from a stored spec, and PipelineAgentTool takes a
# per-agent pipeline config and names itself "pipeline:<agent>" at runtime
# rather than owning a static slug.
NOT_DIRECTLY_EXECUTABLE = {"_DefaultedTool", "DynamicTool", "PipelineAgentTool"}


@pytest.mark.parametrize("cls", TOOL_CLASSES, ids=lambda c: f"{c.__module__}.{c.__name__}")
def test_tool_constructs_the_way_the_endpoint_builds_it(cls: type) -> None:
    """A tool must be constructible from the kwargs the endpoint supplies.

    Tools that legitimately need more configuration raise ValueError, which the
    endpoint turns into a 400. A TypeError means the signature does not match
    how the tool is actually built, which surfaced as a bare 500.
    """
    if cls.__name__ in NOT_DIRECTLY_EXECUTABLE:
        pytest.skip(f"{cls.__name__} is constructed by the registry, not the endpoint")

    try:
        sig = inspect.signature(cls.__init__)
        accepted = set(sig.parameters) - {"self"}
    except (TypeError, ValueError):
        accepted = set()
    kwargs = {k: v for k, v in ENDPOINT_KWARGS.items() if not accepted or k in accepted}

    for attempt in (kwargs, {"tenant_id": ENDPOINT_KWARGS["tenant_id"]}, {}):
        try:
            cls(**attempt)
            return
        except ValueError:
            return  # needs config — the endpoint reports 400, not a crash
        except TypeError:
            continue
    pytest.fail(
        f"{cls.__name__} rejects every kwarg shape the endpoint tries "
        f"(accepted params: {sorted(accepted)})"
    )
