"""Minimal MCP server for Abenix UAT.

Exposes one tool — `uat_echo` — that simply echoes its input. Speaks the
streamable-HTTP MCP transport (the only transport Abenix supports
via the /api/mcp/connections endpoint).

The implementation is intentionally hand-rolled (no `mcp` SDK dep) so
the container image stays tiny and there is no npm/pip toolchain race
during pod startup.

Run::

    uvicorn server:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse


app = FastAPI(title="Abenix UAT MCP Demo Server")


# A single trivial tool. Real MCP servers expose many; one is plenty
# for our discovery + invocation tests.
TOOLS = [
    {
        "name": "uat_echo",
        "description": "Echo the input string back, prefixed with 'UAT '.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to echo."}},
            "required": ["text"],
        },
    },
]


def _jsonrpc_result(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _handle(method: str, req_id: Any, params: dict | None) -> dict:
    if method == "initialize":
        return _jsonrpc_result(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "abenix-uat-mcp", "version": "0.1.0"},
        })
    if method == "tools/list":
        return _jsonrpc_result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        params = params or {}
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        if name == "uat_echo":
            text = args.get("text", "")
            return _jsonrpc_result(req_id, {
                "content": [{"type": "text", "text": f"UAT {text}"}],
                "isError": False,
            })
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"unknown tool {name}"}}
    if method == "notifications/initialized":
        # Notifications carry no result, but some clients still parse the
        # response body as JSON — return an empty JSON-RPC envelope to keep
        # them happy.
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> Response:
    """JSON-RPC entry point — speaks the streamable-HTTP MCP transport.

    Abenix's MCP connector POSTs JSON-RPC requests. We accept either
    `application/json` (synchronous response) or `text/event-stream`
    (streamable). For UAT we return synchronous JSON which is well
    within MCP spec.
    """
    body = await request.json()
    accept = request.headers.get("accept", "")

    # Single request OR batch — always return a JSON body so MCP
    # clients that auto-parse responses don't blow up on notifications.
    if isinstance(body, list):
        responses = [_handle(r.get("method"), r.get("id"), r.get("params")) for r in body]
        payload: Any = responses
    else:
        method = body.get("method")
        req_id = body.get("id")
        params = body.get("params")
        payload = _handle(method, req_id, params)

    if "text/event-stream" in accept:
        async def gen():
            yield f"event: message\ndata: {json.dumps(payload)}\n\n".encode()
        headers = {"Mcp-Session-Id": uuid4().hex}
        return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)
    return JSONResponse(payload, headers={"Mcp-Session-Id": uuid4().hex})


@app.get("/mcp")
async def mcp_get() -> Response:
    # Some clients open SSE first to receive server-initiated events.
    # Demo server doesn't push, so we just hold the stream open briefly
    # and return — actual JSON-RPC traffic comes via POST.
    async def gen():
        yield b": ready\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
