"""One-off — inject a uniform contract-type-aware header into 5 PPA-biased agents."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "packages/db/seeds/agents"

HEADER = """
  ## Branch on contract_type — read this first

  The caller passes a `contract_type` (one of ppa | gas | tolling | vppa |
  metals). Specialise your output to the family in front of you. The four
  market-data families you reach for:

  - `ppa` / `vppa` / `tolling` — entso_e, ember_climate, ecb_rates, the
    EU power curve, EUAs. Units are MW / MWh / EUR per MWh.
  - `gas` — eia_open_data (HH, propane, WTI, Brent), nbp_henry_hub_jkm,
    ttf_settlement, lng_freight_baltic. Units are MMBtu / therm / mcm,
    USD per MMBtu, EUR per MWh thermal.
  - `metals` — lbma_gold_fix, lbma_silver_price, lppm_pgm_fix,
    comex_metals_settlement, shanghai_gold_benchmark, gold_lease_rate,
    metals_etf_flows. Units are troy oz, USD per troy oz, fineness as a
    decimal (0..1).

  If `contract_type` is missing, infer it from the contract text before
  doing any other work.
"""

TARGETS = {
    "contractiq_hedge_advisor.yaml": "  ## Available Tools",
    "contractiq_market_monitor.yaml": "  ## Available Tools",
    "contractiq_market_simulator.yaml": "  ## Available Tools",
    "contractiq_portfolio_valuator.yaml": "  ## Available Tools",
    "contractiq_price_forecaster.yaml": "  ## Available Tools",
    "contractiq_stress_test.yaml": "  ## Available Tools",
}


def main() -> int:
    touched = 0
    for fname, anchor in TARGETS.items():
        p = ROOT / fname
        if not p.exists():
            print(f"skip — missing: {fname}", file=sys.stderr)
            continue
        text = p.read_text(encoding="utf-8")
        if "## Branch on contract_type" in text:
            print(f"skip — already injected: {fname}")
            continue
        if anchor not in text:
            print(f"skip — anchor not found in {fname}", file=sys.stderr)
            continue
        text = text.replace(anchor, HEADER.rstrip() + "\n\n" + anchor, 1)
        p.write_text(text, encoding="utf-8")
        touched += 1
        print(f"injected: {fname}")
    print(f"\ntouched {touched} agent yamls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
