"""Clean spark spread desk: margin, stress margin and spread option value per delivery month."""

import json
import math
import sys

MARKER = "SPARK_DESK_V1"


def num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def kirk(power, gas_leg, strike, t, vol_p, vol_g, rho):
    # Kirk's approximation for an option on power - gas_leg - strike
    if t <= 0 or power <= 0 or gas_leg + strike <= 0:
        return max(power - gas_leg - strike, 0.0)
    w = gas_leg / (gas_leg + strike)
    sig = math.sqrt(vol_p**2 - 2 * rho * vol_p * vol_g * w + (vol_g * w) ** 2)
    sd = sig * math.sqrt(t)
    d1 = (math.log(power / (gas_leg + strike)) + 0.5 * sd**2) / sd
    return power * norm_cdf(d1) - (gas_leg + strike) * norm_cdf(d1 - sd)


def price(p):
    power = num(p.get("power_price"))
    if power is None:
        raise ValueError("power_price is required")
    heat_rate = num(p.get("heat_rate"), 2.0)
    carbon = num(p.get("carbon_price"), 0.0)
    ef = num(p.get("emission_factor"), 0.365)
    mw = num(p.get("volume_mw"), 100.0)
    hours = num(p.get("hours_per_month"), 730.0)
    vol_g = num(p.get("gas_vol"), 0.5)
    vol_p = num(p.get("power_vol"), 0.45)
    rho = num(p.get("correlation"), 0.7)

    curve = p.get("gas_curve")
    if isinstance(curve, str):
        curve = json.loads(curve)
    if isinstance(curve, dict):
        curve = curve.get("points") or []
    if not curve:
        gas = num(p.get("gas_price"))
        if gas is None:
            raise ValueError("give gas_curve points or a gas_price")
        curve = [{"tenor": f"M+{i + 1}", "expected": gas, "p90": gas * (1 + vol_g * 0.4)} for i in range(int(num(p.get("months"), 12)))]

    carbon_cost = carbon * ef
    months, margin, stress, option = [], 0.0, 0.0, 0.0
    for i, pt in enumerate(curve):
        gas = num(pt.get("expected"), num(pt.get("p50")))
        gas_hi = num(pt.get("p90"), gas)
        t = (i + 1) / 12.0
        css = power - heat_rate * gas - carbon_cost
        css_stress = power - heat_rate * gas_hi - carbon_cost
        opt = kirk(power, heat_rate * gas, carbon_cost, t, vol_p, vol_g, rho)
        m = css * mw * hours
        months.append({
            "tenor": pt.get("tenor", f"M+{i + 1}"),
            "gas_expected": round(gas, 2),
            "gas_p90": round(gas_hi, 2),
            "clean_spark_spread": round(css, 2),
            "stress_spread": round(css_stress, 2),
            "option_value_per_mwh": round(opt, 2),
            "margin_eur": round(m, 0),
        })
        margin += m
        stress += css_stress * mw * hours
        option += opt * mw * hours

    negative = [m["tenor"] for m in months if m["stress_spread"] < 0]
    notional = power * mw * hours * len(months)
    return {
        "marker": MARKER,
        "months": months,
        "expected_margin_eur": round(margin, 0),
        "stress_margin_eur": round(stress, 0),
        "option_value_eur": round(option, 0),
        "months_negative_under_stress": negative,
        "months_negative_count": len(negative),
        "position_notional_eur": round(notional, 0),
        "daily_return_vol": round(math.sqrt(vol_p**2 + vol_g**2 - 2 * rho * vol_p * vol_g) / math.sqrt(252), 6),
    }


def main():
    payload = json.loads(sys.stdin.read().strip() or "{}")
    try:
        out = price(payload)
    except (ValueError, TypeError) as e:
        print(f"bad input: {e}", file=sys.stderr)
        sys.exit(2)
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
