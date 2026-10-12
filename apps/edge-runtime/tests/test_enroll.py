"""Enrolment, heartbeat config and the sender, against a fake Abenix that loses its link for a while."""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from abenix_edge import app as edge_app  # noqa: E402
from abenix_edge.uplink import Platform  # noqa: E402


class FakeAbenix:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.version = 1
        self.tokens = {"etk_good"}
        self.key = "tgk_secret"
        self.down = False
        self.revoked = False
        self.heartbeats: list[dict[str, Any]] = []
        self.seen: set[str] = set()
        self.accepted: list[tuple[str, str, list[dict[str, Any]]]] = []
        self.duplicates = 0
        self.gzip_bodies = 0

    async def __call__(self, req: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("network is unreachable", request=req)
        path = req.url.path
        if path == "/api/edge/enroll":
            tok = json.loads(req.content)["token"]
            if tok not in self.tokens:
                return httpx.Response(
                    409,
                    json={
                        "error": {"message": "This enrolment token was already used."}
                    },
                )
            self.tokens.discard(tok)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "pk1",
                        "gateway_id": "yard-gw",
                        "name": "Yard gateway",
                        "key": self.key,
                        "connection_id": "c1",
                        "ingest_url": "/api/telemetry/ingest/c1",
                        "config": self.config,
                        "config_version": self.version,
                    }
                },
            )
        auth = req.headers.get("authorization")
        if self.revoked or auth != f"Bearer {self.key}":
            return httpx.Response(
                401, json={"error": {"message": "This gateway was revoked."}}
            )
        if path == "/api/edge/heartbeat":
            body = json.loads(req.content)
            self.heartbeats.append(body)
            out: dict[str, Any] = {"config_version": self.version}
            if body.get("applied_version") != self.version:
                out["config"] = self.config
            return httpx.Response(200, json={"data": out})
        if path == "/api/telemetry/ingest/c1":
            raw = req.content
            if req.headers.get("content-encoding") == "gzip":
                raw = gzip.decompress(raw)
                self.gzip_bodies += 1
            key = req.headers["idempotency-key"]
            if key in self.seen:
                self.duplicates += 1
            else:
                self.seen.add(key)
                self.accepted.append(
                    (key, req.url.params["subject"], json.loads(raw)["values"])
                )
            return httpx.Response(202, json={"data": {"accepted": True}})
        return httpx.Response(404)

    def values(self, name: str) -> list[Any]:
        return [
            v["value"]
            for _, _, vals in self.accepted
            for v in vals
            if v["name"] == name
        ]


def _gateway(
    tmp_path: Path, fake: FakeAbenix, monkeypatch: pytest.MonkeyPatch
) -> edge_app.Gateway:
    monkeypatch.setenv("ABENIX_URL", "http://abenix.test")
    monkeypatch.setenv("ABENIX_ENROLL_TOKEN", "etk_good")
    monkeypatch.setenv("ABENIX_EDGE_DATA", str(tmp_path))
    monkeypatch.setenv("PORT", "0")
    monkeypatch.setattr(
        edge_app,
        "Platform",
        lambda url, ca=None: Platform(url, ca, transport=httpx.MockTransport(fake)),
    )
    return edge_app.Gateway()


def _config(tmp_path: Path) -> dict[str, Any]:
    log = tmp_path / "plc.csv"
    log.write_text("ts,temp_c\n")
    return {
        "roles": ["collect"],
        "heartbeat_s": 0.3,
        "self_metrics_s": 0.25,
        "uplink": {"gzip": True},
        "gateway_asset": {"group": "yard"},
        "collectors": [
            {
                "id": "plc-log",
                "type": "file_tail",
                "name": "PLC log",
                "path": str(log),
                "format": "csv",
                "interval_s": 0.2,
                "from_start": True,
                "asset": {"group": "yard", "node": "press-1", "device": "plc"},
            }
        ],
    }


def test_enrol_collect_cut_and_backfill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeAbenix(_config(tmp_path))
    gw = _gateway(tmp_path, fake, monkeypatch)
    log = tmp_path / "plc.csv"

    async def scenario() -> int:
        run = asyncio.create_task(gw.run())
        for i in range(6):
            with log.open("a") as f:
                f.write(f"{1791720000000 + i * 1000},{20 + i}\n")
            await asyncio.sleep(0.25)
        fake.down = True
        for i in range(6, 14):
            with log.open("a") as f:
                f.write(f"{1791720000000 + i * 1000},{20 + i}\n")
            await asyncio.sleep(0.25)
        backlog = gw.buffer.stats()["depth"]
        fake.down = False
        await asyncio.sleep(3.0)
        gw.stop.set()
        await asyncio.wait_for(run, 15)
        return backlog

    backlog = asyncio.run(scenario())
    assert backlog > 0
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["gateway_id"] == "yard-gw" and state["key"] == "tgk_secret"
    if os.name != "nt":
        assert oct((tmp_path / "state.json").stat().st_mode & 0o777) == "0o600"
    temps = fake.values("temp_c")
    assert temps == [20 + i for i in range(14)], "every reading arrives once, in order"
    seq = fake.values("Edge/Seq")
    assert seq == list(
        range(1, len(seq) + 1)
    ), "the gateway's sequence has no gap and no repeat"
    assert {s for _, s, _ in fake.accepted} == {
        "yard/press-1/plc",
        "yard/yard-gw/gateway",
    }
    assert fake.gzip_bodies == len(fake.accepted)
    hb = fake.heartbeats[-1]
    assert hb["gateway_id"] == "yard-gw" and hb["applied_version"] == 1
    assert hb["collectors"][0]["status"] == "running"
    assert hb["buffer"]["sent"] >= len(temps)
    assert any(h["uplink"]["status"] == "online" for h in fake.heartbeats)


def test_config_change_on_heartbeat_and_revoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _config(tmp_path)
    fake = FakeAbenix(cfg)
    gw = _gateway(tmp_path, fake, monkeypatch)

    async def scenario() -> None:
        run = asyncio.create_task(gw.run())
        await asyncio.sleep(1.0)
        assert set(gw.manager.running) == {"plc-log"}
        fake.config = {
            **cfg,
            "collectors": cfg["collectors"]
            + [
                {
                    "id": "bad",
                    "type": "modbus",
                    "name": "Bad map",
                    "registers": "x, nowhere, 1",
                }
            ],
        }
        fake.version = 2
        await asyncio.sleep(1.0)
        assert gw.config_version == 2
        assert gw.manager.failed["bad"]["error"].startswith("x: the table must be")
        fake.revoked = True
        await asyncio.sleep(1.5)
        gw.stop.set()
        await asyncio.wait_for(run, 15)

    asyncio.run(scenario())
    assert "revoked" in (gw.problem or "").lower()
    assert gw.manager.running == {}


def test_used_token_is_refused_in_plain_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeAbenix(_config(tmp_path))
    fake.tokens = set()
    gw = _gateway(tmp_path, fake, monkeypatch)

    async def scenario() -> None:
        run = asyncio.create_task(gw.run())
        await asyncio.sleep(0.5)
        assert "already used" in gw.problem
        gw.stop.set()
        await asyncio.wait_for(run, 5)

    asyncio.run(scenario())
    assert not (tmp_path / "state.json").exists()


def test_not_enrolled_without_a_token_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeAbenix(_config(tmp_path))
    gw = _gateway(tmp_path, fake, monkeypatch)
    gw.token = ""
    assert asyncio.run(gw.run()) == 2


def test_a_new_install_command_enrols_again_and_keeps_the_buffer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeAbenix(_config(tmp_path))
    gw = _gateway(tmp_path, fake, monkeypatch)

    async def once(g: edge_app.Gateway, secs: float) -> None:
        run = asyncio.create_task(g.run())
        await asyncio.sleep(secs)
        g.stop.set()
        await asyncio.wait_for(run, 15)

    asyncio.run(once(gw, 1.0))
    first = json.loads((tmp_path / "state.json").read_text())
    # same token again: no second enrolment, the used token would be refused
    asyncio.run(once(_gateway(tmp_path, fake, monkeypatch), 0.8))
    assert json.loads((tmp_path / "state.json").read_text())["key"] == first["key"]
    fake.tokens = {"etk_new"}
    fake.key = "tgk_rotated"
    monkeypatch.setenv("ABENIX_ENROLL_TOKEN", "etk_new")
    g3 = edge_app.Gateway()
    asyncio.run(once(g3, 1.0))
    after = json.loads((tmp_path / "state.json").read_text())
    assert after["key"] == "tgk_rotated" and after["gateway_id"] == "yard-gw"
    assert g3.problem is None
