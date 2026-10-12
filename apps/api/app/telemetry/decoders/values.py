"""Typed values, the shape the OPC UA and Modbus connectors emit.

    content-type application/vnd.abenix.values+json
    {"ts": 1791720000000, "values": [{"name": "Boiler/Temp_C", "value": 81.2, "quality": "good",
                                      "ts": 1791720000000, "unit": "C", "node_id": "ns=2;s=Temp", "status": "Good"}]}
"""

from __future__ import annotations

import json
from typing import Any

from app.telemetry import mapping as M
from app.telemetry.connectors.base import Envelope
from app.telemetry.decoders.base import (
    QUALITIES,
    DecodeError,
    Decoder,
    DecoderState,
    Metric,
    Record,
)

CONTENT_TYPE = "application/vnd.abenix.values+json"


class ValuesDecoder(Decoder):
    name = "values"
    label = "Typed values (OPC UA, Modbus)"
    description = (
        "Named values that already carry their type, quality, unit and time, as the OPC UA "
        "and Modbus connectors send them. The mapping sets the group, asset and part and can "
        "rename a signal or change its unit."
    )
    config_fields = ()
    stateful = False

    def decode(
        self, envelope: Envelope, state: DecoderState, mapping: dict[str, Any] | None
    ) -> list[Record]:
        try:
            doc = json.loads(envelope.payload)
        except (TypeError, ValueError):
            raise DecodeError(
                "This is not the typed values JSON the OPC UA and Modbus connectors send"
            ) from None
        if not isinstance(doc, dict) or not isinstance(doc.get("values"), list):
            raise DecodeError('Typed values need a "values" list')
        m = mapping or {}
        sep = m.get("subject_separator")
        dg, dn, dd = M.default_asset(envelope.subject, sep)
        subject, headers = envelope.subject, envelope.headers
        group = (
            M.render(m["group"], doc, subject, headers, sep) if m.get("group") else dg
        )
        node = M.render(m["node"], doc, subject, headers, sep) if m.get("node") else dn
        device = (
            M.render(m["device"], doc, subject, headers, sep) if "device" in m else dd
        )
        spec = m.get("signals") or {}
        rename = spec.get("rename") or {}
        units = spec.get("units") or {}
        include = [str(x) for x in spec.get("include") or []]
        exclude = [str(x) for x in spec.get("exclude") or []]
        base_ts = M.parse_ts(doc.get("ts")) if doc.get("ts") is not None else None
        base_ts = base_ts or int(envelope.t_recv * 1000)
        metrics = []
        for v in doc["values"]:
            if not isinstance(v, dict) or not v.get("name"):
                raise DecodeError("Every typed value needs a name")
            name = str(v["name"])
            if include and not M._matches(name, include):
                continue
            if exclude and M._matches(name, exclude):
                continue
            q = str(v.get("quality") or "good").lower()
            if q not in QUALITIES:
                q = "uncertain"
            value = v.get("value")
            ts = M.parse_ts(v.get("ts")) if v.get("ts") is not None else base_ts
            metrics.append(
                Metric(
                    name=rename.get(name, name),
                    value=value,
                    type=v.get("type") or M.infer_type(value),
                    unit=units.get(name) or v.get("unit"),
                    ts=ts,
                    quality=q,
                    source_type=v.get("status"),
                )
            )
        if not metrics:
            return []
        return [
            Record(
                group=group,
                node=node,
                device=device,
                kind="data",
                metrics=metrics,
                ts=base_ts,
                seq=_seq(doc.get("seq")),
            )
        ]


def _seq(v: object) -> int | None:
    try:
        return int(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None
