"""Per-connection mapping: a decoded document into Records.

    {
      "group": "{subject.0}",             # templates: {subject}, {subject.N}, {header.X}, {$.path}, or a bare $.path
      "node": "$.machine.id",
      "device": "engine",
      "records": "$.items",               # optional, each element is its own document
      "timestamp": {"path": "$.ts", "format": "auto"},   # epoch_s, epoch_ms, epoch_ns, iso or auto
      "signals": {
        "root": "$.readings",             # where the signals live, the whole document by default
        "include": ["temp", "rpm"],       # names or paths, empty keeps all
        "exclude": ["meta"],
        "flatten": true,                  # nested objects become a/b/c
        "rename": {"temp": "Engine/Temp_C"},
        "units": {"temp": "C"},
        "types": {"rpm": "number"},
        "declared": ["temp", "rpm"]       # with strict, anything else goes to the dead-letter ring
      },
      "event": {"name": "$.type"},        # store the whole message as an event, such as order.created
      "writable": [{"signal": "Setpoint", "target": {"topic": "plant/{node}/set", "payload": "{\\"sp\\": {value}}"}}],
      "offline_after_s": 120
    }
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from app.telemetry.decoders.base import MappingError as DecodeError
from app.telemetry.decoders.base import Metric, Record

_TOKEN = re.compile(r"\{([^{}]+)\}")
_PATH_PART = re.compile(r"\.([^.\[\]]+)|\[(\d+)\]|\['([^']+)'\]|\[\"([^\"]+)\"\]")
TS_KEYS = (
    "ts",
    "timestamp",
    "time",
    "t",
    "event_time",
    "eventTime",
    "@timestamp",
    "datetime",
)
ID_KEYS = (
    "device_id",
    "vehicle_id",
    "vehicleId",
    "vin",
    "imei",
    "tracker_id",
    "unit_id",
    "serial",
    "serial_number",
    "station_id",
    "meter_id",
    "symbol",
    "ticker",
    "deviceId",
    "machine_id",
    "machineId",
    "asset_id",
    "assetId",
    "sensor_id",
    "sensorId",
    "node_id",
    "nodeId",
    "machine",
    "asset",
    "device",
    "sensor",
    "id",
)
UNIT_SUFFIX = {
    "_c": "C",
    "_degc": "C",
    "_f": "F",
    "_k": "K",
    "_rpm": "rpm",
    "_bar": "bar",
    "_kpa": "kPa",
    "_pa": "Pa",
    "_pct": "%",
    "_percent": "%",
    "_v": "V",
    "_a": "A",
    "_w": "W",
    "_kw": "kW",
    "_kwh": "kWh",
    "_m": "m",
    "_mm": "mm",
    "_kg": "kg",
    "_t": "t",
    "_s": "s",
    "_ms": "ms",
    "_hz": "Hz",
    "_rad": "rad",
    "_deg": "deg",
    "_l": "L",
    "_lph": "L/h",
    "_kmh": "km/h",
}


def path_get(doc: Any, path: str) -> Any:
    """$.a.b[0].c on dicts and lists. None when any step is missing."""
    p = path.strip()
    if p in ("$", ""):
        return doc
    if not p.startswith("$"):
        p = "$." + p
    cur = doc
    for m in _PATH_PART.finditer(p[1:]):
        key = m.group(1) or m.group(3) or m.group(4)
        if key is not None:
            if isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return None
        else:
            idx = int(m.group(2))
            if isinstance(cur, list) and -len(cur) <= idx < len(cur):
                cur = cur[idx]
            else:
                return None
        if cur is None:
            return None
    return cur


def _segments(subject: str, sep: str | None = None) -> list[str]:
    """Split on / when the subject has one (MQTT, HTTP), else on . (NATS, AMQP). sep pins it: /, . or none."""
    subject = subject or ""
    if sep in ("none", ""):
        return [subject] if subject else []
    if sep not in ("/", "."):
        sep = "/" if "/" in subject else "."
    return [x for x in subject.split(sep) if x != ""]


def segments(subject: str, mapping: dict[str, Any] | None = None) -> list[str]:
    return _segments(subject, (mapping or {}).get("subject_separator"))


def render(
    template: Any,
    doc: Any,
    subject: str,
    headers: dict[str, str],
    sep: str | None = None,
) -> str:
    if template is None:
        return ""
    t = str(template)
    if t.startswith("$"):
        v = path_get(doc, t)
        return "" if v is None else str(v)

    def sub(m: re.Match) -> str:
        key = m.group(1).strip()
        if key == "subject":
            return subject
        if key.startswith("subject."):
            segs = _segments(subject, sep)
            try:
                return segs[int(key.split(".", 1)[1])]
            except (ValueError, IndexError):
                return ""
        if key.startswith("header."):
            name = key.split(".", 1)[1].lower()
            for k, v in (headers or {}).items():
                if k.lower() == name:
                    return str(v)
            return ""
        if key.startswith("$"):
            v = path_get(doc, key)
            return "" if v is None else str(v)
        return m.group(0)

    return _TOKEN.sub(sub, t)


def default_asset(subject: str, sep: str | None = None) -> tuple[str, str, str]:
    segs = _segments(subject, sep)
    if not segs:
        return "default", "stream", ""
    if len(segs) == 1:
        return "stream", segs[0], ""
    return segs[0], segs[1], "/".join(segs[2:])


def parse_ts(value: Any, fmt: str = "auto") -> int | None:
    """Epoch milliseconds from epoch s, ms, ns or ISO 8601."""
    if value is None or value == "":
        return None
    fmt = (fmt or "auto").lower()
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value.strip())
    ):
        f = float(value)
        if fmt == "epoch_s":
            return int(f * 1000)
        if fmt == "epoch_ms":
            return int(f)
        if fmt == "epoch_ns":
            return int(f / 1_000_000)
        if fmt == "epoch_us":
            return int(f / 1000)
        if f > 1e17:
            return int(f / 1_000_000)
        if f > 1e14:
            return int(f / 1000)
        if f > 1e11:
            return int(f)
        return int(f * 1000)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise DecodeError(
            f"The time {value!r} is not ISO 8601 or epoch seconds or milliseconds"
        ) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def infer_type(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, (bytes, bytearray)):
        return "bytes"
    if isinstance(v, (dict, list)):
        return "json"
    return "string"


def coerce(v: Any, kind: str) -> Any:
    if v is None:
        return None
    try:
        if kind == "number":
            if isinstance(v, bool):
                return 1.0 if v else 0.0
            f = float(v)
            return int(f) if f.is_integer() and not isinstance(v, float) else f
        if kind == "bool":
            if isinstance(v, str):
                return v.strip().lower() in ("1", "true", "yes", "on")
            return bool(v)
        if kind == "string":
            return v if isinstance(v, str) else json.dumps(v, default=str)
        if kind == "json":
            return json.loads(v) if isinstance(v, str) else v
        if kind == "bytes":
            return v.hex() if isinstance(v, (bytes, bytearray)) else str(v)
    except (TypeError, ValueError):
        raise DecodeError(f"{v!r} cannot be read as {kind}") from None
    return v


def flatten(
    obj: Any, prefix: str = "", out: dict[str, Any] | None = None, deep: bool = True
) -> dict[str, Any]:
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}/{k}" if prefix else str(k)
            if deep and isinstance(v, dict):
                flatten(v, key, out, deep)
            else:
                out[key] = v
    elif prefix:
        out[prefix] = obj
    return out


def _norm(name: str) -> str:
    n = name.strip()
    if n.startswith("$."):
        n = n[2:]
    return n.replace(".", "/")


def _matches(name: str, patterns: list[str]) -> bool:
    for p in patterns:
        q = _norm(p)
        if name == q or name.startswith(q + "/"):
            return True
        if q.endswith("*") and name.startswith(q[:-1]):
            return True
    return False


def unit_from_name(name: str) -> str | None:
    low = name.lower()
    for suf, unit in sorted(UNIT_SUFFIX.items(), key=lambda x: -len(x[0])):
        if low.endswith(suf):
            return unit
    return None


def signals(
    doc: Any, spec: dict[str, Any], ts_key: str | None
) -> list[tuple[str, Any, str | None, str]]:
    """(name, value, unit, type) for each signal of a document."""
    root = path_get(doc, spec["root"]) if spec.get("root") else doc
    if not isinstance(root, dict):
        if root is None:
            return []
        return [("value", root, spec.get("units", {}).get("value"), infer_type(root))]
    flat = flatten(root, deep=spec.get("flatten", True) is not False)
    include = [str(x) for x in spec.get("include") or []]
    exclude = [str(x) for x in spec.get("exclude") or []]
    units = {_norm(k): v for k, v in (spec.get("units") or {}).items()}
    types = {_norm(k): v for k, v in (spec.get("types") or {}).items()}
    rename = {_norm(k): v for k, v in (spec.get("rename") or {}).items()}
    out = []
    for name, v in flat.items():
        if ts_key and name == _norm(ts_key):
            continue
        if include and not _matches(name, include):
            continue
        if exclude and _matches(name, exclude):
            continue
        kind = types.get(name) or infer_type(v)
        value = coerce(v, kind)
        unit = units.get(name)
        out.append((rename.get(name, name), value, unit, kind))
    return out


def filter_reason(doc: Any, spec: dict[str, Any] | None) -> str | None:
    """Why the filter leaves this document out, or None when it passes."""
    if not spec:
        return None
    for path in spec.get("require") or []:
        v = path_get(doc, path)
        if v is None or v == "":
            return f"Skipped by the filter: {path} is missing"
    for path, want in (spec.get("match") or {}).items():
        v = path_get(doc, path)
        allowed = want if isinstance(want, list) else [want]
        if v not in allowed:
            return f"Skipped by the filter: {path} is {v!r}, not {want!r}"
    for path, drop in (spec.get("exclude") or {}).items():
        v = path_get(doc, path)
        dropped = drop if isinstance(drop, list) else [drop]
        if v is not None and v in dropped:
            return f"Skipped by the filter: {path} is {v!r}"
    return None


def apply(
    doc: Any, envelope: Any, mapping: dict[str, Any], skips: list[str] | None = None
) -> list[Record]:
    """Records from one document under one mapping. Raises DecodeError in plain words."""
    m = mapping or {}
    subject = getattr(envelope, "subject", "") or ""
    headers = getattr(envelope, "headers", {}) or {}
    if m.get("records"):
        items = path_get(doc, m["records"])
        if not isinstance(items, list):
            raise DecodeError(f"{m['records']} is not a list in this message")
        out: list[Record] = []
        for it in items:
            sub = dict(m)
            sub.pop("records", None)
            out.extend(apply(it, envelope, sub, skips))
        return out
    if isinstance(doc, list):
        out = []
        for it in doc:
            out.extend(apply(it, envelope, m, skips))
        return out
    why = filter_reason(doc, m.get("filter"))
    if why:
        if skips is not None:
            skips.append(why)
        return []
    sep = m.get("subject_separator")
    dg, dn, dd = default_asset(subject, sep)
    group = render(m["group"], doc, subject, headers, sep) if m.get("group") else dg
    node = render(m["node"], doc, subject, headers, sep) if m.get("node") else dn
    device = render(m["device"], doc, subject, headers, sep) if "device" in m else dd
    if not group or not node:
        raise DecodeError(
            "The mapping gives no group or asset for this message. Check the group and asset templates"
        )
    ts_spec = m.get("timestamp") or {}
    ts_key = ts_spec.get("path")
    ts_raw = None
    if ts_key:
        ts_raw = path_get(doc, ts_key)
    elif isinstance(doc, dict):
        for k in TS_KEYS:
            if k in doc:
                ts_key, ts_raw = k, doc[k]
                break
    ts = parse_ts(ts_raw, ts_spec.get("format", "auto")) if ts_raw is not None else None
    if ts is None:
        ts = int(getattr(envelope, "t_recv", 0) * 1000) or None
    recs: list[Record] = []
    ev = m.get("event")
    if ev:
        ev = ev if isinstance(ev, dict) else {}
        name = (
            render(ev.get("name"), doc, subject, headers) if ev.get("name") else subject
        )
        recs.append(
            Record(
                group=group,
                node=node,
                device=device,
                kind="event",
                ts=ts,
                event=doc if isinstance(doc, (dict, list)) else {"value": doc},
                event_name=name or subject,
            )
        )
        if not m.get("signals"):
            return recs
    spec = m.get("signals") or {}
    metrics = []
    for name, value, unit, kind in signals(doc, spec, ts_key):
        metrics.append(
            Metric(
                name=name,
                value=value,
                type=kind,
                unit=unit or unit_from_name(name),
                ts=ts,
            )
        )
    if spec.get("declared") and m.get("strict"):
        allowed = {str(x) for x in spec["declared"]}
        unknown = sorted(x.name for x in metrics if x.name not in allowed)
        if unknown:
            raise DecodeError(
                "Strict mode: signals not in the mapping, " + ", ".join(unknown[:10])
            )
    if metrics:
        recs.append(
            Record(
                group=group,
                node=node,
                device=device,
                kind="data",
                metrics=metrics,
                ts=ts,
            )
        )
    return recs


def suggest(sample: Any, subject: str = "") -> dict[str, Any]:
    """A first mapping from one sample, for people to edit."""
    doc = sample
    m: dict[str, Any] = {}
    batch = (
        [x for x in sample if isinstance(x, dict)] if isinstance(sample, list) else []
    )
    if batch:
        # the most common shape, so a heartbeat or a subscribe reply does not decide the mapping
        doc = max(batch, key=lambda x: sum(1 for y in batch if set(y) == set(x)))
    elif isinstance(doc, dict):
        for k, v in doc.items():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                m["records"] = f"$.{k}"
                doc = v[0]
                break
    g, n, d = default_asset(subject)
    m["group"] = "{subject.0}" if len(_segments(subject)) > 1 else (g or "stream")
    m["node"] = "{subject.1}" if len(_segments(subject)) > 1 else (subject or "stream")
    if isinstance(doc, dict):
        for k in ID_KEYS:
            if k in doc and isinstance(doc[k], (str, int)):
                m["node"] = f"$.{k}"
                break
        if batch and str(m["node"]).startswith("$."):
            missing = [x for x in batch if path_get(x, m["node"]) in (None, "")]
            if missing and len(missing) * 2 < len(batch):
                m["filter"] = {"require": [m["node"]]}
        for k in TS_KEYS:
            if k in doc:
                v = doc[k]
                fmt = "iso"
                if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
                    f = float(v)
                    fmt = (
                        "epoch_ns"
                        if f > 1e17
                        else (
                            "epoch_us"
                            if f > 1e14
                            else "epoch_ms" if f > 1e11 else "epoch_s"
                        )
                    )
                m["timestamp"] = {"path": f"$.{k}", "format": fmt}
                break
        flat = flatten(doc)
        id_key = m["node"][2:] if str(m["node"]).startswith("$.") else None
        exclude = [k for k in flat if id_key and k == id_key]
        units = {k: u for k in flat if (u := unit_from_name(k))}
        strings = [
            k
            for k, v in flat.items()
            if isinstance(v, str) and k not in exclude and k not in TS_KEYS
        ]
        sig: dict[str, Any] = {"flatten": True}
        if exclude:
            sig["exclude"] = exclude
        if units:
            sig["units"] = units
        m["signals"] = sig
        if strings and any(
            s in ("type", "event", "event_type", "eventType") for s in strings
        ):
            key = next(
                s for s in strings if s in ("type", "event", "event_type", "eventType")
            )
            m["event"] = {"name": f"$.{key}"}
    return m
