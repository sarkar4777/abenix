# Wingman VaR Simulator (Go)

Monte Carlo Value-at-Risk engine for a Wingman strategy rule.

## What it does
Reads a JSON envelope on stdin (rule + recent EIA spot history), runs
N GBM-walk simulations of the strategy's P&L over the horizon, and
prints a JSON envelope on stdout with `p50_usd`, `p95_usd`, `p99_usd`,
`expected_shortfall_p99_usd`, mean, std, and a 30-bucket histogram.

## Why Go
Compute-heavy by design — 10,000 simulations × 30 daily steps × ~5 RNG
draws per step is a tight Go loop. Roughly 5–10× faster than the same
maths in NumPy at this scale, and ships as a single static binary that
the platform's code-runner sandbox can exec without a Python interpreter.

## Build locally
```
cd wingman/code-assets/var-simulator
go build -o var-simulator .
echo '{"rule":{"corridor_id":"USGC-NWE","side":"sell_forward","size_mt":10000,"trigger":{"metric":"net_arb_per_mt","operator":">","value":30}},"spot_history":[0.92,0.94,0.91,0.89,0.95,0.97,1.01],"horizon_days":30,"n_simulations":10000}' | ./var-simulator
```

## Deploy on the platform (bring-your-own-code path)
1. From this directory, run `zip -r var-simulator.zip .`.
2. Upload via the **Code Runner** page in the Abenix UI (or
   `POST /api/code-assets` via the SDK / curl).
3. The analyzer detects the `go.mod`, picks Go 1.22, builds, and
   registers the asset id.
4. The `wingman-var-simulator` agent (seeded under
   `packages/db/seeds/agents/wingman_var_simulator.yaml`) calls
   `code_asset` with this asset id and feeds in real
   `eia_open_data` history.

The Strategy Lab page in Wingman has a **Run VaR analysis** button
that fires the agent and renders the histogram next to the existing
12-month backtest curve.
