"""Shared pytest fixtures for the ResolveAI API test suite."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest
import pytest_asyncio

# Make the api package importable when pytest is invoked from
# ``resolveai/api`` *or* from the repo root.
API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
SDK_ROOT = API_ROOT / "sdk"
if SDK_ROOT.exists() and str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))


# ─── Stub ExecutionResult payload ────────────────────────────────────
# Default: a successful auto-resolution the Inbound Resolution pipeline
# would emit. Tests override via ``mock_sdk.configure(output=...)``.
DEFAULT_AUTO_RESOLVED_PAYLOAD: dict[str, Any] = {
    "reply": (
        "Hi! I've gone ahead and issued a full refund for order ord-5484. "
        "You should see it back on your card in 3-5 business days."
    ),
    "deflection_score": 0.85,
    "citations": [
        {"policy_id": "refund-policy-us", "version": 3,
         "excerpt": "Full refunds permitted within 30 days of purchase."},
    ],
    "action_plan": {
        "actions": [
            {"type": "issue_refund", "amount_usd": 19.99,
             "order_id": "ord-5484", "requires_approval": False},
        ],
    },
    "triage": {"category": "refund", "intent": "refund_request", "urgency": "normal"},
    "policy_research": {
        "policies": [
            {"policy_id": "refund-policy-us", "version": 3,
             "clause": "30-day no-questions-asked window"},
        ],
    },
    "moderation_vet": {"decision": "allow", "reason": ""},
}


@pytest.fixture(autouse=True)
def _set_sdk_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee ``_deps.get_sdk`` thinks it has a valid SDK key + URL."""
    monkeypatch.setenv("RESOLVEAI_ABENIX_API_KEY", "af_test_dummy_key")
    monkeypatch.setenv("ABENIX_API_URL", "http://test.invalid")
    # ``DATABASE_URL`` unset → ``build_store()`` picks InMemoryStore.
    monkeypatch.delenv("DATABASE_URL", raising=False)


class _MockSDK:
    """Handle exposed to tests to customise the stub SDK behaviour."""

    def __init__(self) -> None:
        self._payload: Any = dict(DEFAULT_AUTO_RESOLVED_PAYLOAD)
        self._cost = 0.0123
        self._duration_ms = 842
        self._exc: Exception | None = None
        self.calls: list[dict[str, Any]] = []

    # ── configuration ─────────────────────────────────────────────
    def configure(
        self,
        *,
        output: Any | None = None,
        cost: float | None = None,
        duration_ms: int | None = None,
    ) -> None:
        if output is not None:
            self._payload = output
        if cost is not None:
            self._cost = cost
        if duration_ms is not None:
            self._duration_ms = duration_ms

    def raise_on_execute(self, exc: Exception) -> None:
        self._exc = exc

    # ── behaviour the test harness invokes ────────────────────────
    async def execute(
        self,
        agent_slug_or_id: str,
        message: str,
        *_: Any,
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            {"agent": agent_slug_or_id, "message": message, "kwargs": kwargs},
        )
        if self._exc is not None:
            raise self._exc
        from abenix_sdk import ExecutionResult  # type: ignore[import-not-found]
        return ExecutionResult(
            output=self._payload,  # type: ignore[arg-type]
            cost=self._cost,
            duration_ms=self._duration_ms,
            model="stub-model",
        )

    async def close(self) -> None:
        return None


@pytest.fixture
def mock_sdk() -> _MockSDK:
    """Return a stub ``Abenix`` client."""
    return _MockSDK()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, mock_sdk: _MockSDK):
    """FastAPI app with a **fresh** in-memory store and SDK stub."""
    import main  # type: ignore[import-not-found]
    from app.core.store import InMemoryStore  # type: ignore[import-not-found]
    from app.routers import _deps  # type: ignore[import-not-found]
    from app.routers import cases as cases_mod  # type: ignore[import-not-found]
    from app.routers import qa as qa_mod  # type: ignore[import-not-found]
    from app.routers import sla as sla_mod  # type: ignore[import-not-found]
    from app.routers import trends as trends_mod  # type: ignore[import-not-found]

    # Fresh store per test — no cross-test leakage.
    main.app.state.store = InMemoryStore()

    # Patch every ``get_sdk`` binding so a direct function call inside
    # a handler returns our stub. Each router imports the name locally
    # via ``from app.routers._deps import get_sdk`` so the patch has to
    # be applied to each module's namespace.
    sdk_factory = lambda: mock_sdk
    monkeypatch.setattr(_deps, "get_sdk", sdk_factory)
    monkeypatch.setattr(cases_mod, "get_sdk", sdk_factory)
    monkeypatch.setattr(qa_mod, "get_sdk", sdk_factory)
    monkeypatch.setattr(sla_mod, "get_sdk", sdk_factory)
    monkeypatch.setattr(trends_mod, "get_sdk", sdk_factory)

    # Also register the FastAPI override — harmless belt-and-braces in
    # case a router starts using ``Depends(get_sdk)`` later.
    main.app.dependency_overrides[_deps.get_sdk] = sdk_factory

    try:
        yield main.app
    finally:
        main.app.dependency_overrides.pop(_deps.get_sdk, None)
        try:
            del main.app.state.store
        except AttributeError:
            pass


@pytest_asyncio.fixture
async def client(app):
    """httpx.AsyncClient wired to the FastAPI app in-memory."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as c:
        yield c


# ─── sample_ticket factory ──────────────────────────────────────────

_TICKET_TEMPLATES: dict[str, dict[str, Any]] = {
    "refund": {
        "customer_id": "c-1001",
        "channel": "chat",
        "subject": "Refund for damaged package",
        "body": ("Box was crushed, item dented. Photos attached. "
                 "Want a full refund please."),
        "order_id": "ord-5484",
        "sku": "SKU-RED-L",
        "customer_tier": "standard",
        "jurisdiction": "US",
        "locale": "en",
    },
    "exchange": {
        "customer_id": "c-1002",
        "channel": "email",
        "subject": "Wrong size — need to exchange",
        "body": "Ordered M, got L. Happy to exchange not refund.",
        "order_id": "ord-5485",
        "sku": "SKU-BLUE-M",
        "customer_tier": "standard",
        "jurisdiction": "US",
        "locale": "en",
    },
    "complaint": {
        "customer_id": "c-1003",
        "channel": "chat",
        "subject": "This product doesn't work as advertised",
        "body": ("I bought this last week and it fails immediately on "
                 "startup. Terrible experience."),
        "order_id": None,
        "sku": "SKU-GRN-S",
        "customer_tier": "standard",
        "jurisdiction": "US",
        "locale": "en",
    },
    "vip_escalation": {
        "customer_id": "c-9001",
        "channel": "chat",
        "subject": "VIP account — urgent chargeback issue",
        "body": ("I've been a platinum member for six years and I'm "
                 "seeing a fraudulent charge. Please escalate immediately."),
        "order_id": "ord-9999",
        "sku": "SKU-PLATINUM",
        "customer_tier": "vip",
        "jurisdiction": "US",
        "locale": "en",
    },
}


@pytest.fixture
def sample_ticket() -> Callable[..., dict[str, Any]]:
    """Return deterministic ticket payloads by name."""

    def _factory(kind: str = "refund", **overrides: Any) -> dict[str, Any]:
        if kind not in _TICKET_TEMPLATES:
            raise KeyError(
                f"Unknown ticket kind {kind!r}. "
                f"Known: {sorted(_TICKET_TEMPLATES)}",
            )
        body = dict(_TICKET_TEMPLATES[kind])
        body.update(overrides)
        return body

    return _factory


@pytest.fixture
def random_case_id() -> str:
    """A UUID that looks like a real case id but will always 404."""
    import uuid
    return str(uuid.uuid4())
