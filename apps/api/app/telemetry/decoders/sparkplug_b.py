"""Sparkplug B, with its session rules: seq, bdSeq, aliases and rebirth.

Stateful per connection. A node birth resets the node's alias table, data
names metrics by alias, a jump in seq asks the node to be born again, and the
will of an older session (a stale bdSeq) is ignored.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from app.telemetry import sparkplug as sp
from app.telemetry.connectors.base import ConfigField, Envelope
from app.telemetry.decoders.base import (
    DecodeError,
    Decoder,
    DecoderState,
    Metric,
    Record,
)

REBIRTH_EVERY_S = 5.0
_KIND_DTYPE = {
    "boolean_value": 11,
    "double_value": 10,
    "float_value": 9,
    "long_value": 4,
    "int_value": 3,
    "string_value": 12,
}


@dataclass
class _Node:
    expected: int | None = None
    bdseq: int | None = None
    last_rebirth: float = 0.0
    gaps: int = 0


def _type(dtype: int, value: Any) -> str:
    if dtype == 11 or isinstance(value, bool):
        return "bool"
    if dtype in sp.NUMERIC_TYPES or isinstance(value, (int, float)):
        return "number"
    if dtype in (17, 18):
        return "bytes"
    if isinstance(value, (dict, list)):
        return "json"
    return "string"


class SparkplugDecoder(Decoder):
    name = "sparkplug_b"
    label = "Sparkplug B"
    description = (
        "Eclipse Sparkplug B 3.0 over MQTT topics spBv1.0/{group}/{type}/{node}/{device}. "
        "Births, deaths, data and host state, with seq, bdSeq, aliases and rebirth requests."
    )
    config_fields = (
        ConfigField(
            key="rebirth_on_gap",
            label="Ask for a rebirth on a seq gap",
            kind="bool",
            required=False,
            description="Sends NCMD Node Control/Rebirth, at most once every 5 seconds per node.",
            default="true",
        ),
    )
    stateful = True
    uses_mapping = False

    # session helpers

    def _nodes(self, state: DecoderState) -> dict[tuple[str, str], _Node]:
        return state.data.setdefault("nodes", {})

    def _online(
        self, state: DecoderState
    ) -> dict[tuple[str, str, str], tuple[bool, float]]:
        return state.data.setdefault("online", {})

    async def _is_online(
        self, state: DecoderState, t: str, g: str, n: str, d: str, fresh: bool = False
    ) -> bool:
        cache = self._online(state)
        hit = cache.get((g, n, d))
        now = time.monotonic()
        if hit is not None and not fresh and (hit[0] or now - hit[1] < 2.0):
            return hit[0]
        online = bool(state.lookup and await state.lookup("online", t, g, n, d))
        cache[(g, n, d)] = (online, now)
        return online

    async def _aliases(
        self, state: DecoderState, t: str, g: str, n: str
    ) -> dict[int, tuple[str, str, int]]:
        amaps = state.data.setdefault("aliases", {})
        m = amaps.get((g, n))
        if m is None:
            raw = (
                await state.lookup("aliases", t, g, n) if state.lookup else None
            ) or {}
            m = {}
            for k, v in raw.items():
                try:
                    dev, name, dtype = json.loads(v)
                    m[int(k)] = (dev, name, int(dtype))
                except (TypeError, ValueError):
                    continue
            amaps[(g, n)] = m
        return m

    def _stat(self, state: DecoderState, key: str, n: int = 1) -> None:
        state.stats[key] = state.stats.get(key, 0) + n

    def _rebirth(self, state: DecoderState, ns: _Node, g: str, n: str) -> None:
        if str(state.config.get("rebirth_on_gap", "true")).lower() in (
            "false",
            "0",
            "no",
        ):
            return
        now = time.monotonic()
        if now - ns.last_rebirth < REBIRTH_EVERY_S:
            return
        ns.last_rebirth = now
        state.outbox.append((sp.command_topic(g, n), sp.rebirth_payload()))
        self._stat(state, "rebirths")

    def _metric(self, m: Any, name: str, dtype: int, ts: int) -> Metric:
        value = sp.metric_value(m, dtype)
        if not dtype:
            dtype = _KIND_DTYPE.get(m.WhichOneof("value") or "", 0)
        if isinstance(value, bytes):
            value = value.hex()
        return Metric(
            name=name,
            value=value,
            type=_type(dtype, value),
            ts=int(m.timestamp or ts),
            quality=sp.quality(m),
            source_type=sp.TYPE_NAMES.get(dtype, "Unknown"),
            historical=bool(m.is_historical),
        )

    # decode

    async def decode(
        self, envelope: Envelope, state: DecoderState, mapping: dict[str, Any] | None
    ) -> list[Record]:
        tp = sp.parse_topic(envelope.subject)
        if tp is None:
            raise DecodeError(
                f"{envelope.subject} is not a Sparkplug B topic, they look like spBv1.0/group/NDATA/node"
            )
        t = envelope.tenant
        if tp.is_state:
            return [
                Record(
                    group="",
                    node="",
                    kind="state",
                    meta={
                        "host": tp.host_id,
                        "state": envelope.payload.decode("utf-8", "replace")[:2000],
                    },
                )
            ]
        if tp.message_type in ("NCMD", "DCMD"):
            return []
        try:
            p = sp.decode(envelope.payload)
        except Exception:  # noqa: BLE001
            raise DecodeError(
                "The payload is not a Sparkplug B protobuf message"
            ) from None
        mt, g, n, d = tp.message_type, tp.group, tp.node, tp.device
        ts = int(p.timestamp) if p.timestamp else int(envelope.t_recv * 1000)
        ns = self._nodes(state).setdefault((g, n), _Node())
        meta: dict[str, Any] = {}
        seq = int(p.seq) if p.HasField("seq") else None
        if mt != "NDEATH" and seq is not None and not state.shared:
            gap = self._seq(state, ns, mt, seq, g, n)
            if gap:
                meta["seq_gap"] = gap
        if mt in ("NBIRTH", "DBIRTH"):
            rec = await self._birth(
                state, ns, p, t, g, n, d if mt == "DBIRTH" else "", ts
            )
        elif mt in ("NDATA", "DDATA"):
            rec = await self._data(state, ns, p, t, g, n, d, ts)
        elif mt == "DDEATH":
            self._online(state)[(g, n, d)] = (False, time.monotonic())
            rec = Record(group=g, node=n, device=d, kind="death", ts=ts)
        else:
            rec = await self._node_death(state, ns, p, t, g, n, ts)
        if rec is None:
            if meta:
                return [
                    Record(
                        group=g,
                        node=n,
                        device="",
                        kind="data",
                        ts=ts,
                        seq=seq,
                        meta=meta,
                    )
                ]
            return []
        rec.seq = seq
        rec.meta.update(meta)
        return [rec]

    def _seq(
        self, state: DecoderState, ns: _Node, mt: str, seq: int, g: str, n: str
    ) -> dict[str, Any] | None:
        if mt == "NBIRTH" or ns.expected is None:
            ns.expected = (seq + 1) % 256
            return None
        gap = None
        if seq != ns.expected:
            ns.gaps += 1
            gap = {"expected": ns.expected, "received": seq, "seq_gaps": ns.gaps}
            self._rebirth(state, ns, g, n)
        ns.expected = (seq + 1) % 256
        return gap

    async def _birth(
        self,
        state: DecoderState,
        ns: _Node,
        p: Any,
        t: str,
        g: str,
        n: str,
        d: str,
        ts: int,
    ) -> Record:
        amap = await self._aliases(state, t, g, n)
        meta: dict[str, Any] = {"replace_metrics": True, "aliases": {}}
        if not d:
            amap.clear()
            meta["reset_aliases"] = True
            for m in p.metrics:
                if m.name == sp.BDSEQ_METRIC:
                    ns.bdseq = int(sp.metric_value(m, 4) or 0)
            if ns.bdseq is not None:
                meta["bdseq"] = ns.bdseq
        types = state.data.setdefault("types", {}).setdefault((g, n, d), {})
        if d:
            declared = {m.name for m in p.metrics if m.name}
            gone = [
                a
                for a, (dev, name, _) in amap.items()
                if dev == d and name not in declared
            ]
            for a in gone:
                amap.pop(a, None)
            if gone:
                meta["drop_aliases"] = sorted(gone)
        types.clear()
        metrics = []
        for m in p.metrics:
            if not m.name:
                continue
            dtype = m.datatype or 0
            types[m.name] = dtype
            if m.HasField("alias"):
                amap[int(m.alias)] = (d, m.name, dtype)
                meta["aliases"][str(int(m.alias))] = [d, m.name, dtype]
            metrics.append(self._metric(m, m.name, dtype, ts))
        self._online(state)[(g, n, d)] = (True, time.monotonic())
        return Record(
            group=g, node=n, device=d, kind="birth", metrics=metrics, ts=ts, meta=meta
        )

    async def _data(
        self,
        state: DecoderState,
        ns: _Node,
        p: Any,
        t: str,
        g: str,
        n: str,
        d: str,
        ts: int,
    ) -> Record | None:
        if not await self._is_online(state, t, g, n, d):
            # data before any birth we know of, ask the node to say who it is
            self._stat(state, "data_before_birth")
            self._rebirth(state, ns, g, n)
            if not (state.lookup and await state.lookup("known", t, g, n, d)):
                return None
        amap = None
        types = state.data.setdefault("types", {}).get((g, n, d)) or {}
        metrics = []
        for m in p.metrics:
            name = m.name
            dtype = m.datatype or 0
            if not name and m.HasField("alias"):
                if amap is None:
                    amap = await self._aliases(state, t, g, n)
                hit = amap.get(int(m.alias))
                if hit is None:
                    self._stat(state, "unknown_alias")
                    self._rebirth(state, ns, g, n)
                    continue
                _dev, name, btype = hit
                dtype = dtype or btype
            if not name:
                continue
            metrics.append(self._metric(m, name, dtype or types.get(name, 0), ts))
        return Record(
            group=g,
            node=n,
            device=d,
            kind="data",
            metrics=metrics,
            ts=ts,
            meta={"session": True},
        )

    async def _node_death(
        self, state: DecoderState, ns: _Node, p: Any, t: str, g: str, n: str, ts: int
    ) -> Record | None:
        bdseq = None
        for m in p.metrics:
            if m.name == sp.BDSEQ_METRIC:
                bdseq = int(sp.metric_value(m, 4) or 0)
        current = ns.bdseq
        if current is None and state.lookup:
            stored = await state.lookup("bdseq", t, g, n)
            current = int(stored) if stored not in (None, "") else None
        if bdseq is not None and current is not None and bdseq != current:
            # the will of an older session, the node has been born again since
            self._stat(state, "stale_death")
            return None
        ns.expected = None
        for key in [k for k in self._online(state) if k[0] == g and k[1] == n]:
            self._online(state)[key] = (False, time.monotonic())
        return Record(
            group=g, node=n, device="", kind="death", ts=ts, meta={"cascade": True}
        )
