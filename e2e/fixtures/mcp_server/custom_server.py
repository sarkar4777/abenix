"""A custom MCP server with several tools, for exercising the MCP config UI.

The single-tool server next door proves a connection can be made. This one
proves the parts that only show up once a server has more than one tool. It
exposes three, each shaped differently on purpose.

  inventory_lookup   required + optional args, returns structured data
  shipping_quote     numeric args and arithmetic, so a wrong argument shows
  order_status       an argument that can legitimately not be found

Between them they cover a tool returning a normal result, a tool returning a
known-absent result, and a tool returning an error, which is the distinction
an agent has to get right.

Run::

    uvicorn custom_server:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Abenix Custom MCP Demo Server")

# Deliberately odd numbers. If an agent invents an answer rather than calling
# the tool, the invention will not match these.
CATALOGUE = {
    "SKU-4417": {"name": "Hydraulic seal kit", "on_hand": 63, "warehouse": "Rotterdam"},
    "SKU-9002": {"name": "Bearing assembly 40mm", "on_hand": 7, "warehouse": "Singapore"},
    "SKU-1183": {"name": "Pressure sensor, 0-16 bar", "on_hand": 0, "warehouse": "Houston"},
}

ORDERS = {
    "ORD-88213": {"status": "in_transit", "carrier": "MSC", "eta_days": 11},
    "ORD-88214": {"status": "held_at_customs", "carrier": "Maersk", "eta_days": 26},
}

TOOLS = [
    {
        "name": "inventory_lookup",
        "description": (
            "Look up stock for a SKU. Returns the item name, units on hand and "
            "the warehouse holding them."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string", "description": "Stock keeping unit, e.g. SKU-4417."},
                "include_warehouse": {
                    "type": "boolean",
                    "description": "Include the warehouse name. Defaults to true.",
                },
            },
            "required": ["sku"],
        },
    },
    {
        "name": "shipping_quote",
        "description": (
            "Quote a shipment in USD from weight and distance. The rate is 4.25 "
            "per kg plus 0.85 per km, with a 95 minimum."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "weight_kg": {"type": "number", "description": "Gross weight in kilograms."},
                "distance_km": {"type": "number", "description": "Distance in kilometres."},
            },
            "required": ["weight_kg", "distance_km"],
        },
    },
    {
        "name": "order_status",
        "description": "Current status of an order by reference, e.g. ORD-88213.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "order_ref": {"type": "string", "description": "Order reference."},
            },
            "required": ["order_ref"],
        },
    },
]


def _text(payload: Any, is_error: bool = False) -> dict:
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return {"content": [{"type": "text", "text": body}], "isError": is_error}


def _call(name: str, args: dict) -> dict:
    if name == "inventory_lookup":
        sku = str(args.get("sku", "")).strip().upper()
        if not sku:
            return _text("sku is required", is_error=True)
        row = CATALOGUE.get(sku)
        if row is None:
            # Not an error. The tool worked and the answer is that there is no
            # such SKU, which an agent should report rather than guess around.
            return _text({"sku": sku, "found": False})
        out = {"sku": sku, "found": True, "name": row["name"], "on_hand": row["on_hand"]}
        if args.get("include_warehouse", True):
            out["warehouse"] = row["warehouse"]
        return _text(out)

    if name == "shipping_quote":
        try:
            weight = float(args["weight_kg"])
            distance = float(args["distance_km"])
        except (KeyError, TypeError, ValueError):
            return _text("weight_kg and distance_km must both be numbers", is_error=True)
        price = max(95.0, round(weight * 4.25 + distance * 0.85, 2))
        return _text({
            "weight_kg": weight,
            "distance_km": distance,
            "quote_usd": price,
            "rate": "4.25/kg + 0.85/km, minimum 95",
        })

    if name == "order_status":
        ref = str(args.get("order_ref", "")).strip().upper()
        row = ORDERS.get(ref)
        if row is None:
            return _text({"order_ref": ref, "found": False})
        return _text({"order_ref": ref, "found": True, **row})

    return _text(f"unknown tool {name}", is_error=True)


def _result(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _handle(method: str, req_id: Any, params: dict | None) -> dict:
    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "abenix-custom-mcp", "version": "1.0.0"},
        })
    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        params = params or {}
        return _result(req_id, _call(params.get("name", ""), params.get("arguments") or {}))
    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "tools": [t["name"] for t in TOOLS]}


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> Response:
    body = await request.json()
    accept = request.headers.get("accept", "")
    if isinstance(body, list):
        payload: Any = [_handle(r.get("method"), r.get("id"), r.get("params")) for r in body]
    else:
        payload = _handle(body.get("method"), body.get("id"), body.get("params"))
    if "text/event-stream" in accept:
        async def gen():
            yield f"event: message\ndata: {json.dumps(payload)}\n\n".encode()
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Mcp-Session-Id": uuid4().hex})
    return JSONResponse(payload, headers={"Mcp-Session-Id": uuid4().hex})


@app.get("/mcp")
async def mcp_get() -> Response:
    async def gen():
        yield b": ready\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
