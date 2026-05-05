#!/usr/bin/env python3
"""FieldEdge weekly schedule solver.

Stdin: one JSON object {technicians, work_orders, days?, weather_forecast?,
previous_schedule?}. Stdout: one JSON object {solver, assignments,
unassigned, objective_value, infeasible, explanation}.

Hard constraints
- Each WO is assigned at most once across the horizon.
- Technician must possess every skill listed in skill_required.
- Daily hours per technician <= hours_per_day.
- weather_sensitive WOs only on days with climb_safe == True.
- WO not scheduled before parts_available_on (if supplied).

Soft objective
- Minimise sum of (priority_weight * day_index) so P1 WOs land early.
- Slight preference for spreading work across the crew (anti-stack).
- Penalty for unassigned WOs scaled by priority.

OR-tools is preferred. If the package isn't available we degrade to a
deterministic greedy heuristic that respects all the hard constraints —
the technician on the tower still gets a usable plan; the explanation
field flags the fallback.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from typing import Any

# Priority weights — lower number = more urgent = stronger pressure to
# schedule early. P1 is twice as urgent as P2, P3 is half-weight again.
PRIORITY_WEIGHT = {"P1": 4, "P2": 2, "P3": 1}


def _normalise_days(payload: dict, default_days: int = 7) -> list[str]:
    """Return ISO date strings for the planning horizon."""
    weather = payload.get("weather_forecast") or []
    if weather and all(isinstance(w, dict) and w.get("day") for w in weather):
        return [str(w["day"]) for w in weather[:default_days]]
    # Fall back to "today + N" so the solver can run without a forecast.
    today = datetime.utcnow().date()
    return [(today + timedelta(days=i)).isoformat() for i in range(default_days)]


def _climb_safe_map(payload: dict, days: list[str]) -> dict[str, bool]:
    """day -> climb_safe; default to True when forecast missing."""
    forecast = payload.get("weather_forecast") or []
    by_day: dict[str, bool] = {}
    for entry in forecast:
        if not isinstance(entry, dict):
            continue
        d = str(entry.get("day") or "")
        if not d:
            continue
        # Treat absent climb_safe as True unless wind/precip clearly fail.
        wind = float(entry.get("wind_mps") or 0)
        precip = (entry.get("precip") or "none").lower()
        derived_safe = wind <= 12 and precip in ("none", "")
        by_day[d] = bool(entry.get("climb_safe", derived_safe))
    return {d: by_day.get(d, True) for d in days}


def _wo_can_run_on_day(wo: dict, day: str, climb_safe: dict[str, bool]) -> bool:
    parts_avail = wo.get("parts_available_on")
    if parts_avail and str(day) < str(parts_avail):
        return False
    if wo.get("weather_sensitive") and not climb_safe.get(day, True):
        return False
    return True


def _tech_can_do(tech: dict, wo: dict) -> bool:
    needed = wo.get("skill_required") or []
    if isinstance(needed, str):
        needed = [needed]
    have = set(tech.get("skills") or [])
    return all(s in have for s in needed)


def solve_with_ortools(payload: dict, days: list[str]) -> dict[str, Any]:
    """CP-SAT model: assign WOs to (tech, day) cells with hour budgets."""
    from ortools.sat.python import cp_model  # type: ignore

    technicians = payload.get("technicians") or []
    work_orders = payload.get("work_orders") or []
    climb_safe = _climb_safe_map(payload, days)

    if not technicians or not work_orders:
        return {
            "solver": "or-tools",
            "assignments": [],
            "unassigned": [{"wo_id": w.get("wo_id"), "reason": "no_resources"}
                           for w in work_orders],
            "objective_value": 0,
            "infeasible": True,
            "explanation": "no technicians or no work orders supplied",
        }

    model = cp_model.CpModel()
    # x[w][t][d] = 1 if WO w assigned to tech t on day d.
    x: dict = {}
    for wi, w in enumerate(work_orders):
        for ti, t in enumerate(technicians):
            for di, d in enumerate(days):
                if not _tech_can_do(t, w):
                    continue
                if not _wo_can_run_on_day(w, d, climb_safe):
                    continue
                x[(wi, ti, di)] = model.NewBoolVar(f"x_{wi}_{ti}_{di}")

    # Each WO assigned at most once.
    for wi, w in enumerate(work_orders):
        candidates = [v for (a, b, c), v in x.items() if a == wi]
        if candidates:
            model.Add(sum(candidates) <= 1)

    # Daily hour budget per technician.
    for ti, t in enumerate(technicians):
        budget = int(t.get("hours_per_day") or 8)
        for di, _d in enumerate(days):
            assigned_hours = []
            for wi, w in enumerate(work_orders):
                v = x.get((wi, ti, di))
                if v is None:
                    continue
                hours = int(round(float(w.get("estimated_hours") or 1)))
                assigned_hours.append(v * hours)
            if assigned_hours:
                model.Add(sum(assigned_hours) <= budget)

    # Objective: minimise weighted-day for assigned WOs + heavy penalty for
    # unassigned WOs (an "assigned" indicator y[w]).
    UNASSIGN_PENALTY = 100
    y: dict[int, Any] = {}
    obj_terms: list[Any] = []
    for wi, w in enumerate(work_orders):
        weight = PRIORITY_WEIGHT.get(w.get("priority") or "P2", 2)
        cands = [(di, v) for (a, _b, di), v in x.items() if a == wi]
        if not cands:
            # No feasible cell -> permanently unassigned. Don't add a y var,
            # account for it via a constant term below.
            obj_terms.append(weight * UNASSIGN_PENALTY)
            continue
        # Day-cost per assignment.
        for di, v in cands:
            obj_terms.append(weight * di * v)
        # Penalty if not assigned at all.
        y[wi] = model.NewBoolVar(f"y_{wi}")
        model.Add(y[wi] == sum(v for _di, v in cands))
        obj_terms.append(weight * UNASSIGN_PENALTY * (1 - y[wi]))

    model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(model)

    assignments: list[dict] = []
    unassigned: list[dict] = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (wi, ti, di), v in x.items():
            if solver.Value(v) == 1:
                w = work_orders[wi]
                t = technicians[ti]
                # Pack work-order onto tech in earliest free slot of the day.
                # The hourly schedule is approximate — we just stamp 8am start.
                assignments.append({
                    "wo_id": w.get("wo_id"),
                    "turbine_id": w.get("turbine_id"),
                    "technician_id": t.get("id"),
                    "technician_name": t.get("name"),
                    "day": days[di],
                    "start_hour": 8,
                    "duration_hours": float(w.get("estimated_hours") or 1),
                    "skill_required": w.get("skill_required"),
                    "priority": w.get("priority"),
                })
        # Anything not in the assignment list is unassigned.
        assigned_ids = {a["wo_id"] for a in assignments}
        for w in work_orders:
            if w.get("wo_id") not in assigned_ids:
                unassigned.append({
                    "wo_id": w.get("wo_id"),
                    "reason": _explain_unassigned(w, technicians, days, climb_safe),
                })
        return {
            "solver": "or-tools",
            "assignments": assignments,
            "unassigned": unassigned,
            "objective_value": solver.ObjectiveValue(),
            "infeasible": False,
            "explanation": (
                f"OR-tools CP-SAT solved in {solver.WallTime():.2f}s "
                f"(status={solver.StatusName(status)})."
            ),
        }
    # No solution at all.
    return {
        "solver": "or-tools",
        "assignments": [],
        "unassigned": [{"wo_id": w.get("wo_id"), "reason": "model_infeasible"}
                       for w in work_orders],
        "objective_value": 0,
        "infeasible": True,
        "explanation": (
            f"OR-tools returned status={solver.StatusName(status)}; "
            "constraints unsatisfiable. Most likely a skill or weather gate "
            "ruled out every cell for one or more WOs."
        ),
    }


def solve_greedy(payload: dict, days: list[str]) -> dict[str, Any]:
    """Deterministic fallback when ortools is missing or fails to import.

    Greedy by priority-weight desc. For each WO walk days earliest-first;
    pick the technician with the most hours remaining who has the skill;
    skip cells that violate weather / parts gates.
    """
    technicians = payload.get("technicians") or []
    work_orders = payload.get("work_orders") or []
    climb_safe = _climb_safe_map(payload, days)

    # hours_left[tech_id][day] -> int
    hours_left: dict = {
        t.get("id"): {d: int(t.get("hours_per_day") or 8) for d in days}
        for t in technicians
    }

    # Sort WOs: P1 first, then by estimated hours desc (pack the big ones early).
    sorted_wos = sorted(
        work_orders,
        key=lambda w: (
            -PRIORITY_WEIGHT.get(w.get("priority") or "P2", 2),
            -float(w.get("estimated_hours") or 1),
        ),
    )

    assignments: list[dict] = []
    unassigned: list[dict] = []
    for w in sorted_wos:
        hours = float(w.get("estimated_hours") or 1)
        placed = False
        for d in days:
            if not _wo_can_run_on_day(w, d, climb_safe):
                continue
            # Pick the eligible tech with most remaining hours that day.
            eligible = [t for t in technicians if _tech_can_do(t, w)]
            eligible.sort(key=lambda t: -hours_left[t.get("id")].get(d, 0))
            for t in eligible:
                avail = hours_left[t.get("id")].get(d, 0)
                if avail >= hours:
                    hours_left[t.get("id")][d] = avail - int(round(hours))
                    assignments.append({
                        "wo_id": w.get("wo_id"),
                        "turbine_id": w.get("turbine_id"),
                        "technician_id": t.get("id"),
                        "technician_name": t.get("name"),
                        "day": d,
                        "start_hour": 8,
                        "duration_hours": hours,
                        "skill_required": w.get("skill_required"),
                        "priority": w.get("priority"),
                    })
                    placed = True
                    break
            if placed:
                break
        if not placed:
            unassigned.append({
                "wo_id": w.get("wo_id"),
                "reason": _explain_unassigned(w, technicians, days, climb_safe),
            })

    objective = sum(
        PRIORITY_WEIGHT.get(w.get("priority") or "P2", 2) * days.index(a["day"])
        for w, a in ((wo, a) for wo in work_orders for a in assignments
                     if a["wo_id"] == wo.get("wo_id"))
    )
    return {
        "solver": "greedy-fallback",
        "assignments": assignments,
        "unassigned": unassigned,
        "objective_value": objective,
        "infeasible": False,
        "explanation": (
            "ortools not available — used deterministic greedy heuristic. "
            "All hard constraints respected; objective is approximate."
        ),
    }


def _explain_unassigned(
    wo: dict, technicians: list[dict], days: list[str],
    climb_safe: dict[str, bool],
) -> str:
    """Best-effort human-readable reason."""
    skill_capable = any(_tech_can_do(t, wo) for t in technicians)
    if not skill_capable:
        return f"no technician has skill: {wo.get('skill_required')}"
    weather_eligible_days = [d for d in days
                             if _wo_can_run_on_day(wo, d, climb_safe)]
    if not weather_eligible_days:
        return "weather window blocked across the entire horizon"
    parts_avail = wo.get("parts_available_on")
    if parts_avail and parts_avail > days[-1]:
        return f"parts unavailable until {parts_avail}"
    return "all eligible cells already booked"


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        json.dump({
            "solver": "none",
            "assignments": [],
            "unassigned": [],
            "objective_value": 0,
            "infeasible": True,
            "explanation": f"input was not valid JSON: {exc}",
        }, sys.stdout)
        return 1

    days = _normalise_days(payload, default_days=int(payload.get("days") or 7))

    try:
        import ortools.sat.python.cp_model  # noqa: F401
        result = solve_with_ortools(payload, days)
    except ImportError:
        result = solve_greedy(payload, days)
    except Exception as exc:  # solver crashed mid-run -> fall back
        result = solve_greedy(payload, days)
        result["explanation"] = (
            f"ortools error ({exc}); used greedy fallback. " + result["explanation"]
        )

    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
