"""A call to an asset meant to stay warm waits for its starting runner instead of a cold Job."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from engine import code_runners as cr


class NoResponders(Exception):
    pass


class FakeNats:
    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    async def request(self, subject, data, timeout):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise NoResponders("nats: no responders available for request")
        return SimpleNamespace(data=b'{"ok": true}')


def _spec():
    return SimpleNamespace(subject="code.t.a.r", name="runner-a")


def test_waits_for_a_runner_that_comes_up(monkeypatch):
    monkeypatch.setattr(cr, "WARM_WAIT", 5.0)
    monkeypatch.setattr(cr, "keeps_warm", lambda asset: True)
    monkeypatch.setattr(cr, "_no_responders", lambda e: isinstance(e, NoResponders))
    nc = FakeNats(fail_times=2)

    async def fast_sleep(_):
        return None

    monkeypatch.setattr(cr.asyncio, "sleep", fast_sleep)
    msg = asyncio.run(cr._await_runner(nc, _spec(), b"{}", {}, 5))
    assert msg is not None and nc.calls == 3


def test_assets_not_kept_warm_go_straight_to_the_fallback(monkeypatch):
    monkeypatch.setattr(cr, "WARM_WAIT", 5.0)
    monkeypatch.setattr(cr, "keeps_warm", lambda asset: False)
    nc = FakeNats(fail_times=0)
    assert asyncio.run(cr._await_runner(nc, _spec(), b"{}", {}, 5)) is None
    assert nc.calls == 0


def test_wait_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(cr, "WARM_WAIT", 0.0)
    monkeypatch.setattr(cr, "keeps_warm", lambda asset: True)
    assert asyncio.run(cr._await_runner(FakeNats(0), _spec(), b"{}", {}, 5)) is None
