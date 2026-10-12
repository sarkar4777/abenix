import asyncio

import tool_stream_consumer as tsc


class FakeRedis:
    def __init__(self, ids, last_delivered, pending):
        self.ids = list(ids)
        self.last = last_delivered
        self.pending = pending
        self.deleted = []

    async def xinfo_groups(self, stream):
        return [{"name": tsc.TOOL_CONSUMER_GROUP, "last-delivered-id": self.last}]

    async def xpending(self, stream, group):
        if not self.pending:
            return {"pending": 0, "min": None, "max": None, "consumers": []}
        return {"pending": len(self.pending), "min": min(self.pending)}

    async def xtrim(self, stream, minid, approximate=True):
        assert approximate is False

        def key(i):
            ms, seq = i.split("-")
            return int(ms), int(seq)

        keep = [i for i in self.ids if key(i) >= key(minid)]
        removed = len(self.ids) - len(keep)
        self.ids = keep
        return removed

    async def xack(self, *a):
        return 1

    async def xdel(self, stream, msg_id):
        self.deleted.append(msg_id)
        self.ids.remove(msg_id)
        return 1


def test_trim_drops_everything_acked():
    r = FakeRedis(["1-0", "2-0", "3-0"], "3-0", [])
    asyncio.run(tsc._trim_done(r))
    assert r.ids == []


def test_trim_keeps_pending_jobs():
    r = FakeRedis(["1-0", "2-0", "3-0", "4-0"], "4-0", ["3-0"])
    asyncio.run(tsc._trim_done(r))
    assert r.ids == ["3-0", "4-0"]


def test_trim_leaves_undelivered_jobs():
    r = FakeRedis(["1-0", "2-0", "3-0"], b"1-0", [])
    asyncio.run(tsc._trim_done(r))
    assert r.ids == ["2-0", "3-0"]


def test_trim_skips_when_other_groups_read_the_stream():
    r = FakeRedis(["1-0"], "1-0", [])

    async def two(stream):
        return [{"last-delivered-id": "1-0"}, {"last-delivered-id": "0-0"}]

    r.xinfo_groups = two
    asyncio.run(tsc._trim_done(r))
    assert r.ids == ["1-0"]
