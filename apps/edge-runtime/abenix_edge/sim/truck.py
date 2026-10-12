"""A haul truck doing laps of a site route, for the simulated ECUs: driver, gearbox, engine, cooling, DEF.

The route has a site gate, an access road, a hill, a descent and a turn. Each lap
the driver picks slightly different speeds, the load changes and traffic slows the
truck now and then, all from one seeded random stream, so a run is repeatable but
never periodic. Time advances in fixed 50 ms steps, paced to the wall clock.
"""

from __future__ import annotations

import math
import os
import random
import threading
import time
from dataclasses import dataclass, field

DT = 0.05
G = 9.81
RATIOS = (14.94, 11.73, 9.04, 7.09, 5.54, 4.35, 3.44, 2.70, 2.08, 1.63, 1.27, 1.00)
FINAL_DRIVE = 3.08
WHEEL_R = 0.52
DRIVELINE_EFF = 0.92
IDLE_RPM = 600.0
REF_TORQUE = 2600.0
ORIGIN = (51.4927, 0.0645)


def max_torque(rpm: float) -> float:
    """A 13 litre diesel: full torque from 1000 to 1400 rpm, falling off either side."""
    if rpm < 1000:
        return 1100 + 1500 * max(0.0, (rpm - IDLE_RPM) / 400)
    if rpm <= 1400:
        return 2600.0
    return max(600.0, 2600 - (rpm - 1400) * 2.6)


@dataclass
class Segment:
    start: tuple[float, float]
    end: tuple[float, float]
    limit_kmh: float
    grade_pct: float
    name: str
    stop_at_end: bool = False

    @property
    def length_m(self) -> float:
        return math.dist(self.start, self.end)

    @property
    def heading_deg(self) -> float:
        dx, dy = self.end[0] - self.start[0], self.end[1] - self.start[1]
        return math.degrees(math.atan2(dx, dy)) % 360


# a closed loop in metres east and north of the site gate, about 3.5 km
_POINTS = [
    (0, 0),
    (180, 0),
    (630, 200),
    (740, 610),
    (640, 1205),
    (215, 1270),
    (110, 1175),
    (-60, 160),
]
_LEGS = [
    (20, 0.0, "yard exit"),
    (50, 0.5, "access road"),
    (45, 6.0, "hill climb"),
    (60, 0.0, "top road"),
    (45, -5.0, "descent"),
    (25, 0.0, "turn"),
    (50, -0.48, "return road"),
    (20, -0.5, "gate approach"),
]
ROUTE = [
    Segment(
        _POINTS[i],
        _POINTS[(i + 1) % len(_POINTS)],
        lim,
        grade,
        name,
        stop_at_end=i == len(_LEGS) - 1,
    )
    for i, (lim, grade, name) in enumerate(_LEGS)
]


@dataclass
class State:
    t: float = 0.0
    speed: float = 0.0
    rpm: float = IDLE_RPM
    gear: int = 0
    selected_gear: int = 0
    torque_pct: float = 5.0
    pedal_pct: float = 0.0
    load_pct: float = 5.0
    fuel_lph: float = 2.6
    coolant_c: float = 72.0
    oil_c: float = 78.0
    lat: float = ORIGIN[0]
    lon: float = ORIGIN[1]
    heading: float = 90.0
    altitude_m: float = 35.0
    grade_pct: float = 0.0
    odometer_km: float = 284113.0
    hours: float = 12873.4
    fuel_level_pct: float = 64.0
    def_level_pct: float = 13.2
    braking: bool = False
    phase: str = "idle at the gate"
    segment: str = ROUTE[0].name
    def_warning: bool = False
    dtcs: list[tuple[int, int, int]] = field(default_factory=list)


class Truck:
    def __init__(self, seed: int | None = None, start: bool = True) -> None:
        self.rng = random.Random(
            int(os.environ.get("SIM_SEED", "7")) if seed is None else seed
        )
        self.s = State()
        self.lock = threading.Lock()
        self.seg = 0
        self.pos_m = 0.0
        self.lap = 0
        self.mass = 0.0
        self.targets: list[float] = []
        self.dwell = 0.0
        self.shift_left = 0.0
        self.shift_to = 0
        self.since_shift = 10.0
        self.slowdown: tuple[float, float] = (-1, 0)
        self.x = 0.0
        self.y = 0.0
        self.refill_due = False
        # slow wander in the driver's chosen speed and in the road's grade, so cruise is never flat
        self.v_dev = 0.0
        self.a_cmd = 0.0
        self.g_dev = 0.0
        self._new_lap()
        self.dwell = 8.0
        self._snap = State(**self.s.__dict__)
        if start:
            threading.Thread(target=self._run, daemon=True).start()

    # the driver's plan for a lap

    def _new_lap(self) -> None:
        self.lap += 1
        r = self.rng
        payload = r.choice((0.0, 6.0, 11.0, 14.5, 18.0)) * 1000
        self.mass = 15500 + payload
        self.targets = [seg.limit_kmh * r.uniform(0.82, 1.0) / 3.6 for seg in ROUTE]
        # sometimes a slow vehicle ahead on one stretch
        if r.random() < 0.55:
            i = r.choice((1, 3, 6))
            self.slowdown = (i, r.uniform(12, 25) / 3.6)
        else:
            self.slowdown = (-1, 0)

    def _target(self) -> float:
        seg = ROUTE[self.seg]
        v = max(1.0, self.targets[self.seg] + self.v_dev)
        i, slow = self.slowdown
        if i == self.seg and 0.25 < self.pos_m / seg.length_m < 0.7:
            v = min(v, slow)
        # look ahead to the next limit or the gate and brake gently for it
        left = seg.length_m - self.pos_m
        nxt = 0.0 if seg.stop_at_end else self.targets[(self.seg + 1) % len(ROUTE)]
        return min(v, math.sqrt(nxt * nxt + 2 * 0.9 * max(0.0, left - 1.5)))

    # one 50 ms step

    def step(self) -> None:
        s = self.s
        s.t += DT
        seg = ROUTE[self.seg]
        r = self.rng
        self.v_dev += -self.v_dev / 15 * DT + 0.22 * math.sqrt(DT) * r.gauss(0, 1)
        self.g_dev += -self.g_dev / 20 * DT + 0.22 * math.sqrt(DT) * r.gauss(0, 1)
        grade = math.atan((seg.grade_pct + self.g_dev) / 100)
        if self.dwell > 0:
            self._idle(seg)
            return
        if seg.stop_at_end and seg.length_m - self.pos_m < 3 and s.speed < 0.8:
            self._arrive()
            return
        v_t = self._target()
        raw = max(-2.2, min(1.0, 0.8 * (v_t - s.speed)))
        # a driver eases the pedal, except to brake hard
        self.a_cmd += (raw - self.a_cmd) * min(1.0, DT / (0.3 if raw < -1.0 else 1.2))
        a_want = self.a_cmd
        resist = (
            self.mass * G * (0.0065 * math.cos(grade) + math.sin(grade))
            + 0.5 * 1.2 * 6.2 * s.speed**2
        )
        if s.speed < 0.05 and a_want <= 0:
            resist = max(0.0, resist)
        f_need = self.mass * a_want + resist
        # gear for the next step
        self.since_shift += DT
        if self.shift_left > 0:
            self.shift_left -= DT
            if self.shift_left <= 0:
                s.gear = self.shift_to
        elif s.gear == 0:
            s.gear = s.selected_gear = 2 if self.mass < 26000 else 1
        else:
            wheel_rpm = s.speed / WHEEL_R * 60 / (2 * math.pi) * FINAL_DRIVE
            rpm_now = wheel_rpm * RATIOS[s.gear - 1]
            up_at = 1350 + 350 * (s.pedal_pct / 100)
            if rpm_now > 1850 and s.gear < 12 and self.since_shift > 0.8:
                self._shift(s.gear + 1)
            elif (
                rpm_now > up_at
                and s.gear < 12
                and f_need > 0
                and self.since_shift > 2.5
            ):
                self._shift(s.gear + 1 if rpm_now < 1700 or s.gear > 10 else s.gear + 2)
            elif (
                rpm_now < (1050 if f_need > 0.5 * resist and grade > 0.02 else 900)
                and s.gear > 1
                and self.since_shift > 1.5
            ):
                self._shift(s.gear - 1)
        g = max(1, s.gear)
        ratio = RATIOS[g - 1] * FINAL_DRIVE
        wheel_rpm = s.speed / WHEEL_R * 60 / (2 * math.pi)
        engine_rpm = wheel_rpm * ratio
        slipping = engine_rpm < 950 and f_need > 0
        rpm = max(engine_rpm, IDLE_RPM)
        if self.shift_left > 0:
            # clutch open, torque cut, the engine falls toward the next gear's speed
            torque = 0.0
            nxt = wheel_rpm * RATIOS[self.shift_to - 1] * FINAL_DRIVE
            rpm = s.rpm + (max(nxt, IDLE_RPM) - s.rpm) * min(1.0, DT / 0.35)
            f_drive = 0.0
        elif f_need > 0:
            if slipping:
                rpm = max(rpm, 900 + 250 * min(1.0, f_need / (self.mass * 0.8)))
            t_need = f_need * WHEEL_R / (ratio * DRIVELINE_EFF)
            torque = min(t_need, max_torque(rpm))
            f_drive = torque * ratio * DRIVELINE_EFF / WHEEL_R
        else:
            torque = 0.0
            f_drive = 0.0
        a = (f_drive - resist) / self.mass if f_need > 0 else a_want
        s.braking = f_need <= 0 and a_want < -0.15
        s.speed = max(0.0, s.speed + a * DT)
        s.rpm = rpm + self.rng.gauss(0, 4)
        s.torque_pct = (
            100 * torque / REF_TORQUE
            if torque > 0
            else (0.0 if engine_rpm > 900 else 4.0)
        )
        s.pedal_pct = min(100.0, 100 * torque / max(1.0, max_torque(rpm)))
        s.load_pct = max(4.0, s.torque_pct)
        power_kw = torque * rpm * 2 * math.pi / 60 / 1000
        s.fuel_lph = 2.4 + power_kw * 0.205 / 0.835 + self.rng.gauss(0, 0.15)
        s.phase = (
            "shifting"
            if self.shift_left > 0
            else (
                "braking"
                if s.braking
                else (
                    "pulling away"
                    if s.speed < 2.5 and f_need > 0
                    else "hill climb" if seg.grade_pct > 3 else "cruise"
                )
            )
        )
        self._thermal(power_kw)
        self._consume(power_kw)
        self._move(seg)

    def _arrive(self) -> None:
        self.pos_m = 0.0
        self.s.speed = 0.0
        self.s.altitude_m = 35.0
        self.dwell = self.rng.uniform(18, 55)

    def _shift(self, to: int) -> None:
        to = max(1, min(12, to))
        self.shift_to = to
        self.s.selected_gear = to
        self.shift_left = 0.45 + self.rng.uniform(0, 0.25)
        self.since_shift = 0.0

    def _idle(self, seg: Segment) -> None:
        s = self.s
        self.dwell -= DT
        self.a_cmd = 0.0
        s.speed = 0.0
        s.gear = s.selected_gear = 0
        s.rpm += (IDLE_RPM + self.rng.gauss(0, 6) - s.rpm) * min(1.0, DT / 0.6)
        s.torque_pct = 4.0 + self.rng.gauss(0, 0.4)
        s.pedal_pct = 0.0
        s.load_pct = 5.0
        s.fuel_lph = 2.5 + self.rng.gauss(0, 0.05)
        s.braking = True
        s.phase = "stopped at the gate"
        self._thermal(4.0)
        self._consume(4.0)
        if self.refill_due and self.dwell < 5:
            # mostly a jerry can top-up, now and then a full tank
            full = self.rng.random() < 0.3
            s.def_level_pct = (
                self.rng.uniform(80, 92) if full else self.rng.uniform(14, 30)
            )
            self.refill_due = False
        if self.dwell <= 0:
            self.seg, self.pos_m = 0, 0.0
            self._new_lap()

    def _thermal(self, power_kw: float) -> None:
        s = self.s
        frac = max(0.0, power_kw) / 340
        heat = 0.025 + 0.11 * frac
        opening = min(1.0, max(0.04, (s.coolant_c - 86) / 7))
        s.coolant_c += DT * (heat - 0.0019 * opening * (s.coolant_c - 15))
        s.oil_c += DT * ((s.coolant_c + 6 + 10 * frac) - s.oil_c) / 90

    def _consume(self, power_kw: float) -> None:
        s = self.s
        litres = s.fuel_lph * DT / 3600
        s.fuel_level_pct = max(5.0, s.fuel_level_pct - litres / 400 * 100)
        # DEF is drawn quicker than life so the warning shows up within a demo
        s.def_level_pct = max(
            0.0, s.def_level_pct - (0.004 + 0.00004 * max(0.0, power_kw)) * DT
        )
        s.hours += DT / 3600
        if s.def_level_pct < 10.0 and not s.def_warning:
            s.def_warning = True
            self.refill_due = self.rng.random() < 0.7
        elif s.def_level_pct >= 10.0 and s.def_warning:
            s.def_warning = False
        if s.def_warning:
            # DEF tank level low, and the inducement warning that comes with it
            s.dtcs = [(1761, 18, 1), (5246, 15, 1)]
        else:
            s.dtcs = []

    def _move(self, seg: Segment) -> None:
        s = self.s
        d = s.speed * DT
        s.odometer_km += d / 1000
        self.pos_m += d
        s.altitude_m += d * seg.grade_pct / 100
        s.grade_pct = seg.grade_pct + self.g_dev
        # heading eases into the next segment over the last 25 m
        nxt = ROUTE[(self.seg + 1) % len(ROUTE)]
        left = seg.length_m - self.pos_m
        h = seg.heading_deg
        if left < 25:
            diff = (nxt.heading_deg - h + 540) % 360 - 180
            h = (h + diff * (1 - left / 25) / 2) % 360
        s.heading = h
        f = min(1.0, self.pos_m / seg.length_m)
        self.x = seg.start[0] + (seg.end[0] - seg.start[0]) * f
        self.y = seg.start[1] + (seg.end[1] - seg.start[1]) * f
        s.lat = ORIGIN[0] + self.y / 111_320
        s.lon = ORIGIN[1] + self.x / (111_320 * math.cos(math.radians(ORIGIN[0])))
        s.segment = seg.name
        if self.pos_m >= seg.length_m:
            self.pos_m -= seg.length_m
            if seg.stop_at_end:
                self._arrive()
            else:
                self.seg = (self.seg + 1) % len(ROUTE)

    def _run(self) -> None:
        nxt = time.monotonic()
        while True:
            self.step()
            with self.lock:
                self._snap = State(**{**self.s.__dict__, "dtcs": list(self.s.dtcs)})
            nxt += DT
            delay = nxt - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -1:
                nxt = time.monotonic()

    def now(self) -> State:
        with self.lock:
            return self._snap
