"""Compiled rules per workspace, indexed by signal name, and the asset facts scopes match on."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.telemetry.rules.conditions import Cond, compile_condition


def akey(g: str, n: str, d: str = "") -> str:
    return f"{g}/{n}/{d}"


@dataclass
class AssetFacts:
    """Registry rows of one workspace: type, tags and name per key."""

    rows: dict[str, dict[str, Any]] = field(default_factory=dict)

    def props(self, g: str, n: str, d: str) -> tuple[str | None, frozenset[str]]:
        own = self.rows.get(akey(g, n, d))
        top = self.rows.get(akey(g, n, "")) if d else None
        t = (own or {}).get("type") or (top or {}).get("type")
        tags = frozenset((own or {}).get("tags") or ()) | frozenset(
            (top or {}).get("tags") or ()
        )
        return t, tags

    def name(self, g: str, n: str, d: str = "") -> str:
        top = (self.rows.get(akey(g, n, "")) or {}).get("name") or n
        if not d:
            return top
        own = (self.rows.get(akey(g, n, d)) or {}).get("name")
        return own or f"{top} {d}"

    def keys_where(
        self, kind: str, value: str, group: str = ""
    ) -> list[tuple[str, str, str]]:
        out = []
        for k, r in self.rows.items():
            g, n, d = k.split("/", 2)
            if group and g != group:
                continue
            t, tags = self.props(g, n, d)
            if (kind == "type" and t == value) or (kind == "tag" and value in tags):
                out.append((g, n, d))
        return out


@dataclass
class Compiled:
    id: str
    tenant: str
    name: str
    severity: str
    cooldown_ms: int
    scope: dict[str, Any]
    cond: Cond
    actions: list[dict[str, Any]]
    created_by: str | None = None
    team_id: str | None = None

    def matches(self, g: str, n: str, d: str, facts: AssetFacts) -> bool:
        s = self.scope
        k = s.get("kind")
        if k == "asset":
            if g != s.get("group") or n != s.get("node"):
                return False
            dev = s.get("device", "*")
            return dev == "*" or dev == d
        if s.get("group") and g != s["group"]:
            return False
        t, tags = facts.props(g, n, d)
        if k == "type":
            return t == s.get("type")
        if k == "tag":
            return s.get("tag") in tags
        return False


def compile_rule(row: dict[str, Any]) -> Compiled:
    return Compiled(
        id=str(row["id"]),
        tenant=str(row["tenant_id"]),
        name=row.get("name") or "",
        severity=row.get("severity") or "warning",
        cooldown_ms=int(row.get("cooldown_s") or 0) * 1000,
        scope=dict(row.get("scope") or {}),
        cond=compile_condition(dict(row.get("condition") or {})),
        actions=list(row.get("actions") or []),
        created_by=str(row["created_by"]) if row.get("created_by") else None,
        team_id=str(row["team_id"]) if row.get("team_id") else None,
    )


@dataclass
class TenantIndex:
    by_signal: dict[str, list[Compiled]] = field(default_factory=dict)
    stale: list[Compiled] = field(default_factory=list)
    geo_signals: set[str] = field(default_factory=set)
    facts: AssetFacts = field(default_factory=AssetFacts)
    count: int = 0


def build(
    rules: list[Compiled], facts: dict[str, AssetFacts]
) -> dict[str, TenantIndex]:
    out: dict[str, TenantIndex] = {}
    for r in rules:
        ti = out.get(r.tenant)
        if ti is None:
            ti = out[r.tenant] = TenantIndex(facts=facts.get(r.tenant) or AssetFacts())
        ti.count += 1
        if r.cond.swept:
            ti.stale.append(r)
            continue
        for sig in r.cond.signals():
            ti.by_signal.setdefault(sig, []).append(r)
        if r.cond.kind == "geofence":
            ti.geo_signals.update(r.cond.signals())
    return out
