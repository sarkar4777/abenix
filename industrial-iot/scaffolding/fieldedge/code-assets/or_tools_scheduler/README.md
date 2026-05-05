# or_tools_scheduler

Constraint-based 7-day scheduler for wind-farm field maintenance crews.

## Usage

```bash
echo '{"technicians":[...], "work_orders":[...], "weather_forecast":[...]}' \
  | python main.py
```

Stdin: one JSON object. Stdout: one JSON object (assignments + unassigned).

## Inputs

| field | required | description |
| --- | --- | --- |
| `technicians[]` | yes | `id`, `name`, `skills[]`, `shift`, `hours_per_day` |
| `work_orders[]` | yes | `wo_id`, `turbine_id`, `skill_required`, `estimated_hours`, `priority` (P1/P2/P3), optional `weather_sensitive`, `parts_available_on` |
| `weather_forecast[]` | optional | one entry per day: `day` (ISO date), `wind_mps`, `precip`, `climb_safe` |
| `days` | optional | horizon length, default 7 |
| `previous_schedule` | optional | passed through, used by the LLM narrator for delta reporting |

## Hard constraints

- Each WO is assigned at most once.
- Technician must have **every** skill listed in `skill_required`.
- Daily hours per technician do not exceed `hours_per_day`.
- WOs flagged `weather_sensitive` only land on days with `climb_safe == True`
  (or with `wind_mps <= 12` and `precip in (none, "")` if `climb_safe` not supplied).
- WO not scheduled before its `parts_available_on` date.

## Soft objective

`minimise sum(priority_weight * day_index)` plus a heavy penalty for any
unassigned WO scaled by priority. P1 weight = 4, P2 = 2, P3 = 1.

## Solver behaviour

1. Tries OR-tools CP-SAT (`ortools.sat.python.cp_model`).
2. On `ImportError` falls back to a deterministic greedy heuristic that
   respects every hard constraint — the technician still gets a usable
   plan; the `solver` field in the output flags the fallback so the UI can
   surface it.
3. On any solver runtime crash (`Exception`), also falls back to greedy
   and prepends the error to `explanation`.

## Output shape

```json
{
  "solver": "or-tools" | "greedy-fallback" | "none",
  "assignments": [
    {
      "wo_id": "WO-007",
      "turbine_id": "TURB-03",
      "technician_id": "T-01",
      "technician_name": "M. Patel",
      "day": "2026-05-05",
      "start_hour": 8,
      "duration_hours": 6,
      "skill_required": "blade-repair",
      "priority": "P1"
    }
  ],
  "unassigned": [
    { "wo_id": "WO-013", "reason": "weather window blocked across the entire horizon" }
  ],
  "objective_value": 47,
  "infeasible": false,
  "explanation": "OR-tools CP-SAT solved in 0.18s (status=OPTIMAL)."
}
```

## Why CP-SAT

Wind-farm scheduling is a small (typically <100 WOs over 7 days) but
constraint-heavy problem with discontinuous feasibility regions
(weather windows, parts logistics). MIP linearisation works but CP-SAT
handles the categorical skill-match and per-day capacity bins more
naturally and converges in well under a second on realistic inputs.
