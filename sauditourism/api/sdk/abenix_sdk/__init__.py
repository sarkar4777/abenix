"""Abenix Python SDK — execute and monitor AI agents from any Python app."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx


@dataclass
class ActingSubject:
    """RBAC delegation: act on behalf of an end user."""
    subject_type: str           # e.g., "example_app", "external", "user"
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
class ExecutionResult:
    output: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    duration_ms: int = 0
    model: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    confidence_score: float | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)  # Per-agent/node errors


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


class AgentsClient:
    def __init__(self, client: "Abenix"):
        self._client = client

    async def list(self) -> list[dict[str, Any]]:
        return await self._client._get("/api/agents") or []

    async def get(self, agent_id: str) -> dict[str, Any]:
        return await self._client._get(f"/api/agents/{agent_id}")


class KnowledgeClient:
    """Knowledge Engine client — Cognify, graph queries, and hybrid search."""

    def __init__(self, client: "Abenix"):
        self._client = client

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
        if agent_slug: body["agent_slug"] = agent_slug
        if agent_id:   body["agent_id"] = agent_id
        if app_slug:   body["app_slug"] = app_slug
        if title:      body["title"] = title
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
        if app_slug:   params["app_slug"] = app_slug
        if agent_slug: params["agent_slug"] = agent_slug
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
        if context:      body["context"] = context
        if agent_slug:   body["agent_slug"] = agent_slug
        if attachments:  body["attachments"] = attachments
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
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.default_act_as = act_as
        self.executions = ExecutionsClient(self)
        self.agents = AgentsClient(self)
        self.knowledge = KnowledgeClient(self)
        self.chat = ChatClient(self)
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
            timeout=self.timeout,
        )

    def _subject_headers(self, act_as: ActingSubject | None = None) -> dict[str, str]:
        """Build the X-Abenix-Subject header from an acting subject."""
        subject = act_as or self.default_act_as
        if not subject:
            return {}
        return {"X-Abenix-Subject": subject.to_header()}

    def set_act_as(self, act_as: ActingSubject | None) -> None:
        """Update the default acting subject for all subsequent calls."""
        self.default_act_as = act_as

    async def execute(
        self, agent_slug_or_id: str, message: str,
        act_as: ActingSubject | None = None, **kwargs: Any,
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
        fix repairs every standalone app (the example app insights, ResolveAI,
        SauditTourism, IndustrialIoT, …) that depends on synchronous output.
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
        # Caller-supplied kwargs win (e.g. context, explicit wait=False).
        body.update(kwargs)

        res = await self._http.post(
            f"/api/agents/{agent_id}/execute",
            json=body,
            headers=self._subject_headers(act_as),
        )
        res.raise_for_status()
        data = res.json().get("data", {}) or {}

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
                    last = (r.json() or {}).get("data", {}) or last
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

    async def _get(self, path: str) -> Any:
        res = await self._http.get(path)
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
