"""The asset registry: names, types, tags, teams, locations and free fields per (group, node, device).

A key the stream has sent but nobody has named is "unregistered". The list merges
the live keys from the ingest's device index with the registered rows.
"""

from __future__ import annotations

import csv
import io
import math
import re
from typing import Any

ASSET_TYPES = ("vehicle", "machine", "sensor", "device", "system")
TYPE_HINTS = {
    "vehicle": "Trucks, vans, cars and mobile plant on the road",
    "machine": "Excavators, cranes, presses, pumps and other equipment",
    "sensor": "A single sensor or a small sensor node",
    "device": "A connected product, gateway or controller",
    "system": "A software system or service that streams events",
}
FIXED_FIELDS = ("vin", "plate", "serial", "model")
CSV_COLUMNS = (
    "group",
    "node",
    "device",
    "name",
    "type",
    "tags",
    "team",
    "lat",
    "lon",
    "x",
    "y",
    *FIXED_FIELDS,
)
CSV_MAX_ROWS = 5000
CSV_MAX_BYTES = 2_000_000
MAX_TAGS = 20
MAX_FIELDS = 30
_TAG = re.compile(r"^[a-z0-9 _.\-:/]{1,40}$")
_FIELD = re.compile(r"^[a-z0-9_]{1,40}$")
_KEYPART = re.compile(r"^[^/#+\s][^/#+]{0,254}$")


class AssetInvalid(ValueError):
    def __init__(self, fields: dict[str, str]) -> None:
        super().__init__(next(iter(fields.values())) if fields else "Invalid asset")
        self.fields = fields


def _num(v: Any) -> float | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def clean_tags(v: Any, err: dict[str, str]) -> list[str]:
    if v in (None, ""):
        return []
    if isinstance(v, str):
        v = re.split(r"[;|,]", v)
    if not isinstance(v, list):
        err["tags"] = "Tags are a list of short words."
        return []
    out: list[str] = []
    for t in v:
        s = str(t or "").strip().lower()
        if not s:
            continue
        if not _TAG.match(s):
            err["tags"] = (
                f"The tag {str(t)[:40]!r} has characters a tag cannot use. Use letters, digits, spaces and _ . - : /, up to 40 characters."
            )
            continue
        if s not in out:
            out.append(s)
    if len(out) > MAX_TAGS:
        err["tags"] = f"An asset can have at most {MAX_TAGS} tags."
    return out[:MAX_TAGS]


def clean_location(v: Any, err: dict[str, str]) -> dict[str, Any] | None:
    if v in (None, "", {}):
        return None
    if not isinstance(v, dict):
        err["location"] = "Give a location as latitude and longitude, or site x and y."
        return None
    label = str(v.get("label") or "").strip()[:80]
    has_gps = any(v.get(k) not in (None, "") for k in ("lat", "lon"))
    has_site = any(v.get(k) not in (None, "") for k in ("x", "y"))
    if has_gps and has_site:
        err["location"] = "Use latitude and longitude, or site x and y, not both."
        return None
    if has_gps:
        lat, lon = _num(v.get("lat")), _num(v.get("lon"))
        if lat is None or not -90 <= lat <= 90:
            err["location.lat"] = "Latitude is a number from -90 to 90."
        if lon is None or not -180 <= lon <= 180:
            err["location.lon"] = "Longitude is a number from -180 to 180."
        return {"lat": lat, "lon": lon, **({"label": label} if label else {})}
    if has_site:
        x, y = _num(v.get("x")), _num(v.get("y"))
        if x is None:
            err["location.x"] = "Site x is a number, in metres from the site origin."
        if y is None:
            err["location.y"] = "Site y is a number, in metres from the site origin."
        return {"x": x, "y": y, **({"label": label} if label else {})}
    return {"label": label} if label else None


def clean_fields(v: Any, err: dict[str, str]) -> dict[str, str]:
    if v in (None, ""):
        return {}
    if not isinstance(v, dict):
        err["fields"] = "Details are names with text values."
        return {}
    out: dict[str, str] = {}
    for k, val in v.items():
        key = str(k or "").strip().lower().replace(" ", "_")
        if not key:
            continue
        if not _FIELD.match(key):
            err[f"fields.{k}"] = (
                "A detail name is lower case letters, digits and _ only, up to 40 characters."
            )
            continue
        s = "" if val is None else str(val).strip()
        if len(s) > 200:
            err[f"fields.{key}"] = "Keep each detail under 200 characters."
            continue
        if s:
            out[key] = s
    if len(out) > MAX_FIELDS:
        err["fields"] = f"An asset can have at most {MAX_FIELDS} details."
    return out


def clean_key(
    group: str, node: str, device: str, err: dict[str, str]
) -> tuple[str, str, str]:
    g, n, d = (group or "").strip(), (node or "").strip(), (device or "").strip()
    if not g or not _KEYPART.match(g):
        err["group"] = (
            "The group is the first part of the asset's key, without / # or +."
        )
    if not n or not _KEYPART.match(n):
        err["node"] = "The asset id is the second part of the key, without / # or +."
    if d and not _KEYPART.match(d):
        err["device"] = "The part id cannot contain / # or +."
    return g, n, d


def clean(body: dict[str, Any]) -> dict[str, Any]:
    """The registry row as stored. Raises AssetInvalid with a message per field."""
    err: dict[str, str] = {}
    name = body.get("display_name")
    name = str(name).strip() if name not in (None,) else ""
    if len(name) > 120:
        err["display_name"] = "Keep the name under 120 characters."
    t = body.get("type")
    t = str(t).strip().lower() if t not in (None, "") else None
    if t is not None and t not in ASSET_TYPES:
        err["type"] = "Choose vehicle, machine, sensor, device or system."
    out = {
        "display_name": name or None,
        "asset_type": t,
        "tags": clean_tags(body.get("tags"), err),
        "location": clean_location(body.get("location"), err),
        "fields": clean_fields(body.get("fields"), err),
    }
    if err:
        raise AssetInvalid(err)
    return out


def row_json(
    a: Any,
    *,
    live: dict[str, Any] | None,
    teams: dict[str, str],
    can_edit: bool,
    parts: list[str] | None = None,
    key: tuple[str, str, str] | None = None,
) -> dict[str, Any]:
    g, n, d = key if key else (a.grp, a.node, a.device or "")
    lv = live or {}
    tid = str(a.team_id) if a is not None and a.team_id else None
    row = {
        "id": str(a.id) if a is not None else None,
        "key": f"{g}/{n}/{d}",
        "group": g,
        "node": n,
        "device": d,
        "registered": a is not None,
        "display_name": a.display_name if a is not None else None,
        "type": a.asset_type if a is not None else None,
        "tags": list(a.tags or []) if a is not None else [],
        "team_id": tid,
        "team_name": teams.get(tid) if tid else None,
        "location": a.location if a is not None else None,
        "fields": dict(a.fields or {}) if a is not None else {},
        "live": bool(live),
        "online": lv.get("online") if live else None,
        "last_seen": lv.get("last_seen") if live else None,
        "connection_id": lv.get("connection_id") if live else None,
        "updated_at": (
            a.updated_at.isoformat() if a is not None and a.updated_at else None
        ),
        "can_edit": can_edit,
    }
    if not d:
        row["parts"] = parts or []
    return row


def matches(
    row: dict[str, Any], *, q: str, type_: str, tag: str, group: str, status: str
) -> bool:
    if group and row["group"] != group:
        return False
    if type_ and (row.get("type") or "") != type_:
        return False
    if tag and tag.lower() not in (row.get("tags") or []):
        return False
    if status == "registered" and not row["registered"]:
        return False
    if status == "unregistered" and row["registered"]:
        return False
    if q:
        ql = q.lower()
        hay = " ".join(
            [
                row["key"],
                row.get("display_name") or "",
                " ".join(row.get("tags") or []),
                " ".join((row.get("fields") or {}).values()),
            ]
        ).lower()
        if ql not in hay:
            return False
    return True


def facets(rows: list[dict[str, Any]]) -> dict[str, Any]:
    types: dict[str, int] = {}
    tags: dict[str, int] = {}
    reg = unreg = 0
    for r in rows:
        if r["registered"]:
            reg += 1
        else:
            unreg += 1
        if r.get("type"):
            types[r["type"]] = types.get(r["type"], 0) + 1
        for t in r.get("tags") or []:
            tags[t] = tags.get(t, 0) + 1
    return {
        "types": types,
        "tags": [
            {"tag": t, "count": c}
            for t, c in sorted(tags.items(), key=lambda x: (-x[1], x[0]))
        ],
        "registered": reg,
        "unregistered": unreg,
    }


# CSV import


def template_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([*CSV_COLUMNS, "fuel"])
    w.writerow(
        [
            "groundwork",
            "ipc-ex1",
            "",
            "Excavator EX1",
            "machine",
            "earthworks;north pit",
            "",
            "",
            "",
            "120.5",
            "48.0",
            "",
            "",
            "EX1-2291",
            "CAT 336",
            "diesel",
        ]
    )
    w.writerow(
        [
            "fleet",
            "van-017",
            "",
            "Van 17",
            "vehicle",
            "deliveries|city",
            "",
            "51.5072",
            "-0.1276",
            "",
            "",
            "WF0XXXTTGXKA12345",
            "AB12 CDE",
            "",
            "Transit",
            "diesel",
        ]
    )
    return buf.getvalue()


def parse_csv(
    text: str, teams_by_name: dict[str, str], team_ids: set[str]
) -> tuple[list[dict[str, Any]], str | None]:
    """Rows with their cleaned values and plain errors. The second value is a whole-file problem."""
    if len(text.encode("utf-8", "ignore")) > CSV_MAX_BYTES:
        return (
            [],
            f"The file is larger than {CSV_MAX_BYTES // 1_000_000} MB. Split it into smaller files.",
        )
    text = text.lstrip("﻿")
    if not text.strip():
        return [], "The file is empty. Start from the template, it has the header row."
    try:
        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        header = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        return [], "The file is empty. Start from the template, it has the header row."
    if "group" not in header or "node" not in header:
        return (
            [],
            "The first row must be a header with at least group and node columns. Download the template to see the layout.",
        )
    if len(set(header)) != len(header):
        return [], "Two columns have the same name in the header row."
    out: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for i, raw in enumerate(reader, start=2):
        if not any((c or "").strip() for c in raw):
            continue
        if len(out) >= CSV_MAX_ROWS:
            return (
                out,
                f"The file has more than {CSV_MAX_ROWS} rows. Split it into smaller files.",
            )
        rec = {
            header[j]: (raw[j] if j < len(raw) else "").strip()
            for j in range(len(header))
        }
        err: dict[str, str] = {}
        g, n, d = clean_key(
            rec.get("group", ""), rec.get("node", ""), rec.get("device", ""), err
        )
        body: dict[str, Any] = {
            "display_name": rec.get("name") or None,
            "type": rec.get("type") or None,
            "tags": rec.get("tags") or "",
        }
        if any(rec.get(k) for k in ("lat", "lon", "x", "y")):
            body["location"] = {
                k: rec.get(k) for k in ("lat", "lon", "x", "y") if rec.get(k)
            }
        extra = {k: v for k, v in rec.items() if k not in CSV_COLUMNS and v}
        body["fields"] = {
            **{k: rec.get(k) for k in FIXED_FIELDS if rec.get(k)},
            **extra,
        }
        cleaned: dict[str, Any] = {}
        try:
            cleaned = clean(body)
        except AssetInvalid as e:
            err.update(e.fields)
        team_id = None
        tv = rec.get("team") or ""
        if tv:
            if tv in team_ids:
                team_id = tv
            elif tv.lower() in teams_by_name:
                team_id = teams_by_name[tv.lower()]
            else:
                err["team"] = (
                    f"No team called {tv!r}. Teams are set up under Admin, Permissions."
                )
        key = f"{g}/{n}/{d}"
        if key in seen and not err:
            err["key"] = f"This asset is also on line {seen[key]}."
        seen.setdefault(key, i)
        out.append(
            {
                "line": i,
                "key": key,
                "group": g,
                "node": n,
                "device": d,
                "display_name": cleaned.get("display_name"),
                "type": cleaned.get("asset_type"),
                "tags": cleaned.get("tags") or [],
                "location": cleaned.get("location"),
                "fields": cleaned.get("fields") or {},
                "team_id": team_id,
                "errors": [_plain(k, v) for k, v in err.items()],
            }
        )
    if not out:
        return [], "The file has a header but no rows."
    return out, None


def _plain(field: str, msg: str) -> str:
    return msg if field in ("key",) else f"{field.replace('_', ' ')}: {msg}"


def same(a: Any, row: dict[str, Any]) -> bool:
    return (
        (a.display_name or None) == row["display_name"]
        and (a.asset_type or None) == row["type"]
        and list(a.tags or []) == row["tags"]
        and (a.location or None) == row["location"]
        and dict(a.fields or {}) == row["fields"]
        and (str(a.team_id) if a.team_id else None) == row["team_id"]
    )
