"""Flushes a store Batch to Redis in one pipeline. Shared by the ingest and the API's DLQ replay."""

from __future__ import annotations

import json
import time
from typing import Any

from app.telemetry import keys as K
from app.telemetry.store import Batch

MERGE_LUA = """
local cur = redis.call('HGET', KEYS[1], ARGV[1])
local obj = {}
if cur then obj = cjson.decode(cur) end
local p = cjson.decode(ARGV[2])
for k, v in pairs(p) do
  if k == 'inc' then
    for kk, vv in pairs(v) do obj[kk] = (tonumber(obj[kk]) or 0) + vv end
  elseif k == 'max' then
    for kk, vv in pairs(v) do
      if (tonumber(obj[kk]) or 0) < vv then obj[kk] = vv end
    end
  else
    obj[k] = v
  end
end
redis.call('HSET', KEYS[1], ARGV[1], cjson.encode(obj))
return 1
"""


SEQ_LUA = """
local last = tonumber(redis.call('HGET', KEYS[1], 'last'))
local seq = tonumber(ARGV[1])
local delta = 0
if last == nil then
  redis.call('HSET', KEYS[1], 'last', seq)
elseif seq > last + 1 then
  delta = seq - last - 1
  redis.call('HSET', KEYS[1], 'last', seq)
elseif seq > last then
  redis.call('HSET', KEYS[1], 'last', seq)
elseif seq < last then
  local missing = tonumber(redis.call('HGET', KEYS[1], 'missing') or '0')
  if missing > 0 then delta = -1 end
elseif seq == last then
  delta = 0
end
if delta ~= 0 then redis.call('HINCRBY', KEYS[1], 'missing', delta) end
redis.call('EXPIRE', KEYS[1], 86400)
return delta
"""


class Writer:
    def __init__(self, r: Any) -> None:
        self.r = r
        self.merge = r.register_script(MERGE_LUA)
        self.seq = r.register_script(SEQ_LUA)
        self.gaps: list[tuple[str, str, str, str, int, int]] = []

    async def lookup(self, kind: str, t: str, g: str, n: str, d: str = "") -> Any:
        r = self.r
        if kind == "aliases":
            return await r.hgetall(K.aliases(t, g, n))
        if kind == "online":
            return (await r.hget(K.device(t, g, n, d), "_online")) == "1"
        if kind == "known":
            return bool(await r.hexists(K.index(t), K.index_field(g, n, d)))
        if kind == "metric_fields":
            return [
                f for f in await r.hkeys(K.device(t, g, n, d)) if f.startswith("m:")
            ]
        if kind == "bdseq":
            return await r.hget(K.device(t, g, n, ""), "_bdseq")
        if kind == "node_devices":
            return list(await r.smembers(K.node_devices(t, g, n)))
        return None

    async def flush(
        self, b: Batch, extra: list[tuple[str, tuple, dict]] | None = None
    ) -> dict[str, int]:
        """Writes the batch. Returns this second's message count per workspace, for the rate limit."""
        pipe = self.r.pipeline(transaction=False)
        for key in b.delete:
            pipe.delete(key)
        for key, fields in b.hdel:
            pipe.hdel(key, *fields)
        for key, mapping in b.hset.items():
            if mapping:
                pipe.hset(key, mapping=mapping)
        for key, member in b.sadd:
            pipe.sadd(key, member)
        for t, field, patch in b.index:
            await self.merge(
                keys=[K.index(t)],
                args=[field, json.dumps(patch, default=str)],
                client=pipe,
            )
        for key, frames in b.frames.items():
            if frames:
                pipe.lpush(key, *frames)
                pipe.ltrim(key, 0, K.FRAME_RING - 1)
        for key, (items, cap) in b.rings.items():
            if items:
                pipe.lpush(key, *items)
                pipe.ltrim(key, 0, cap - 1)
        for (t, sec), counts in b.rate.items():
            rk = K.rate(t, sec)
            for f, c in counts.items():
                pipe.hincrby(rk, f, c)
            pipe.expire(rk, 10)
        for t, counts in b.stats.items():
            for f, c in counts.items():
                if not f.startswith("_"):
                    pipe.hincrby(K.stats(t), f, c)
        slots = []
        sec = int(time.time())
        for t, cnt in b.tenant_msgs.items():
            pipe.hincrby(K.stats(t), "messages", cnt)
            qk = K.quota_count(t, sec)
            slots.append((t, len(pipe.command_stack)))
            pipe.incrby(qk, cnt)
            pipe.expire(qk, 5)
        for ch, msg in b.publish:
            pipe.publish(ch, msg)
        seq_slots = []
        for t, g, n, seq, cid in b.seqs:
            seq_slots.append((t, g, n, cid, seq, len(pipe.command_stack)))
            await self.seq(keys=[K.seq_state(t, g, n)], args=[seq], client=pipe)
        for name, args, kw in extra or ():
            getattr(pipe, name)(*args, **kw)
        res = await pipe.execute()
        self.gaps = []
        for t, g, n, cid, seq, idx in seq_slots:
            try:
                delta = int(res[idx])
            except (TypeError, ValueError, IndexError):
                continue
            if delta > 0:
                self.gaps.append((t, g, n, cid, seq, delta))
        out = {}
        for t, idx in slots:
            try:
                out[t] = int(res[idx])
            except (TypeError, ValueError, IndexError):
                pass
        return out
