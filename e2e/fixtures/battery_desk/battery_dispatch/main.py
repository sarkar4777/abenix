"""Battery dispatch for one hour: discharge when power is dear, charge when it is cheap."""

import json
import sys

MARKER = "BATTERY_DISPATCH_V1"
SOC_MIN = 10.0
SOC_MAX = 90.0


def num(p, key, default=None):
    v = p.get(key, default)
    if v is None:
        raise ValueError(f"{key} is required")
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number")


def dispatch(p):
    price = num(p, "price_forecast")
    soc = num(p, "soc_pct")
    capacity = num(p, "capacity_mwh")
    max_mw = num(p, "max_mw")
    high = num(p, "discharge_above", 90.0)
    low = num(p, "charge_below", 45.0)
    if capacity <= 0 or max_mw <= 0:
        raise ValueError("capacity_mwh and max_mw must be above zero")

    # one hour, so MW and MWh are the same number
    if price >= high and soc > SOC_MIN:
        mw = min(max_mw, capacity * (soc - SOC_MIN) / 100)
        action, revenue = "discharge", mw * price
        reason = f"Price {price:.1f} EUR/MWh is at or above {high:.0f}, sell {mw:.1f} MW"
    elif price <= low and soc < SOC_MAX:
        mw = min(max_mw, capacity * (SOC_MAX - soc) / 100)
        action, revenue = "charge", -mw * price
        reason = f"Price {price:.1f} EUR/MWh is at or below {low:.0f}, buy {mw:.1f} MW"
    else:
        mw, action, revenue = 0.0, "hold", 0.0
        reason = f"Price {price:.1f} EUR/MWh is between {low:.0f} and {high:.0f}, hold"

    mw = round(mw, 1)
    revenue = round(revenue, 0)
    band = abs(revenue) * 0.15
    return {
        "marker": MARKER,
        "action": action,
        "mw": mw,
        "soc_pct": soc,
        "price_forecast": round(price, 2),
        "expected_revenue_eur": revenue,
        "revenue_low_eur": round(revenue - band, 0),
        "revenue_high_eur": round(revenue + band, 0),
        "reason": reason,
    }


def main():
    payload = json.loads(sys.stdin.read().strip() or "{}")
    try:
        out = dispatch(payload)
    except ValueError as e:
        print(f"bad input: {e}", file=sys.stderr)
        sys.exit(2)
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
