"""An in-memory stand-in for the slice of redis.asyncio the telemetry code uses."""

from __future__ import annotations

import fnmatch
import json
import time
from typing import Any


def _merge(obj: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for k, v in patch.items():
        if k == "inc":
            for kk, vv in v.items():
                obj[kk] = (obj.get(kk) or 0) + vv
        elif k == "max":
            for kk, vv in v.items():
                if (obj.get(kk) or 0) < vv:
                    obj[kk] = vv
        else:
            obj[k] = v
    return obj


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.expiry: dict[str, float] = {}
        self.published: list[tuple[str, str]] = []

    # plumbing

    def _alive(self, key: str) -> bool:
        exp = self.expiry.get(key)
        if exp is not None and exp <= time.time():
            self.data.pop(key, None)
            self.expiry.pop(key, None)
        return key in self.data

    def _hash(self, key: str) -> dict[str, str]:
        if not self._alive(key):
            self.data[key] = {}
        return self.data[key]

    def pipeline(self, transaction: bool = False) -> "FakePipeline":
        return FakePipeline(self)

    def register_script(self, src: str) -> "FakeScript":
        return FakeScript(self, src)

    async def aclose(self) -> None:
        return None

    # strings

    async def get(self, key: str) -> Any:
        return self.data.get(key) if self._alive(key) else None

    async def set(
        self,
        key: str,
        value: Any,
        nx: bool = False,
        px: int | None = None,
        ex: int | None = None,
    ) -> bool:
        if nx and self._alive(key):
            return False
        self.data[key] = str(value)
        if px:
            self.expiry[key] = time.time() + px / 1000.0
        elif ex:
            self.expiry[key] = time.time() + ex
        else:
            self.expiry.pop(key, None)
        return True

    async def incr(self, key: str) -> int:
        return await self.incrby(key, 1)

    async def incrby(self, key: str, n: int) -> int:
        v = int(self.data.get(key) or 0) + int(n) if self._alive(key) else int(n)
        self.data[key] = str(v)
        return v

    async def expire(self, key: str, s: int) -> bool:
        if self._alive(key):
            self.expiry[key] = time.time() + s
            return True
        return False

    async def pexpire(self, key: str, ms: int) -> bool:
        return await self.expire(key, ms / 1000.0)

    async def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if self._alive(k):
                n += 1
            self.data.pop(k, None)
            self.expiry.pop(k, None)
        return n

    # hashes

    async def hset(
        self,
        key: str,
        field: str | None = None,
        value: Any = None,
        mapping: dict | None = None,
    ) -> int:
        h = self._hash(key)
        n = 0
        items = dict(mapping or {})
        if field is not None:
            items[field] = value
        for f, v in items.items():
            n += 0 if f in h else 1
            h[str(f)] = str(v) if not isinstance(v, str) else v
        return n

    async def hget(self, key: str, field: str) -> Any:
        return self.data.get(key, {}).get(field) if self._alive(key) else None

    async def hmget(self, key: str, *fields: str) -> list[Any]:
        h = self.data.get(key, {}) if self._alive(key) else {}
        return [h.get(f) for f in fields]

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.data.get(key, {})) if self._alive(key) else {}

    async def hkeys(self, key: str) -> list[str]:
        return list((await self.hgetall(key)).keys())

    async def hexists(self, key: str, field: str) -> bool:
        return field in (await self.hgetall(key))

    async def hlen(self, key: str) -> int:
        return len(await self.hgetall(key))

    async def hdel(self, key: str, *fields: str) -> int:
        h = self.data.get(key, {}) if self._alive(key) else {}
        n = 0
        for f in fields:
            if f in h:
                del h[f]
                n += 1
        return n

    async def hincrby(self, key: str, field: str, n: int) -> int:
        h = self._hash(key)
        h[field] = str(int(h.get(field) or 0) + int(n))
        return int(h[field])

    # sets, lists, sorted sets

    async def sadd(self, key: str, *members: str) -> int:
        if not self._alive(key):
            self.data[key] = set()
        before = len(self.data[key])
        self.data[key].update(members)
        return len(self.data[key]) - before

    async def srem(self, key: str, *members: str) -> int:
        if not self._alive(key):
            return 0
        before = len(self.data[key])
        self.data[key].difference_update(members)
        return before - len(self.data[key])

    async def smembers(self, key: str) -> set[str]:
        return set(self.data.get(key, set())) if self._alive(key) else set()

    async def lpush(self, key: str, *values: str) -> int:
        if not self._alive(key):
            self.data[key] = []
        for v in values:
            self.data[key].insert(0, v)
        return len(self.data[key])

    async def ltrim(self, key: str, start: int, stop: int) -> bool:
        if self._alive(key):
            self.data[key] = self.data[key][start : (None if stop == -1 else stop + 1)]
        return True

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        if not self._alive(key):
            return []
        return list(self.data[key][start : (None if stop == -1 else stop + 1)])

    async def zadd(self, key: str, mapping: dict[str, float], nx: bool = False) -> int:
        if not self._alive(key):
            self.data[key] = {}
        z = self.data[key]
        added = 0
        for m, sc in mapping.items():
            if nx and m in z:
                continue
            added += 0 if m in z else 1
            z[m] = float(sc)
        return added

    async def zrangebyscore(self, key: str, lo: Any, hi: Any) -> list[str]:
        z = self.data.get(key, {}) if self._alive(key) else {}
        lo = float("-inf") if lo == "-inf" else float(lo)
        hi = float("inf") if hi == "+inf" else float(hi)
        return [m for m, s in sorted(z.items(), key=lambda x: x[1]) if lo <= s <= hi]

    async def zremrangebyscore(self, key: str, lo: Any, hi: Any) -> int:
        z = self.data.get(key, {}) if self._alive(key) else {}
        gone = [m for m, s in z.items() if float(lo) <= s <= float(hi)]
        for m in gone:
            del z[m]
        return len(gone)

    async def zremrangebyrank(self, key: str, start: int, stop: int) -> int:
        z = self.data.get(key, {}) if self._alive(key) else {}
        order = [m for m, _ in sorted(z.items(), key=lambda x: x[1])]
        n = len(order)
        stop = n + stop if stop < 0 else stop
        gone = order[start : stop + 1] if stop >= start else []
        for m in gone:
            del z[m]
        return len(gone)

    async def xlen(self, key: str) -> int:
        st = self.data.get(key)
        return len(st["entries"]) if st else 0

    async def zrem(self, key: str, *members: str) -> int:
        z = self.data.get(key, {}) if self._alive(key) else {}
        return sum(1 for m in members if z.pop(m, None) is not None)

    async def zcard(self, key: str) -> int:
        return len(self.data.get(key, {})) if self._alive(key) else 0

    async def llen(self, key: str) -> int:
        return len(self.data.get(key, [])) if self._alive(key) else 0

    async def lrem(self, key: str, count: int, value: str) -> int:
        items = self.data.get(key, []) if self._alive(key) else []
        n = 0
        for i, v in enumerate(list(items)):
            if v == value and (count == 0 or n < count):
                items.remove(v)
                n += 1
        return n

    # streams, enough for one consumer group

    async def xgroup_create(
        self, key: str, group: str, id: str = "0", mkstream: bool = False
    ) -> bool:
        st = self.data.setdefault(key, {"entries": [], "groups": {}, "seq": 0})
        if group in st["groups"]:
            raise Exception("BUSYGROUP Consumer Group name already exists")
        st["groups"][group] = {"last": 0, "pending": {}}
        return True

    async def xadd(
        self,
        key: str,
        fields: dict,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        st = self.data.setdefault(key, {"entries": [], "groups": {}, "seq": 0})
        st["seq"] += 1
        eid = f"{int(time.time() * 1000)}-{st['seq']}"
        st["entries"].append((st["seq"], eid, {k: str(v) for k, v in fields.items()}))
        return eid

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict,
        count: int = 10,
        block: int | None = None,
    ) -> list:
        out = []
        for key in streams:
            st = self.data.get(key)
            if not st:
                continue
            g = st["groups"][group]
            got = [(n, eid, f) for n, eid, f in st["entries"] if n > g["last"]][:count]
            for n, eid, f in got:
                g["last"] = n
                g["pending"][eid] = consumer
            if got:
                out.append((key, [(eid, f) for _, eid, f in got]))
        if not out:
            import asyncio

            await asyncio.sleep(min((block or 0) / 1000.0, 0.01))
        return out

    async def xack(self, key: str, group: str, *ids: str) -> int:
        g = self.data[key]["groups"][group]
        return sum(1 for i in ids if g["pending"].pop(i, None) is not None)

    async def xdel(self, key: str, *ids: str) -> int:
        st = self.data[key]
        before = len(st["entries"])
        st["entries"] = [e for e in st["entries"] if e[1] not in ids]
        return before - len(st["entries"])

    async def xautoclaim(
        self,
        key: str,
        group: str,
        consumer: str,
        min_idle: int,
        start: str,
        count: int = 100,
    ) -> list:
        return ["0-0", [], []]

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 0

    async def keys(self, pattern: str) -> list[str]:
        return [
            k
            for k in list(self.data)
            if self._alive(k) and fnmatch.fnmatchcase(k, pattern)
        ]


class FakeScript:
    def __init__(self, r: FakeRedis, src: str) -> None:
        self.r = r
        self.src = src

    async def run(self, keys: list[str], args: list[Any]) -> Any:
        r = self.r
        if "'missing'" in self.src:
            h = r._hash(keys[0])
            seq = int(args[0])
            last = int(h["last"]) if "last" in h else None
            delta = 0
            if last is None or seq > last:
                delta = seq - last - 1 if last is not None and seq > last + 1 else 0
                h["last"] = str(seq)
            elif seq < last and int(h.get("missing", 0)) > 0:
                delta = -1
            if delta:
                h["missing"] = str(int(h.get("missing", 0)) + delta)
            return delta
        if "cjson" in self.src:
            h = r._hash(keys[0])
            cur = json.loads(h[args[0]]) if args[0] in h else {}
            h[args[0]] = json.dumps(_merge(cur, json.loads(args[1])))
            return 1
        held = await r.get(keys[0]) == args[0]
        if not held:
            return 0
        if "PEXPIRE" in self.src:
            return int(await r.pexpire(keys[0], int(args[1])))
        return await r.delete(keys[0])

    def __call__(self, keys: list[str], args: list[Any], client: Any = None) -> Any:
        if isinstance(client, FakePipeline):
            client.ops.append((self.run, (keys, args), {}))
            return _Done(client)
        return self.run(keys, args)


class _Done:
    def __init__(self, v: Any) -> None:
        self.v = v

    def __await__(self):
        if False:
            yield
        return self.v


class FakePipeline:
    def __init__(self, r: FakeRedis) -> None:
        self.r = r
        self.ops: list[tuple[Any, tuple, dict]] = []

    @property
    def command_stack(self) -> list:
        return self.ops

    def __getattr__(self, name: str) -> Any:
        fn = getattr(self.r, name)

        def queue(*a: Any, **kw: Any) -> "FakePipeline":
            self.ops.append((fn, a, kw))
            return self

        return queue

    async def execute(self) -> list[Any]:
        out = []
        for fn, a, kw in self.ops:
            out.append(await fn(*a, **kw))
        self.ops = []
        return out
