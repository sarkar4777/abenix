"""InfluxDB line protocol: measurement,tag=v field=v timestamp."""

from __future__ import annotations

from typing import Any

from app.telemetry import mapping as M
from app.telemetry.connectors.base import ConfigField, Envelope
from app.telemetry.decoders.base import DecodeError, Decoder, DecoderState, Record

_SCALE = {"ns": 1_000_000, "us": 1000, "ms": 1, "s": 0.001}


def _split(s: str, sep: str) -> list[str]:
    """Split on sep outside quotes, keeping backslash escapes."""
    out, cur, quoted, i = [], [], False, 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            cur.append(s[i : i + 2])
            i += 2
            continue
        if c == '"':
            quoted = not quoted
        if c == sep and not quoted:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


def _unescape(s: str) -> str:
    return (
        s.replace("\\,", ",")
        .replace("\\=", "=")
        .replace("\\ ", " ")
        .replace('\\"', '"')
    )


def _field(v: str) -> Any:
    if v.startswith('"') and v.endswith('"'):
        return _unescape(v[1:-1])
    low = v.lower()
    if low in ("t", "true"):
        return True
    if low in ("f", "false"):
        return False
    if v.endswith("i") or v.endswith("u"):
        return int(v[:-1])
    return float(v)


def parse_line(line: str) -> dict[str, Any]:
    parts = [p for p in _split(line.strip(), " ") if p != ""]
    if len(parts) < 2:
        raise DecodeError(f"{line[:60]!r} needs a measurement and at least one field")
    head = _split(parts[0], ",")
    meas = _unescape(head[0])
    tags = {}
    for kv in head[1:]:
        if "=" not in kv:
            raise DecodeError(f"The tag {kv!r} has no value")
        k, v = kv.split("=", 1)
        tags[_unescape(k)] = _unescape(v)
    fields = {}
    for kv in _split(parts[1], ","):
        if "=" not in kv:
            raise DecodeError(f"The field {kv!r} has no value")
        k, v = kv.split("=", 1)
        try:
            fields[_unescape(k)] = _field(v)
        except ValueError:
            raise DecodeError(
                f"The field {k} has a value that is not a number, string or boolean"
            ) from None
    try:
        ts = int(parts[2]) if len(parts) > 2 else None
    except ValueError:
        raise DecodeError(f"The timestamp {parts[2]!r} is not a whole number") from None
    return {"measurement": meas, "tags": tags, "fields": fields, "ts": ts}


class InfluxLineDecoder(Decoder):
    name = "influx_line"
    label = "Influx line protocol"
    description = (
        "Telegraf and InfluxDB lines. The measurement is the group, a tag names the asset, "
        "fields are the signals."
    )
    config_fields = (
        ConfigField(
            key="node_tag",
            label="Tag that names the asset",
            kind="string",
            required=False,
            default="host",
        ),
        ConfigField(
            key="device_tag",
            label="Tag that names the part",
            kind="string",
            required=False,
        ),
        ConfigField(
            key="precision",
            label="Timestamp precision",
            kind="select",
            required=False,
            default="ns",
            options=("ns", "us", "ms", "s"),
        ),
    )

    def decode(
        self, envelope: Envelope, state: DecoderState, mapping: dict[str, Any] | None
    ) -> list[Record]:
        cfg = state.config
        node_tag = cfg.get("node_tag") or "host"
        device_tag = cfg.get("device_tag")
        scale = _SCALE.get(cfg.get("precision") or "ns", 1_000_000)
        out: list[Record] = []
        for line in envelope.payload.decode("utf-8", "replace").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            doc = parse_line(line)
            if doc["ts"] is not None:
                doc["ts"] = int(doc["ts"] / scale)
            tags = doc["tags"]
            if node_tag in tags:
                node = f"$.tags.{node_tag}"
            else:
                node = next(iter(tags.values()), "") or "default"
            base = {
                "group": "$.measurement",
                "node": node,
                "device": (
                    f"$.tags.{device_tag}" if device_tag and device_tag in tags else ""
                ),
                "timestamp": {"path": "$.ts", "format": "epoch_ms"},
                "signals": {"root": "$.fields"},
            }
            out.extend(M.apply(doc, envelope, {**base, **(mapping or {})}))
        if not out:
            raise DecodeError("No lines in this message")
        return out
