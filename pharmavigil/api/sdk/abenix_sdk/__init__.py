"""Abenix Python SDK — execute and monitor AI agents from any Python app."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx


@dataclass
class ActingSubject:
    """RBAC delegation: act on behalf of an end user."""
    subject_type: str           # e.g., "contractiq", "external", "user"
    subject_id: str             # end-user ID in third-party system
    email: str | None = None
    display_name: str | None = None
    metadata: dict[str, Any] | None = None

    def to_header(self) -> str:
        return json.dumps({k: v for k, v in {
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "email": self.email,
            "display_name": self.display_name,
            "metadata": self.metadata,
        }.items() if v is not None})


@dataclass
class StreamEvent:
    type: str  # token, tool_call, tool_result, node_start, node_complete, done, error
    text: str | None = None
    name: str | None = None
    arguments: dict[str, Any] | None = None
    result: str | None = None
    node_id: str | None = None
    tool_name: str | None = None
    status: str | None = None
    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None
    message: str | None = None
    error_code: str | None = None      # "timeout", "tool_error", "llm_error"
    agent_id: str | None = None        # Which agent/node failed
    traceback: str | None = None       # Stack trace (debug mode)
    output_preview: str | None = None  # Truncated output for node_complete events


@dataclass
class ApprovalRef:
    """Reference to a HITL gate that paused an execution."""
    approval_id: str
    title: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    required_signoffs: int = 1
    expires_at: str | None = None
    gate_kind: str | None = None


@dataclass
class ExecutionResult:
    output: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    duration_ms: int = 0
    model: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    confidence_score: float | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    execution_id: str | None = None
    status: str = "completed"               # completed | failed | paused | running
    paused_at: ApprovalRef | None = None    # set when status == "paused"


@dataclass
class DagSnapshot:
    """Idempotent snapshot of a running execution, delivered by `forge.watch(id)`."""
    execution_id: str
    agent_id: str | None = None
    agent_name: str | None = None
    mode: str = "agent"                         # "pipeline" | "agent"
    status: str = "queued"                      # queued|running|completed|failed
    started_at: str | None = None
    completed_at: str | None = None
    current_node_id: str | None = None
    progress: dict[str, int] = field(default_factory=lambda: {"completed": 0, "total": 0})
    cost_so_far: float = 0.0
    tokens: dict[str, int] = field(default_factory=lambda: {"in": 0, "out": 0})
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed")


@dataclass
class LiveExecution:
    execution_id: str
    agent_id: str
    agent_name: str
    status: str
    current_step: str = ""
    current_tool: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    iteration: int = 0
    max_iterations: int = 10
    confidence_score: float | None = None


class ExecutionsClient:
    def __init__(self, client: "Abenix"):
        self._client = client

    async def live(self) -> list[LiveExecution]:
        data = await self._client._get("/api/executions/live")
        return [LiveExecution(**e) for e in (data or [])]

    async def get(self, execution_id: str) -> dict[str, Any]:
        return await self._client._get(f"/api/executions/{execution_id}")

    async def replay(self, execution_id: str) -> dict[str, Any]:
        return await self._client._get(f"/api/executions/{execution_id}/replay")

    async def tree(self, execution_id: str) -> dict[str, Any]:
        return await self._client._get(f"/api/executions/tree/{execution_id}")

    async def pending_approvals(self) -> list[dict[str, Any]]:
        return await self._client._get("/api/executions/approvals") or []

    async def watch_raw_sse(self, execution_id: str) -> AsyncIterator[bytes]:
        """Yield the raw SSE byte-stream for an execution.

        Use this when a downstream surface (e.g. a standalone app's web pod)
        needs to forward the live DAG stream to a browser unchanged. Unlike
        ``forge.watch()`` which parses ``event: snapshot`` payloads into
        ``DagSnapshot`` dataclasses and drops everything else, this preserves
        every event line — ``tool_call``, ``tool_result``, ``node_start``,
        ``node_complete``, ``done``, ``error`` — so the trader's terminal
        sees the same picture the platform emitted.
        """
        async with self._client._http.stream(
            "GET",
            f"/api/executions/{execution_id}/watch",
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                yield chunk


class ToolsClient:
    """Tool catalogue + direct execution surface.

    `list()` enumerates the registered tools so AI-Builder palettes and
    standalone apps can render them without each duplicating the
    /api/tools fetch.

    `execute(slug, arguments, config=None)` runs a tool directly — bypasses
    the agent loop. Use this when an app needs the structured tool output
    without paying for an LLM round-trip (lookups, deterministic calcs,
    market data fetches). Each direct execute still runs through the
    sandbox and audit log.
    """

    def __init__(self, client: "Abenix"):
        self._client = client

    async def list(self) -> list[dict[str, Any]]:
        data = await self._client._get("/api/tools")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("data") or data.get("tools") or []
        return []

    async def catalog(self) -> list[dict[str, Any]]:
        return await self.list()

    async def execute(
        self,
        slug: str,
        arguments: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        body = {"arguments": arguments or {}, "config": config or {}}
        res = await self._client._http.post(
            f"/api/tools/{slug}/execute",
            json=body,
            headers=self._client._subject_headers(),
            timeout=timeout or self._client.timeout,
        )
        res.raise_for_status()
        return (res.json() or {}).get("data") or {}


class PresetsClient:
    """Per-tenant labelled (tool, default_args) bundles.

    Presets sit between the universal tool catalogue and end users. One
    generic ``yahoo_finance`` tool covers every instrument — but a preset
    named ``lbma_gold_fix`` pins ``{action: commodity_future, symbol:
    gold}`` so dashboards, agents, and SDK callers all share the same
    configured feed by a single slug. Agents that have access to the
    underlying tool automatically see the preset.
    """

    def __init__(self, client: "Abenix"):
        self._client = client

    async def list(
        self,
        *,
        tool_slug: str | None = None,
        ui_group: str | None = None,
        asset_class: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {
            k: v
            for k, v in {
                "tool_slug": tool_slug,
                "ui_group": ui_group,
                "asset_class": asset_class,
            }.items()
            if v
        }
        data = await self._client._get("/api/tool-presets", params=params)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("data") or []
        return []

    async def get(self, slug: str) -> dict[str, Any]:
        data = await self._client._get(f"/api/tool-presets/{slug}")
        return data if isinstance(data, dict) else {}

    async def upsert(self, body: dict[str, Any]) -> dict[str, Any]:
        res = await self._client._http.post(
            "/api/tool-presets",
            json=body,
            headers=self._client._subject_headers(),
            timeout=self._client.timeout,
        )
        res.raise_for_status()
        return (res.json() or {}).get("data") or {}

    async def delete(self, slug: str) -> dict[str, Any]:
        res = await self._client._http.delete(
            f"/api/tool-presets/{slug}",
            headers=self._client._subject_headers(),
            timeout=self._client.timeout,
        )
        res.raise_for_status()
        return (res.json() or {}).get("data") or {}

    async def run(
        self,
        slug: str,
        arguments: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        body = {"arguments": arguments or {}, "config": config or {}}
        res = await self._client._http.post(
            f"/api/tool-presets/{slug}/run",
            json=body,
            headers=self._client._subject_headers(),
            timeout=timeout or self._client.timeout,
        )
        res.raise_for_status()
        return (res.json() or {}).get("data") or {}


class ApprovalsClient:
    """First-class HITL surface — list, get, sign off, and wait on approvals.

    Replaces the older ``Abenix.approve(execution_id, gate_id)`` shape, which
    pretended a gate_id existed alongside the approval primary key. The DB
    only has approval ids, so this client takes that directly.
    """

    def __init__(self, client: "Abenix"):
        self._client = client

    async def list(
        self,
        *,
        status: str | None = None,
        execution_id: str | None = None,
        agent_id: str | None = None,
        kind: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if execution_id:
            params["execution_id"] = execution_id
        if agent_id:
            params["agent_id"] = agent_id
        if kind:
            params["kind"] = kind
        res = await self._client._http.get("/api/approvals", params=params)
        res.raise_for_status()
        return (res.json() or {}).get("data") or []

    async def get(self, approval_id: str) -> dict[str, Any]:
        return await self._client._get(f"/api/approvals/{approval_id}") or {}

    async def create(
        self,
        title: str,
        payload: dict[str, Any],
        *,
        required_signoffs: int = 1,
        expires_seconds: int = 86400,
        gate_kind: str | None = None,
        agent_id: str | None = None,
        agent_execution_id: str | None = None,
        client_token: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "title": title,
            "payload": payload,
            "required_signoffs": required_signoffs,
            "expires_seconds": expires_seconds,
        }
        if gate_kind:
            body["gate_kind"] = gate_kind
        if agent_id:
            body["agent_id"] = agent_id
        if agent_execution_id:
            body["agent_execution_id"] = agent_execution_id
        if client_token:
            body["client_token"] = client_token
        res = await self._client._http.post("/api/approvals", json=body)
        res.raise_for_status()
        return (res.json() or {}).get("data") or {}

    async def signoff(
        self,
        approval_id: str,
        decision: str,
        *,
        reason: str = "",
        client_token: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"decision": decision, "reason": reason}
        if client_token:
            body["client_token"] = client_token
        res = await self._client._http.post(
            f"/api/approvals/{approval_id}/signoff", json=body
        )
        res.raise_for_status()
        return (res.json() or {}).get("data") or {}

    async def approve(
        self, approval_id: str, *, reason: str = "", client_token: str | None = None
    ) -> dict[str, Any]:
        return await self.signoff(
            approval_id, "approve", reason=reason, client_token=client_token
        )

    async def deny(
        self, approval_id: str, *, reason: str = "", client_token: str | None = None
    ) -> dict[str, Any]:
        return await self.signoff(
            approval_id, "deny", reason=reason, client_token=client_token
        )

    async def wait_for(
        self, approval_id: str, *, timeout_seconds: int = 60, poll_seconds: float = 2.0
    ) -> dict[str, Any]:
        """Block until the approval leaves pending status or the timeout fires.

        Uses the server's /wait long-poll under the hood so a single client
        call covers up to 120s of real waiting per round-trip.
        """
        import asyncio as _asyncio
        deadline = max(1, int(timeout_seconds))
        elapsed = 0
        last: dict[str, Any] = {}
        while elapsed < deadline:
            chunk = min(120, deadline - elapsed)
            res = await self._client._http.get(
                f"/api/approvals/{approval_id}/wait",
                params={"timeout_seconds": chunk},
            )
            res.raise_for_status()
            last = (res.json() or {}).get("data") or {}
            if last.get("status") and last["status"] != "pending":
                return last
            elapsed += chunk
            if poll_seconds and elapsed < deadline:
                await _asyncio.sleep(poll_seconds)
        return last

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        """Stream approval lifecycle events for the tenant via the notification WS.

        Yields {event: 'approval_pending'|'approval_resolved', data: {...}}.
        Cleaner than a polling loop when building a reviewer UI.
        """
        async with self._client._http.stream(
            "GET",
            "/api/notifications/stream?types=approval_pending,approval_resolved",
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            current_event: str | None = None
            async for line in response.aiter_lines():
                if not line:
                    current_event = None
                    continue
                if line.startswith("event: "):
                    current_event = line[7:].strip()
                elif line.startswith("data: ") and current_event:
                    try:
                        payload = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    yield {"event": current_event, "data": payload}

    async def return_for_changes(
        self, approval_id: str, reason: str, *, client_token: str | None = None
    ) -> dict[str, Any]:
        """Send it back to the requester with what needs to change. A decision version returns to draft."""
        if not (reason or "").strip():
            raise ValueError("Say what needs to change, so the requester can correct it.")
        return await self.signoff(
            approval_id, "return", reason=reason, client_token=client_token
        )

    async def configure_webhook(
        self, *, url: str | None, secret: str | None = None
    ) -> dict[str, Any]:
        """Set or clear the tenant-level approval webhook URL (admin only)."""
        body: dict[str, Any] = {}
        if url is not None:
            body["url"] = url
        if secret is not None:
            body["secret"] = secret
        res = await self._client._http.put("/api/approvals/webhooks", json=body)
        res.raise_for_status()
        return (res.json() or {}).get("data") or {}


class AgentsClient:
    def __init__(self, client: "Abenix"):
        self._client = client

    async def list(self) -> list[dict[str, Any]]:
        return await self._client._get("/api/agents") or []

    async def get(self, agent_id: str) -> dict[str, Any]:
        return await self._client._get(f"/api/agents/{agent_id}")

    async def find_by_slug(self, slug: str) -> dict[str, Any] | None:
        res = await self._client._get(f"/api/agents?search={slug}&limit=10")
        items = (res.get("data") if isinstance(res, dict) else res) or []
        for a in items:
            if a.get("slug") == slug:
                return a
        return None

    async def by_slug(self, slug: str) -> dict[str, Any] | None:
        """Exact lookup by slug, None when there is no such agent."""
        try:
            return await _call(self._client, AbenixError, "GET", f"/api/agents/by-slug/{slug}")
        except AbenixError as e:
            if e.status == 404:
                return None
            raise

    async def create(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create an agent or pipeline. Takes the same fields as POST /api/agents, including model_config."""
        return await _call(self._client, AbenixError, "POST", "/api/agents", json=body)

    async def update(self, agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Change an agent. A name in the body also renames its slug, so leave it out to keep the slug."""
        return await _call(self._client, AbenixError, "PUT", f"/api/agents/{agent_id}", json=body)


class AbenixError(Exception):
    """A call the platform refused, with its message, status and code."""

    def __init__(self, status: int, message: str, code: str | None = None, details: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


class AbenixDecisionError(AbenixError):
    """A decision call the platform refused, with its message and code."""


async def _call(client: "Abenix", exc: type[AbenixError], method: str, path: str, **kw: Any) -> Any:
    res = await client._http.request(method, path, **kw)
    body: dict[str, Any] = {}
    try:
        body = res.json() or {}
    except ValueError:
        pass
    if not isinstance(body, dict):
        body = {"data": body}
    if res.status_code >= 400:
        err = body.get("error") or body.get("detail") or {}
        if isinstance(err, list):
            err = {"message": "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in err)}
        if not isinstance(err, dict):
            err = {"message": str(err)}
        raise exc(
            res.status_code, err.get("message") or f"HTTP {res.status_code}", err.get("error_code"), err.get("details")
        )
    return body.get("data")


class DecisionsClient:
    """Versioned business rules: evaluate, compare, test and propose changes."""

    def __init__(self, client: "Abenix"):
        self._client = client

    async def _call(self, method: str, path: str, **kw: Any) -> Any:
        return await _call(self._client, AbenixDecisionError, method, path, **kw)

    async def list(self, q: str = "") -> list[dict[str, Any]]:
        return await self._call("GET", "/api/decisions", params={"q": q} if q else None) or []

    async def get(self, key: str) -> dict[str, Any]:
        return await self._call("GET", f"/api/decisions/{key}")

    async def create(self, name: str, *, key: str | None = None, rules: Any = None, risk_tier: str = "low", description: str = "") -> dict[str, Any]:
        return await self._call("POST", "/api/decisions", json={"name": name, "key": key, "rules": rules, "risk_tier": risk_tier, "description": description})

    async def evaluate(
        self,
        key: str,
        facts: dict[str, Any],
        *,
        as_of: str | None = None,
        known_at: str | None = None,
        version: int | None = None,
        trace: bool = True,
        persist: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """outcome is decided, no_match, missing_facts or invalid_facts. Missing facts are never guessed."""
        return await self._call(
            "POST",
            f"/api/decisions/{key}/evaluate",
            json={"facts": facts, "as_of": as_of, "known_at": known_at, "version": version, "trace": trace,
                  "persist": persist, "idempotency_key": idempotency_key},
        )

    async def evaluate_batch(self, key: str, items: list[dict[str, Any]], *, as_of: str | None = None, version: int | None = None) -> dict[str, Any]:
        return await self._call("POST", f"/api/decisions/{key}/evaluate-batch", json={"items": items, "as_of": as_of, "version": version})

    async def compare(self, key: str, facts: dict[str, Any], targets: list[dict[str, Any]]) -> dict[str, Any]:
        """targets: [{"label", "version"} or {"as_of", "known_at"}], at least two."""
        return await self._call("POST", f"/api/decisions/{key}/compare", json={"facts": facts, "targets": targets})

    async def versions(self, key: str) -> list[dict[str, Any]]:
        return (await self.get(key)).get("versions") or []

    async def version(self, key: str, n: int) -> dict[str, Any]:
        return await self._call("GET", f"/api/decisions/{key}/versions/{n}")

    async def export(self, key: str, version: int | None = None) -> dict[str, Any]:
        return await self._call("GET", f"/api/decisions/{key}/export", params={"version": version} if version else None)

    async def propose_rules(self, key: str, rules: Any, *, note: str, mode: str = "merge") -> dict[str, Any]:
        """New draft from the version in force, the rules imported into it, then proposed for sign-off."""
        draft = await self._call("POST", f"/api/decisions/{key}/versions", json={"note": note})
        n = draft["version"]
        await self._call(
            "POST", f"/api/decisions/{key}/import", json={"payload": rules, "mode": mode, "version": n},
            headers={"If-Match": draft["etag"]},
        )
        return await self._call("POST", f"/api/decisions/{key}/versions/{n}/propose", json={"note": note})

    async def validate(self, key: str, version: int) -> dict[str, Any]:
        return await self._call("POST", f"/api/decisions/{key}/versions/{version}/validate")

    async def publish(self, key: str, version: int, *, expected_current: int | None = None) -> dict[str, Any]:
        return await self._call("POST", f"/api/decisions/{key}/versions/{version}/publish", json={"expected_current": expected_current})

    async def update(
        self,
        key: str,
        *,
        name: str | None = None,
        description: str | None = None,
        risk_tier: str | None = None,
        tags: list[str] | None = None,
        log_mode: str | None = None,
    ) -> dict[str, Any]:
        body = {k: v for k, v in {"name": name, "description": description, "risk_tier": risk_tier, "tags": tags, "log_mode": log_mode}.items() if v is not None}
        return await self._call("PATCH", f"/api/decisions/{key}", json=body)

    async def new_draft(self, key: str, *, note: str = "", from_version: int | None = None) -> dict[str, Any]:
        """A draft copied from from_version, or from the version in force. Carries an etag for saves."""
        return await self._call("POST", f"/api/decisions/{key}/versions", json={"note": note, "from_version": from_version})

    async def save_draft(
        self,
        key: str,
        version: int,
        *,
        etag: str | None = None,
        authoring: dict[str, Any] | None = None,
        content: dict[str, Any] | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        clear_valid_from: bool = False,
        clear_valid_to: bool = False,
        change_note: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save a draft. With an etag a stale save is refused with STALE_DRAFT. Problems found come back in problems."""
        body: dict[str, Any] = {"clear_valid_from": clear_valid_from, "clear_valid_to": clear_valid_to}
        for k, v in (("authoring", authoring), ("content", content), ("valid_from", valid_from), ("valid_to", valid_to),
                     ("change_note", change_note), ("provenance", provenance)):
            if v is not None:
                body[k] = v
        headers = {"If-Match": etag} if etag else None
        return await self._call("PUT", f"/api/decisions/{key}/versions/{version}", json=body, headers=headers)

    async def import_rules(self, key: str, version: int, rules: Any, *, mode: str = "merge", etag: str | None = None) -> dict[str, Any]:
        """Typed JSON rules into a draft. merge replaces rules by ruleKey and adds new ones, replace starts over."""
        if mode not in ("merge", "replace"):
            raise ValueError("mode must be merge or replace")
        headers = {"If-Match": etag} if etag else None
        return await self._call("POST", f"/api/decisions/{key}/import", json={"payload": rules, "mode": mode, "version": version}, headers=headers)

    async def propose(self, key: str, version: int, *, note: str = "") -> dict[str, Any]:
        """Validate and send a draft for sign-off under the decision's risk tier. Refused with VALIDATION_FAILED when not ready."""
        return await self._call("POST", f"/api/decisions/{key}/versions/{version}/propose", json={"note": note})

    async def withdraw(self, key: str, version: int) -> dict[str, Any]:
        return await self._call("POST", f"/api/decisions/{key}/versions/{version}/withdraw")

    async def publish_plan(self, key: str, version: int) -> dict[str, Any]:
        """What publishing would supersede or close, and why it would be refused, before anyone publishes."""
        return await self._call("GET", f"/api/decisions/{key}/versions/{version}/publish-plan")

    async def retire(self, key: str, version: int) -> dict[str, Any]:
        return await self._call("POST", f"/api/decisions/{key}/versions/{version}/retire")

    async def diff(self, key: str, a: int, b: int) -> dict[str, Any]:
        """Rules added, removed and changed between two versions, and how the valid period moved."""
        return await self._call("GET", f"/api/decisions/{key}/diff", params={"a": a, "b": b})

    async def tests(self, key: str) -> list[dict[str, Any]]:
        return await self._call("GET", f"/api/decisions/{key}/tests") or []

    async def add_test(self, key: str, name: str, facts: dict[str, Any], *, expected: Any = None, expected_outcome: str = "decided", as_of: str | None = None) -> dict[str, Any]:
        return await self._call("POST", f"/api/decisions/{key}/tests", json={"name": name, "facts": facts, "expected": expected, "expected_outcome": expected_outcome, "as_of": as_of})

    async def evaluations(self, key: str, limit: int = 50) -> list[dict[str, Any]]:
        return await self._call("GET", f"/api/decisions/{key}/evaluations", params={"limit": limit}) or []

    async def reference_sets(self) -> list[dict[str, Any]]:
        return await self._call("GET", "/api/decision-reference-sets") or []

    async def reference_set(self, key: str) -> dict[str, Any]:
        return await self._call("GET", f"/api/decision-reference-sets/{key}")

    async def put_reference_set(self, key: str, name: str, values: list[Any], description: str = "") -> dict[str, Any]:
        """Create the set, or save its values as a new version."""
        try:
            await self.reference_set(key)
        except AbenixDecisionError as e:
            if e.status != 404:
                raise
            return await self._call("POST", "/api/decision-reference-sets", json={"key": key, "name": name, "values": values, "description": description})
        return await self._call("PUT", f"/api/decision-reference-sets/{key}", json={"name": name, "values": values, "description": description})


class SourcesClient:
    """Source Watch: watched pages and feeds, their immutable snapshots and the changes found between them."""

    def __init__(self, client: "Abenix"):
        self._client = client

    async def _call(self, method: str, path: str, **kw: Any) -> Any:
        return await _call(self._client, AbenixError, method, path, **kw)

    async def list(self, q: str = "") -> list[dict[str, Any]]:
        return await self._call("GET", "/api/sources", params={"q": q} if q else None) or []

    async def get(self, source_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/api/sources/{source_id}")

    async def create(
        self,
        name: str,
        url: str,
        *,
        kind: str = "html",
        description: str = "",
        cadence_minutes: int | None = None,
        selector: str | None = None,
        jurisdiction: str | None = None,
        tags: list[str] | None = None,
        risk_tier: str = "low",
        active: bool = True,
        **extra: Any,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name, "url": url, "kind": kind, "description": description, "tags": tags or [],
                                "risk_tier": risk_tier, "active": active, **extra}
        if cadence_minutes is not None:
            body["cadence_minutes"] = cadence_minutes
        if selector:
            body["selector"] = selector
        if jurisdiction:
            body["jurisdiction"] = jurisdiction
        return await self._call("POST", "/api/sources", json=body)

    async def update(self, source_id: str, **fields: Any) -> dict[str, Any]:
        return await self._call("PATCH", f"/api/sources/{source_id}", json=fields)

    async def delete(self, source_id: str) -> dict[str, Any]:
        return await self._call("DELETE", f"/api/sources/{source_id}")

    async def pause(self, source_id: str, reason: str = "") -> dict[str, Any]:
        return await self._call("POST", f"/api/sources/{source_id}/pause", json={"reason": reason})

    async def resume(self, source_id: str) -> dict[str, Any]:
        return await self._call("POST", f"/api/sources/{source_id}/resume")

    async def check_now(self, source_id: str) -> dict[str, Any]:
        """Fetch now. Returns {outcome, source}, where outcome says whether anything changed."""
        return await self._call("POST", f"/api/sources/{source_id}/check-now")

    async def snapshots(self, source_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return await self._call("GET", f"/api/sources/{source_id}/snapshots", params={"limit": limit}) or []

    async def snapshot(self, snapshot_id: str, *, full: bool = False) -> dict[str, Any]:
        return await self._call("GET", f"/api/sources/snapshots/{snapshot_id}", params={"full": "true"} if full else None)

    async def source_changes(self, source_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return await self._call("GET", f"/api/sources/{source_id}/changes", params={"limit": limit}) or []

    async def changes(self, limit: int = 50) -> list[dict[str, Any]]:
        """Recent changes across every source in the tenant, newest first."""
        return await self._call("GET", "/api/sources/changes", params={"limit": limit}) or []

    async def change(self, change_id: str) -> dict[str, Any]:
        """One change with its diff and both snapshots."""
        return await self._call("GET", f"/api/sources/changes/{change_id}")

    async def validate_url(self, url: str) -> dict[str, Any]:
        return await self._call("POST", "/api/sources/validate-url", json={"url": url})

    async def preview(self, url: str, *, kind: str | None = None, selector: str | None = None) -> dict[str, Any]:
        return await self._call("POST", "/api/sources/preview", json={"url": url, "kind": kind, "selector": selector})

    async def settings(self) -> dict[str, Any]:
        return await self._call("GET", "/api/sources/settings")


class EventsClient:
    """Platform events delivered to a webhook, or used to start an agent or pipeline."""

    def __init__(self, client: "Abenix"):
        self._client = client

    async def _call(self, method: str, path: str, **kw: Any) -> Any:
        return await _call(self._client, AbenixError, method, path, **kw)

    async def catalog(self) -> list[dict[str, Any]]:
        return await self._call("GET", "/api/webhooks/catalog") or []

    async def list(self) -> list[dict[str, Any]]:
        return await self._call("GET", "/api/webhooks") or []

    async def subscribe(
        self,
        events: list[str],
        *,
        url: str | None = None,
        name: str = "",
        filter: dict[str, Any] | None = None,
        target_type: str = "webhook",
        target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """A webhook subscription returns its signing_secret once. Keep it to verify deliveries."""
        if not events:
            raise ValueError("Pick at least one event")
        body: dict[str, Any] = {"events": events, "name": name, "target_type": target_type}
        if url:
            body["url"] = url
        if filter:
            body["filter"] = filter
        if target:
            body["target"] = target
        return await self._call("POST", "/api/webhooks", json=body)

    async def update(self, subscription_id: str, **fields: Any) -> dict[str, Any]:
        return await self._call("PUT", f"/api/webhooks/{subscription_id}", json=fields)

    async def delete(self, subscription_id: str) -> dict[str, Any]:
        return await self._call("DELETE", f"/api/webhooks/{subscription_id}")

    async def test(self, subscription_id: str) -> dict[str, Any]:
        return await self._call("POST", f"/api/webhooks/{subscription_id}/test")

    async def deliveries(self, subscription_id: str, *, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        return await self._call("GET", f"/api/webhooks/{subscription_id}/deliveries", params=params) or []

    async def redeliver(self, delivery_id: str) -> dict[str, Any]:
        return await self._call("POST", f"/api/webhooks/deliveries/{delivery_id}/redeliver")

    @staticmethod
    def verify_signature(secret: str, body: bytes | str, signature: str | None) -> bool:
        """True when the X-Abenix-Signature header matches the raw request body."""
        import hashlib
        import hmac

        if not secret or not signature:
            return False
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        want = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(want, signature.strip())


class MLModelsClient:
    """Read-side access to the platform's ML model registry."""

    def __init__(self, client: "Abenix"):
        self._client = client

    async def list(self) -> list[dict[str, Any]]:
        res = await self._client._get("/api/ml-models")
        items = (res.get("data") if isinstance(res, dict) else res) or []
        return items if isinstance(items, list) else []


class KnowledgeClient:
    """Knowledge Engine client — Cognify, graph queries, and hybrid search."""

    def __init__(self, client: "Abenix"):
        self._client = client

    async def bootstrap_project(
        self,
        slug: str,
        name: str,
        description: str = "",
        collections: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a knowledge project and its collections, idempotently.

        Apps call this at startup so their agents have somewhere to search
        before anyone has uploaded anything. Re-running returns the existing
        rows rather than duplicating them.

        Each entry in `collections` takes `name`, and optionally `slug`,
        `description`, `default_visibility` (private/project/tenant),
        `vector_backend` (pinecone/pgvector), `agent_slugs` and
        `agent_permission`. Agent slugs that do not resolve come back in
        `skipped_agents` instead of failing the call.
        """
        res = await self._client._http.post(
            "/api/knowledge-projects/bootstrap",
            json={
                "slug": slug,
                "name": name,
                "description": description,
                "collections": collections or [],
            },
        )
        res.raise_for_status()
        return res.json().get("data", {})

    async def ensure_subject_collection(
        self,
        project_slug: str,
        subject_type: str,
        subject_id: str,
        description: str = "",
        default_visibility: str = "private",
        vector_backend: str = "pgvector",
    ) -> dict[str, Any]:
        """Get or create the collection belonging to one subject.

        A subject is whatever the app partitions its corpus by — usually a
        user, sometimes a tenant or a case. Returns the collection, so the
        caller can pass its id straight to `cognify` or `search`.
        """
        res = await self._client._http.post(
            f"/api/knowledge-projects/{project_slug}/subject-collections/ensure",
            json={
                "subject_type": subject_type,
                "subject_id": subject_id,
                "description": description,
                "default_visibility": default_visibility,
                "vector_backend": vector_backend,
            },
        )
        res.raise_for_status()
        return res.json().get("data", {})

    async def cognify(
        self,
        kb_id: str,
        doc_ids: list[str] | None = None,
        model: str = "claude-sonnet-4-5-20250929",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> dict[str, Any]:
        """Trigger knowledge graph building from documents."""
        res = await self._client._http.post(
            f"/api/knowledge-engines/{kb_id}/cognify",
            json={
                "doc_ids": doc_ids,
                "model": model,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            },
        )
        res.raise_for_status()
        return res.json().get("data", {})

    async def graph_stats(self, kb_id: str) -> dict[str, Any]:
        """Get knowledge graph statistics for a knowledge base."""
        return await self._client._get(f"/api/knowledge-engines/{kb_id}/graph-stats") or {}

    async def search(
        self,
        kb_id: str,
        query: str,
        mode: str = "hybrid",
        top_k: int = 5,
        graph_depth: int = 2,
    ) -> dict[str, Any]:
        """Search across a knowledge base using vector, graph, or hybrid mode."""
        res = await self._client._http.post(
            f"/api/knowledge-engines/{kb_id}/search",
            json={"query": query, "mode": mode, "top_k": top_k, "graph_depth": graph_depth},
        )
        res.raise_for_status()
        return res.json().get("data", {})

    async def graph(self, kb_id: str, limit: int = 100) -> dict[str, Any]:
        """Get the subgraph for visualization."""
        return await self._client._get(f"/api/knowledge-engines/{kb_id}/graph?limit={limit}") or {}

    async def cognify_jobs(self, kb_id: str) -> list[dict[str, Any]]:
        """List cognify job history for a knowledge base."""
        return await self._client._get(f"/api/knowledge-engines/{kb_id}/cognify-jobs") or []


class ChatClient:
    """Persistent multi-turn chat — the platform's chat history primitive."""

    def __init__(self, client: "Abenix"):
        self._client = client

    async def create(
        self,
        *,
        agent_slug: str | None = None,
        agent_id: str | None = None,
        app_slug: str | None = None,
        title: str | None = None,
        act_as: ActingSubject | None = None,
    ) -> dict[str, Any]:
        """Create a new thread bound to an agent. Returns the thread row."""
        body: dict[str, Any] = {}
        if agent_slug:
            body["agent_slug"] = agent_slug
        if agent_id:
            body["agent_id"] = agent_id
        if app_slug:
            body["app_slug"] = app_slug
        if title:
            body["title"] = title
        res = await self._client._http.post(
            "/api/conversations",
            json=body,
            headers=self._client._subject_headers(act_as),
        )
        res.raise_for_status()
        return res.json().get("data", {})

    async def list(
        self,
        *,
        app_slug: str | None = None,
        agent_slug: str | None = None,
        archived: bool = False,
        limit: int = 50,
        offset: int = 0,
        act_as: ActingSubject | None = None,
    ) -> list[dict[str, Any]]:
        """List the acting subject's threads. Filterable by app/agent."""
        params = {"per_page": str(limit), "page": str(max(1, (offset // max(1, limit)) + 1)), "archived": str(archived).lower()}
        if app_slug:
            params["app_slug"] = app_slug
        if agent_slug:
            params["agent_slug"] = agent_slug
        res = await self._client._http.get(
            "/api/conversations",
            params=params,
            headers=self._client._subject_headers(act_as),
        )
        res.raise_for_status()
        return res.json().get("data", []) or []

    async def get(self, thread_id: str, *, act_as: ActingSubject | None = None) -> dict[str, Any]:
        """Fetch a thread + its full message history."""
        res = await self._client._http.get(
            f"/api/conversations/{thread_id}",
            headers=self._client._subject_headers(act_as),
        )
        res.raise_for_status()
        return res.json().get("data", {})

    async def send(
        self,
        thread_id: str,
        content: str,
        *,
        context: str | None = None,
        agent_slug: str | None = None,
        attachments: list | None = None,
        act_as: ActingSubject | None = None,
    ) -> dict[str, Any]:
        """Append a user turn, run the agent with full history, persist both turns.

        Returns: { thread, user_message, assistant_message }
        """
        body: dict[str, Any] = {"content": content}
        if context:
            body["context"] = context
        if agent_slug:
            body["agent_slug"] = agent_slug
        if attachments:
            body["attachments"] = attachments
        res = await self._client._http.post(
            f"/api/conversations/{thread_id}/turn",
            json=body,
            headers=self._client._subject_headers(act_as),
        )
        res.raise_for_status()
        return res.json().get("data", {})

    async def rename(
        self,
        thread_id: str,
        title: str,
        *,
        act_as: ActingSubject | None = None,
    ) -> dict[str, Any]:
        """Change a thread's title."""
        res = await self._client._http.put(
            f"/api/conversations/{thread_id}",
            json={"title": title},
            headers=self._client._subject_headers(act_as),
        )
        res.raise_for_status()
        return res.json().get("data", {})

    async def archive(
        self,
        thread_id: str,
        *,
        archived: bool = True,
        act_as: ActingSubject | None = None,
    ) -> dict[str, Any]:
        """Archive (or un-archive) a thread."""
        res = await self._client._http.put(
            f"/api/conversations/{thread_id}",
            json={"is_archived": archived},
            headers=self._client._subject_headers(act_as),
        )
        res.raise_for_status()
        return res.json().get("data", {})

    async def delete(
        self,
        thread_id: str,
        *,
        act_as: ActingSubject | None = None,
    ) -> dict[str, Any]:
        """Delete a thread (cascades to messages)."""
        res = await self._client._http.delete(
            f"/api/conversations/{thread_id}",
            headers=self._client._subject_headers(act_as),
        )
        res.raise_for_status()
        return res.json().get("data", {})


class Abenix:
    """Abenix Python SDK client."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8000",
        timeout: float = 120.0,
        act_as: ActingSubject | None = None,
    ):
        # Defensive: a secret-mount file with a stray CR/LF turns X-API-Key
        # into an illegal httpx header value and every SDK call dies. Strip
        # whitespace + CR/LF here so the caller can't accidentally take the
        # client down with a trailing newline in the env/secret.
        if isinstance(api_key, str):
            api_key = api_key.strip().rstrip("\r\n")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.default_act_as = act_as
        self.executions = ExecutionsClient(self)
        self.agents = AgentsClient(self)
        self.knowledge = KnowledgeClient(self)
        self.chat = ChatClient(self)
        self.approvals = ApprovalsClient(self)
        self.tools = ToolsClient(self)
        self.presets = PresetsClient(self)
        self.ml_models = MLModelsClient(self)
        self.decisions = DecisionsClient(self)
        self.sources = SourcesClient(self)
        self.events = EventsClient(self)
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
            timeout=self.timeout,
        )
        # Public, authenticated http client. Standalone apps that need to hit
        # platform endpoints not yet covered by a typed namespace should use
        # ``forge.http.get(path)`` / ``forge.http.post(path, json=...)`` rather
        # than constructing their own httpx.AsyncClient — the auth header,
        # base URL and timeout policy stay centralised in the SDK.
        self.http = self._http

    def _subject_headers(self, act_as: ActingSubject | None = None) -> dict[str, str]:
        """Build the X-Abenix-Subject header from an acting subject."""
        subject = act_as or self.default_act_as
        if not subject:
            return {}
        return {"X-Abenix-Subject": subject.to_header()}

    def set_act_as(self, act_as: ActingSubject | None) -> None:
        """Update the default acting subject for all subsequent calls."""
        self.default_act_as = act_as

    async def me(self) -> dict[str, Any]:
        """The user this API key acts as."""
        return await _call(self, AbenixError, "GET", "/api/me")

    async def permissions(self) -> dict[str, Any]:
        """The key's user, role and capabilities, such as approvals.sign or decisions.publish."""
        return await _call(self, AbenixError, "GET", "/api/me/permissions")

    async def execute(
        self,
        agent_slug_or_id: str,
        message: str,
        act_as: ActingSubject | None = None,
        *,
        wait: bool | str | None = None,
        **kwargs: Any,
    ) -> ExecutionResult:
        """Execute an agent and return the final result.

        The Abenix execute endpoint, since the KEDA queue-depth scaling work,
        is async-by-default — it returns ``{"execution_id": ..., "mode": "async"}``
        immediately and the agent runs on a runtime pool. Callers that want the
        synchronous result (the original SDK contract, and what every standalone
        app expects) MUST pass ``wait=True``. We do that here by default. If a
        caller has already passed ``wait`` or ``stream`` in ``kwargs`` we honour it.

        If the server still returns an async response (e.g. because the API
        version predates the ``wait`` flag, or the queue dispatcher fell back),
        we poll the execution row until it terminates so the caller never gets
        an empty ``output``. This is the industrial-strength path: a single SDK
        fix repairs every standalone app (ContractIQ insights, ResolveAI,
        MideastTourism, IndustrialIoT, …) that depends on synchronous output.
        """
        agent_id = await self._resolve_agent_id(agent_slug_or_id)

        # Derive a wait timeout from the SDK's request timeout, clamped to the
        # server-side bounds (5..1800s per ExecuteRequest schema).
        try:
            _t = float(self.timeout)
        except (TypeError, ValueError):
            _t = 180.0
        wait_timeout = max(5, min(1800, int(_t) - 5)) if _t > 10 else 180

        body: dict[str, Any] = {
            "message": message,
            "stream": False,
            "wait": True,
            "wait_timeout_seconds": wait_timeout,
        }
        # New-style wait modes: "submitted" | "until_gate" | "completed" (default).
        # Translate to wait_mode + wait/stream booleans the server understands.
        if isinstance(wait, str):
            body["wait_mode"] = wait
            body["stream"] = False
            if wait == "submitted":
                body["wait"] = False
            else:
                body["wait"] = True
        elif wait is False:
            body["wait"] = False
        # else: keep wait=True default
        body.update(kwargs)

        res = await self._http.post(
            f"/api/agents/{agent_id}/execute",
            json=body,
            headers=self._subject_headers(act_as),
        )
        res.raise_for_status()
        data = res.json().get("data", {}) or {}

        # Server signalled "paused at HITL gate" — surface immediately.
        if data.get("status") == "paused" and data.get("paused_at"):
            pa = data.get("paused_at") or {}
            return ExecutionResult(
                output="",
                execution_id=data.get("execution_id"),
                status="paused",
                paused_at=ApprovalRef(
                    approval_id=pa.get("approval_id") or "",
                    title=pa.get("title") or "",
                    payload=pa.get("payload") or {},
                    required_signoffs=pa.get("required_signoffs") or 1,
                    expires_at=pa.get("expires_at"),
                    gate_kind=pa.get("gate_kind"),
                ),
            )

        # "submitted" caller — return the execution_id without polling.
        if isinstance(wait, str) and wait == "submitted":
            return ExecutionResult(
                output="",
                execution_id=data.get("execution_id"),
                status=(data.get("status") or "running"),
            )

        # Async-mode fallback: server returned {execution_id, mode: "async"}
        # without the synchronous fields. Poll until terminal.
        if data.get("mode") == "async" or (
            not data.get("output") and not data.get("output_message")
            and data.get("execution_id")
        ):
            exec_id = data.get("execution_id")
            if exec_id:
                data = await self._poll_execution(exec_id, deadline_s=wait_timeout)

        return ExecutionResult(
            output=data.get("output", data.get("output_message", "")) or "",
            input_tokens=data.get("input_tokens", 0) or 0,
            output_tokens=data.get("output_tokens", 0) or 0,
            cost=data.get("cost", 0) or 0,
            duration_ms=data.get("duration_ms", 0) or 0,
            model=data.get("model", "") or "",
            tool_calls=data.get("tool_calls", []) or [],
            confidence_score=data.get("confidence_score"),
            execution_id=data.get("execution_id"),
            status=(data.get("status") or "completed"),
        )

    async def _poll_execution(
        self, execution_id: str, deadline_s: int = 180,
    ) -> dict[str, Any]:
        """Poll the executions endpoint until terminal. Returns the data dict.

        Used as a fallback when the execute endpoint returns async-mode and the
        caller wanted the synchronous output. Terminal statuses: completed,
        succeeded, failed, error, cancelled. We poll every 2s with a small
        warm-up so short executions return fast.
        """
        import asyncio as _asyncio
        terminal = {"completed", "succeeded", "failed", "error", "cancelled"}
        delay = 0.5
        elapsed = 0.0
        last: dict[str, Any] = {"execution_id": execution_id}
        while elapsed < deadline_s:
            try:
                r = await self._http.get(f"/api/executions/{execution_id}")
                if r.status_code == 200:
                    row = (r.json() or {}).get("data", {}) or {}
                    if row:
                        # The execution row keys its id as `id`, so reading it
                        # straight dropped execution_id and every run that came
                        # through here — including every failure — came back
                        # with nothing to trace it by.
                        row.setdefault("execution_id", row.get("id") or execution_id)
                        last = row
                    if (last.get("status") or "").lower() in terminal:
                        return last
            except httpx.HTTPError:
                pass
            await _asyncio.sleep(delay)
            elapsed += delay
            delay = min(2.0, delay * 1.5)
        return last

    async def stream(
        self, agent_slug_or_id: str, message: str,
        act_as: ActingSubject | None = None, **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream an agent execution, yielding events."""
        agent_id = await self._resolve_agent_id(agent_slug_or_id)
        async with self._http.stream(
            "POST",
            f"/api/agents/{agent_id}/execute",
            json={"message": message, "stream": True, **kwargs},
            headers=self._subject_headers(act_as),
        ) as response:
            response.raise_for_status()
            current_event = ""
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    current_event = line[7:].strip()
                elif line.startswith("data: ") and current_event:
                    data = json.loads(line[6:])
                    yield self._map_event(current_event, data)
                    current_event = ""

    async def watch(
        self, execution_id: str,
    ) -> AsyncIterator[DagSnapshot]:
        """Subscribe to the live DAG snapshot stream for a single execution."""
        async with self._http.stream(
            "GET",
            f"/api/executions/{execution_id}/watch",
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            current_event: str | None = None
            async for line in response.aiter_lines():
                if not line:
                    current_event = None
                    continue
                if line.startswith("event: "):
                    current_event = line[7:].strip()
                elif line.startswith("data: ") and current_event:
                    if current_event == "end":
                        return
                    if current_event == "snapshot":
                        try:
                            payload = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue
                        # Drop any unknown keys so the dataclass ctor doesn't
                        # trip if the server adds fields ahead of the SDK.
                        known = {
                            "execution_id", "agent_id", "agent_name", "mode",
                            "status", "started_at", "completed_at",
                            "current_node_id", "progress", "cost_so_far",
                            "tokens", "nodes", "edges",
                        }
                        yield DagSnapshot(**{k: v for k, v in payload.items() if k in known})

    async def approve(
        self, execution_id: str, gate_id: str, comment: str = ""
    ) -> None:
        """Approve a HITL gate."""
        await self._http.post(
            f"/api/executions/{execution_id}/approve",
            params={"gate_id": gate_id},
            json={"decision": "approved", "comment": comment},
        )

    async def reject(
        self, execution_id: str, gate_id: str, comment: str = ""
    ) -> None:
        """Reject a HITL gate."""
        await self._http.post(
            f"/api/executions/{execution_id}/approve",
            params={"gate_id": gate_id},
            json={"decision": "rejected", "comment": comment},
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "Abenix":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        res = await self._http.get(path, params=params or None)
        res.raise_for_status()
        return res.json().get("data")

    # UUIDs are exactly 36 chars in 8-4-4-4-12 hex layout.
    _UUID_RE = __import__("re").compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )

    async def _resolve_agent_id(self, slug_or_id: str) -> str:
        # If it's actually a UUID, pass it through; otherwise resolve from slug.
        if self._UUID_RE.match(slug_or_id):
            return slug_or_id
        # Search by name first (faster than listing all) then fall back
        # to a full paginated scan.
        found = await self._get(f"/api/agents?search={slug_or_id}&limit=5")
        for a in (found or []):
            if a.get("slug") == slug_or_id or a.get("id") == slug_or_id:
                return a["id"]
        # Full scan — covers OOB agents that search might miss
        offset = 0
        while True:
            page = await self._get(f"/api/agents?limit=100&offset={offset}")
            if not page:
                break
            for a in page:
                if a.get("slug") == slug_or_id or a.get("id") == slug_or_id:
                    return a["id"]
            if len(page) < 100:
                break
            offset += 100
        raise ValueError(f"Agent not found: {slug_or_id}")

    @staticmethod
    def _map_event(event: str, data: dict[str, Any]) -> StreamEvent:
        if event == "token":
            return StreamEvent(type="token", text=data.get("text"))
        if event == "tool_call":
            return StreamEvent(type="tool_call", name=data.get("name"), arguments=data.get("arguments"))
        if event == "tool_result":
            return StreamEvent(type="tool_result", name=data.get("name"), result=data.get("result"))
        if event == "node_start":
            return StreamEvent(type="node_start", node_id=data.get("node_id"), tool_name=data.get("tool_name"))
        if event == "node_complete":
            return StreamEvent(
                type="node_complete",
                node_id=data.get("node_id"),
                status=data.get("status"),
                duration_ms=data.get("duration_ms"),
                message=data.get("error"),
                output_preview=data.get("output_preview"),
            )
        if event == "done":
            return StreamEvent(type="done", input_tokens=data.get("input_tokens"), output_tokens=data.get("output_tokens"), cost=data.get("cost"), duration_ms=data.get("duration_ms"))
        if event == "error":
            return StreamEvent(
                type="error",
                message=data.get("message"),
                error_code=data.get("type"),
                traceback=data.get("traceback"),
                agent_id=data.get("agent_id"),
            )
        return StreamEvent(type="error", message=f"Unknown event: {event}")
