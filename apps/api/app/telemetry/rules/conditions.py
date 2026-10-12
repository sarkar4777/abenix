"""Rule conditions as small state machines, shared by the live evaluator and the preview.

Each condition turns a sample into True (the rule should be active), False (it
should be clear) or None (inside the hysteresis band, keep what it was). step()
adds the parts every condition shares: arming, edges, cooldown and late samples.
The state is a plain dict so it can live in memory or as JSON in Redis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

PER = {"s": 1.0, "min": 60.0, "h": 3600.0}
WINDOW_CAP = 120
EARTH_M = 6_371_000.0


@dataclass
class Sample:
    value: Any
    ts: int
    signal: str = ""
    # a geofence's partner coordinate, the sweep's age
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Outcome:
    fired: bool = False
    cleared: bool = False
    # active again inside the cooldown, so nothing was sent
    suppressed: bool = False
    value: Any = None
    words: str = ""


NOTHING = Outcome()


def num(v: Any) -> float | None:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "on", "yes"):
            return 1.0
        if s in ("false", "off", "no"):
            return 0.0
        try:
            f = float(s)
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    return None


def norm(v: Any) -> str:
    """Values compared for state equals: 1, 1.0 and "1" match, true and "TRUE" match."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        f = float(v)
        return str(int(f)) if f.is_integer() else repr(f)
    s = str(v if v is not None else "").strip().lower()
    if s in ("true", "false"):
        return s
    try:
        f = float(s)
        return str(int(f)) if f.is_integer() else repr(f)
    except ValueError:
        return s


def fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.4g}" if abs(v) < 1e-3 or abs(v) >= 1e6 else f"{round(v, 3):g}"
    return str(v)


# geometry


def point_in_polygon(x: float, y: float, poly: list[list[float]]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if (yi > y) != (yj > y):
            cross = (xj - xi) * (y - yi) / ((yj - yi) or 1e-300) + xi
            if x < cross:
                inside = not inside
        j = i
    return inside


def _seg_dist(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def edge_distance(x: float, y: float, poly: list[list[float]], gnss: bool) -> float:
    """Distance to the nearest edge, metres for lat/lon (x is longitude), site units otherwise."""
    if gnss:
        # local flat projection around the point is plenty for a site fence
        kx = math.cos(math.radians(y)) * math.pi / 180.0 * EARTH_M
        ky = math.pi / 180.0 * EARTH_M
        pts = [[(p[0] - x) * kx, (p[1] - y) * ky] for p in poly]
        px = py = 0.0
    else:
        pts, px, py = poly, x, y
    n = len(pts)
    best = math.inf
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        best = min(best, _seg_dist(px, py, a[0], a[1], b[0], b[1]))
    return best


# conditions


class Cond:
    kind = ""
    # the first reading only sets where it stands, it never fires
    edge_only = False
    # stale is read by the sweep, never from a message
    swept = False
    # a second reading with the same time is a repeat, except for a zone's two coordinates
    once_per_ts = True

    def __init__(self, c: dict[str, Any]) -> None:
        self.c = c
        self.signal = str(c.get("signal") or "")
        self.h = float(c.get("hysteresis") or 0)

    def signals(self) -> list[str]:
        return [self.signal] if self.signal else []

    def truth(self, st: dict[str, Any], s: Sample) -> tuple[bool | None, Any, str]:
        raise NotImplementedError


class Threshold(Cond):
    kind = "threshold"

    def truth(self, st, s):
        x = num(s.value)
        if x is None:
            return None, s.value, ""
        op, v, h = self.c.get("op") or ">", float(self.c["value"]), self.h
        if op in (">", ">="):
            on = x > v if op == ">" else x >= v
            off = x <= v - h if h else not on
            words = f"is {fmt(x)}, {'above' if op == '>' else 'at or above'} {fmt(v)}"
        else:
            on = x < v if op == "<" else x <= v
            off = x >= v + h if h else not on
            words = f"is {fmt(x)}, {'below' if op == '<' else 'at or below'} {fmt(v)}"
        if on:
            return True, x, words
        return (False if off else None), x, f"is {fmt(x)}"


class Range(Cond):
    kind = "range"

    def truth(self, st, s):
        x = num(s.value)
        if x is None:
            return None, s.value, ""
        lo, hi, h = float(self.c["min"]), float(self.c["max"]), self.h
        if x < lo:
            return True, x, f"is {fmt(x)}, under the range {fmt(lo)} to {fmt(hi)}"
        if x > hi:
            return True, x, f"is {fmt(x)}, over the range {fmt(lo)} to {fmt(hi)}"
        if lo + h <= x <= hi - h:
            return False, x, f"is {fmt(x)}"
        return None, x, ""


class Rate(Cond):
    kind = "rate"

    def truth(self, st, s):
        x = num(s.value)
        if x is None:
            return None, s.value, ""
        win_ms = int(float(self.c.get("window_s") or 10) * 1000)
        w = st.setdefault("w", [])
        w.append([s.ts, x])
        cut = s.ts - win_ms
        while len(w) > 2 and w[1][0] <= cut:
            w.pop(0)
        if len(w) > WINDOW_CAP:
            # thin the middle, keep both ends
            st["w"] = w = [w[0], *w[1:-1:2], w[-1]]
        t0, x0 = w[0]
        dt = (s.ts - t0) / 1000.0
        if len(w) < 2 or dt <= 0 or dt * 1000 < min(win_ms / 2, 1000):
            return None, x, ""
        per = self.c.get("per") or "s"
        r = (x - x0) / dt * PER.get(per, 1.0)
        d = self.c.get("direction") or "either"
        val = r if d == "up" else -r if d == "down" else abs(r)
        limit = float(self.c["limit"])
        unit = {"s": "a second", "min": "a minute", "h": "an hour"}.get(per, "a second")
        words = f"changed by {fmt(round(r, 4))} {unit} over {fmt(round(dt, 1))} s, faster than {fmt(limit)}"
        if val > limit:
            return True, round(r, 6), words
        if val <= limit - self.h:
            return False, round(r, 6), ""
        return None, round(r, 6), ""


class Stale(Cond):
    kind = "stale"
    swept = True

    def truth(self, st, s):
        age_ms = s.extra.get("age_ms")
        if age_ms is None:
            return None, None, ""
        secs = float(self.c["seconds"])
        age = age_ms / 1000.0
        if age > secs:
            what = self.signal or "data"
            tail = s.extra.get("offline_words") or ""
            return (
                True,
                round(age, 1),
                f"has sent no {what} for {fmt(round(age))} s{tail}",
            )
        return False, round(age, 1), ""


class State(Cond):
    kind = "state"

    def truth(self, st, s):
        want = norm(self.c.get("equals"))
        got = norm(s.value)
        eq = got == want
        if (self.c.get("op") or "equals") == "not_equals":
            return (
                (not eq),
                s.value,
                f"is {fmt(s.value)}, not {fmt(self.c.get('equals'))}",
            )
        return eq, s.value, f"is {fmt(s.value)}"


class Geofence(Cond):
    kind = "geofence"
    edge_only = True
    once_per_ts = False

    def __init__(self, c: dict[str, Any]) -> None:
        super().__init__(c)
        self.x_signal = str(c.get("x_signal") or "")
        self.y_signal = str(c.get("y_signal") or "")
        self.signal = self.x_signal
        self.poly = [[float(p[0]), float(p[1])] for p in c.get("polygon") or []]
        self.gnss = (c.get("frame") or "site") == "gnss"

    def signals(self) -> list[str]:
        return [self.x_signal, self.y_signal]

    def truth(self, st, s):
        x, y = num(s.extra.get("x")), num(s.extra.get("y"))
        if x is None or y is None or len(self.poly) < 3:
            return None, None, ""
        inside = point_in_polygon(x, y, self.poly)
        d = 0.0 if inside else edge_distance(x, y, self.poly, self.gnss)
        name = self.c.get("zone") or "the zone"
        pos = (
            f"{fmt(round(y, 6))}, {fmt(round(x, 6))}"
            if self.gnss
            else f"x {fmt(round(x, 2))}, y {fmt(round(y, 2))}"
        )
        if (self.c.get("on") or "enter") == "enter":
            if inside:
                return True, [x, y], f"entered {name} at {pos}"
            return (False if d > self.h else None), [x, y], ""
        if inside:
            return False, [x, y], ""
        if d > self.h:
            return True, [x, y], f"left {name}, now at {pos}"
        return None, [x, y], ""


class Deviation(Cond):
    """The recent mean against the same signal's longer baseline, from rolling buckets kept in state."""

    kind = "deviation"

    def _bucket_ms(self) -> int:
        base_s = float(self.c.get("baseline_s") or 1800)
        return max(1000, int(base_s * 1000 / 120))

    def truth(self, st, s):
        x = num(s.value)
        if x is None:
            return None, s.value, ""
        short_ms = int(float(self.c.get("window_s") or 300) * 1000)
        base_ms = int(float(self.c.get("baseline_s") or 1800) * 1000)
        bms = self._bucket_ms()
        start = s.ts - s.ts % bms
        b = st.setdefault("b", [])
        if b and b[-1][0] == start:
            b[-1][1] += x
            b[-1][2] += x * x
            b[-1][3] += 1
        else:
            b.append([start, x, x * x, 1])
        cut = s.ts - short_ms - base_ms
        while b and b[0][0] + bms <= cut:
            b.pop(0)
        split = s.ts - short_ms
        recent = [r for r in b if r[0] + bms > split]
        base = [r for r in b if r[0] + bms <= split]
        rn = sum(r[3] for r in recent)
        bn = sum(r[3] for r in base)
        # the baseline must cover at least half its window before the rule speaks
        if rn < 3 or bn < 3 or not base or (split - base[0][0]) < base_ms / 2:
            return None, x, ""
        rmean = sum(r[1] for r in recent) / rn
        bmean = sum(r[1] for r in base) / bn
        var = max(0.0, sum(r[2] for r in base) / bn - bmean * bmean)
        sd = math.sqrt(var)
        mode = self.c.get("mode") or "ratio"
        d = self.c.get("direction") or "up"
        t = float(self.c["threshold"])
        h = self.h
        win = fmt(float(self.c.get("window_s") or 300) / 60)
        basew = fmt(float(self.c.get("baseline_s") or 1800) / 60)
        means = f"mean {fmt(round(rmean, 3))} against {fmt(round(bmean, 3))}"
        if mode == "ratio":
            if bmean <= 0:
                return None, x, ""
            r = rmean / bmean
            pct = round((r - 1) * 100, 1)
            words = (
                f"ran {fmt(abs(pct))}% {'above' if pct >= 0 else 'below'} its level over the last "
                f"{basew} min, the last {win} min ({means})"
            )
            if d == "up":
                on, off = r > t, r <= t - h
            elif d == "down":
                on, off = r < t, r >= t + h
            else:
                lo = 1.0 / t if t > 0 else 0.0
                on = r > t or r < lo
                off = (lo + h) <= r <= (t - h)
            val = round(r, 4)
        else:
            if sd <= 0:
                return None, x, ""
            z = (rmean - bmean) / sd
            words = (
                f"moved {fmt(round(abs(z), 2))} standard deviations {'above' if z >= 0 else 'below'} "
                f"its last {basew} min over the last {win} min ({means})"
            )
            if d == "up":
                on, off = z > t, z <= t - h
            elif d == "down":
                on, off = z < -t, z >= -t + h
            else:
                on, off = abs(z) > t, abs(z) <= t - h
            val = round(z, 4)
        if on:
            return True, val, words
        return (False if off else None), val, ""


class Count(Cond):
    kind = "count"

    def _matches(self, v: Any) -> bool:
        w = self.c.get("when")
        if not w:
            return True
        if "equals" in w:
            return norm(v) == norm(w.get("equals"))
        x = num(v)
        if x is None:
            return False
        op, lim = w.get("op") or ">", float(w.get("value") or 0)
        return {
            ">": x > lim,
            ">=": x >= lim,
            "<": x < lim,
            "<=": x <= lim,
        }.get(op, False)

    def truth(self, st, s):
        n = int(self.c["count"])
        win_ms = int(float(self.c["window_s"]) * 1000)
        w = st.setdefault("w", [])
        if self._matches(s.value):
            w.append(s.ts)
        cut = s.ts - win_ms
        while w and w[0] <= cut:
            w.pop(0)
        keep = n + int(self.h) + 5
        if len(w) > keep:
            del w[: len(w) - keep]
        k = len(w)
        words = (
            f"matched {k} times in {fmt(float(self.c['window_s']))} s, the limit is {n}"
        )
        if k >= n:
            return True, k, words
        if k <= n - 1 - int(self.h):
            return False, k, ""
        return None, k, ""


KINDS: dict[str, type[Cond]] = {
    c.kind: c
    for c in (Threshold, Range, Rate, Stale, State, Geofence, Count, Deviation)
}


def compile_condition(c: dict[str, Any]) -> Cond:
    cls = KINDS.get(str(c.get("kind") or ""))
    if cls is None:
        raise ValueError(f"Unknown condition {c.get('kind')!r}")
    return cls(c)


def step(cond: Cond, st: dict[str, Any], s: Sample, cooldown_ms: int) -> Outcome:
    """Advance one rule on one asset by one sample. Mutates st."""
    lt = st.get("lt")
    if (
        lt is not None
        and not cond.swept
        and (s.ts < lt or (s.ts == lt and cond.once_per_ts))
    ):
        # late or repeated data never moves a rule, so a replayed batch changes nothing
        st["late"] = int(st.get("late") or 0) + 1
        return NOTHING
    st["lt"] = s.ts
    truth, value, words = cond.truth(st, s)
    prev = st.get("a")
    if truth is None:
        return NOTHING
    if cond.edge_only and prev is None:
        st["a"] = truth
        return NOTHING
    if truth:
        if prev:
            return NOTHING
        st["a"] = True
        lf = st.get("lf")
        if lf is not None and cooldown_ms > 0 and s.ts - lf < cooldown_ms:
            # active again in the quiet time, so it also clears quietly
            st["q"] = 1
            return Outcome(suppressed=True, value=value, words=words)
        st.pop("q", None)
        st["lf"] = s.ts
        return Outcome(fired=True, value=value, words=words)
    st["a"] = False
    if prev and not st.pop("q", None):
        return Outcome(cleared=True, value=value, words=words)
    return NOTHING
