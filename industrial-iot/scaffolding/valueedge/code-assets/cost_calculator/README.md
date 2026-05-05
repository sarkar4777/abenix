# valueedge-cost-calculator

Stdin → stdout offshore-wind cost calculator used by the
ValueEdge tab + iot-valueedge-pipeline.

Reads ONE JSON scenario object on stdin, returns a JSON cost block
on stdout. Coefficients are aligned to BNEF/IRENA 2026 ranges
(see `ve-knw-006` in the linked KB collection).

## Inputs

```
{
  "id": "S1",
  "turbine_count": 13,
  "turbine_rating_mw": 15,
  "foundation_type": "monopile" | "jacket" | "floating-semisub" | "floating-spar",
  "water_depth_m": 28,
  "distance_to_shore_km": 130,
  "array_voltage_kv": 66,
  "export_topology": "HVAC-via-OSS" | "HVDC-monopolar" | ...,
  "offshore_substations": 1
}
```

## Outputs

```
{
  "result": {
    "id": "S1",
    "capacity_mw": 195.0,
    "capex_musd": 612.4,
    "co2_kt": 290.1,
    "om_annual_musd": 27.1,
    "irr_pct": 9.12,
    "lcoe_usd_mwh": 71.4,
    "breakdown_musd": {"turbines": ..., "foundation": ..., ...}
  }
}
```

## Notes

- IRR is solved by Newton iteration over a 25-year annuity profile
  with a flat 4500 full-load-hours and a 75 USD/MWh price floor.
- The HVDC adder kicks in automatically when `export_topology`
  contains `HVDC`.
- numpy is pinned for repeatable runs but the module only uses
  the standard library; the dep is reserved for future
  Monte-Carlo sensitivity additions.
