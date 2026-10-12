"""WebSocket connector against a real local server: subscribe, receive, token refusal, reconnect, send."""

from __future__ import annotations

import asyncio
import functools
import json

import pytest

pytest.importorskip("websockets")

from websockets.asyncio.server import serve  # noqa: E402

from app.telemetry.connectors import websocket as W  # noqa: E402
from app.telemetry.connectors.base import ConnectorError, RunContext  # noqa: E402

TOKEN = "tok-123456"


def arun(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))

    return wrapper


class Ticks:
    """A tiny price feed: wants a bearer token, answers subscribe and orders, streams ticks."""

    def __init__(self):
        self.got: list[dict] = []
        self.server = None
        self.port = 0

    def check(self, connection, request):
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return connection.respond(401, "no\n")
        return None

    async def handler(self, ws):
        async def ticks():
            i = 0
            while True:
                await ws.send(
                    json.dumps({"type": "tick", "symbol": "BTC-USD", "last": 100 + i})
                )
                i += 1
                await asyncio.sleep(0.02)

        t = asyncio.create_task(ticks())
        try:
            async for raw in ws:
                msg = json.loads(raw)
                self.got.append(msg)
                await ws.send(
                    json.dumps(
                        {
                            "type": (
                                "ack" if msg.get("op") != "subscribe" else "subscribed"
                            ),
                            "received": msg,
                        }
                    )
                )
        finally:
            t.cancel()

    async def start(self, port=0):
        self.server = await serve(
            self.handler, "127.0.0.1", port, process_request=self.check
        )
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()


def cfg(port, **kw):
    return {
        "url": f"ws://127.0.0.1:{port}/ticks",
        "subscribe_message": '{"op": "subscribe", "symbols": {subjects}}',
        "subjects": ["BTC-USD"],
        "ping_interval": "5",
        **kw,
    }


def test_declares_plain_fields():
    d = W.WebSocketConnector.describe()
    assert d["transport"] == "websocket" and d["scale_mode"] == "lease"
    keys = {f["key"]: f for f in d["config_fields"]}
    assert keys["url"]["required"] and keys["auth_header"]["kind"] == "secret"
    for f in d["config_fields"]:
        assert f["label"] and f["description"], f["key"]


def test_settings():
    assert W.subscribe_message(cfg(1)) == '{"op": "subscribe", "symbols": ["BTC-USD"]}'
    assert (
        W.default_subject(
            {"url": "ws://prices.abenix-testbed.svc.cluster.local:8765/ticks"}
        )
        == "prices/ticks"
    )
    assert W.headers_of(
        {"headers": "X-App: abenix\n\n"}, {"auth_header": "Bearer a"}
    ) == [("X-App", "abenix"), ("Authorization", "Bearer a")]
    with pytest.raises(ConnectorError, match="Name: value"):
        W.headers_of({"headers": "nonsense"}, {})
    with pytest.raises(ConnectorError, match="ws:// or wss://"):
        W.url_of({"url": "http://x"})


@arun
async def test_test_samples_and_refuses_a_wrong_token():
    srv = Ticks()
    await srv.start()
    try:
        c = W.WebSocketConnector()
        ok = await c.test(cfg(srv.port), {"auth_header": f"Bearer {TOKEN}"})
        assert ok["ok"] and ok["messages"] > 0 and ok["sample"]
        assert srv.got[0] == {"op": "subscribe", "symbols": ["BTC-USD"]}
        bad = await c.test(cfg(srv.port), {"auth_header": "Bearer wrong"})
        assert not bad["ok"] and "refused the sign-in (401)" in bad["error"]
        assert "wrong" not in bad["error"]
    finally:
        await srv.stop()


@arun
async def test_run_receives_reconnects_and_stops():
    srv = Ticks()
    await srv.start()
    port = srv.port
    ctx = RunContext(
        connection_id="c1",
        tenant="t1",
        name="Prices",
        config=cfg(port),
        secrets={"auth_header": f"Bearer {TOKEN}"},
        replica="r1",
        shared=False,
    )
    task = asyncio.create_task(W.WebSocketConnector().run(ctx))
    try:
        for _ in range(200):
            if len(ctx.queue) >= 5:
                break
            await asyncio.sleep(0.01)
        assert ctx.status == "connected" and len(ctx.queue) >= 5
        assert ctx.queue[-1].subject == "127-0-0-1/ticks"
        await srv.stop()
        for _ in range(200):
            if ctx.status != "connected":
                break
            await asyncio.sleep(0.01)
        assert ctx.status in ("error", "connecting")
        before = len(ctx.queue)
        await srv.start(port)
        for _ in range(800):
            if ctx.status == "connected" and len(ctx.queue) > before:
                break
            await asyncio.sleep(0.01)
        assert ctx.status == "connected" and len(ctx.queue) > before
    finally:
        ctx.stopping.set()
        await asyncio.wait_for(task, 5)
        await srv.stop()


@arun
async def test_write_sends_and_returns_the_reply():
    srv = Ticks()
    await srv.start()
    try:
        out = await W.WebSocketConnector().write(
            cfg(srv.port),
            {"auth_header": f"Bearer {TOKEN}"},
            {"payload": '{"op": "order", "qty": 1}', "reply_contains": '"ack"'},
            None,
        )
        assert out["published"] and '"ack"' in out["reply"]
        assert {"op": "order", "qty": 1} in srv.got
    finally:
        await srv.stop()
