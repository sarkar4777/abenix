"""Disproportionality statistics for a drug-event pair — pure stdlib.

Reads {"a": n, "b": n, "c": n, "d": n} from stdin, where the 2x2 is

                 this event    other events
    this drug        a              b
    other drugs      c              d

and returns the three measures a safety committee reads, each with the bound
that matters more than the point estimate:

    PRR   proportional reporting ratio, 95% lower bound
    ROR   reporting odds ratio, 95% lower bound (Haldane-Anscombe corrected)
    EBGM  shrunk observed-to-expected ratio, and EB05

This is arithmetic, so it lives in code rather than in a model or a prompt.
It is exact, it costs nothing, it returns the same answer every time, and a
reviewer can check it by hand. An earlier cut of this app tried to learn the
same quantities and scored level with the closed form, which is the expected
result when you ask a model to approximate a formula.

The judgement that is NOT arithmetic — whether a reviewer should escalate the
case — is where the ML model earns its place. See aimodels/.
"""

from __future__ import annotations

import json
import math
import sys


def prr(a: float, b: float, c: float, d: float) -> tuple[float, float]:
    """Proportional reporting ratio and its 95% lower bound."""
    if a <= 0 or (a + b) <= 0 or (c + d) <= 0 or c <= 0:
        return 0.0, 0.0
    ratio = (a / (a + b)) / (c / (c + d))
    if ratio <= 0:
        return 0.0, 0.0
    se = math.sqrt(1 / a - 1 / (a + b) + 1 / c - 1 / (c + d))
    return ratio, math.exp(math.log(ratio) - 1.96 * se)


def ror(a: float, b: float, c: float, d: float) -> tuple[float, float]:
    """Reporting odds ratio and its 95% lower bound."""
    if min(a, b, c, d) <= 0:
        # Haldane-Anscombe: half-count correction rather than a zero answer.
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    odds = (a / b) / (c / d)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return odds, math.exp(math.log(odds) - 1.96 * se)


def ebgm(a: float, b: float, c: float, d: float) -> tuple[float, float]:
    """Shrunk observed-to-expected ratio, and its 5th percentile."""
    n = a + b + c + d
    if n <= 0 or a <= 0:
        return 0.0, 0.0
    expected = ((a + b) * (a + c)) / n
    if expected <= 0:
        return 0.0, 0.0
    raw = a / expected
    # Shrink toward the null in proportion to how thin the evidence is.
    weight = a / (a + 2.0)
    shrunk = math.exp(weight * math.log(raw)) if raw > 0 else 0.0
    se = 1 / math.sqrt(a)
    return shrunk, max(0.0, math.exp(math.log(shrunk) - 1.645 * se)) if shrunk > 0 else 0.0


def chi_square(a: float, b: float, c: float, d: float) -> float:
    n = a + b + c + d
    if n <= 0:
        return 0.0
    denom = (a + b) * (c + d) * (a + c) * (b + d)
    if denom <= 0:
        return 0.0
    return (n * (a * d - b * c) ** 2) / denom


def crosses_threshold(a: float, b: float, c: float, d: float) -> int:
    """Today's disproportionality rule. Pure arithmetic, not a prediction.

    Evans criteria, or a DuMouchel-style EB05, and in both cases the lower
    bound has to clear the null. Reported alongside the model so a reviewer
    can see the rule and the forecast disagree when they do.
    """
    p, p_lo = prr(a, b, c, d)
    e, e05 = ebgm(a, b, c, d)
    x2 = chi_square(a, b, c, d)
    if a < 3:
        return 0
    classic = p >= 2.0 and x2 >= 4.0
    bayes = e05 >= 2.0
    bounded = p_lo >= 1.0
    return int((classic or bayes) and bounded)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # noqa: BLE001
        json.dump({"error": f"invalid JSON on stdin: {exc}"}, sys.stdout)
        return

    try:
        a = float(payload["a"]); b = float(payload["b"])
        c = float(payload["c"]); d = float(payload["d"])
    except (KeyError, TypeError, ValueError) as exc:
        json.dump({"error": f"need numeric a, b, c, d: {exc}"}, sys.stdout)
        return

    if min(a, b, c, d) < 0:
        json.dump({"error": "counts cannot be negative"}, sys.stdout)
        return

    p, p_lo = prr(a, b, c, d)
    r, r_lo = ror(a, b, c, d)
    e, e05 = ebgm(a, b, c, d)
    x2 = chi_square(a, b, c, d)
    crosses = crosses_threshold(a, b, c, d)

    if a < 3:
        rule = "a < 3 — too few reports to call, whatever the ratio"
    elif e05 >= 2.0:
        rule = "EB05 >= 2"
    elif p >= 2.0 and x2 >= 4.0 and p_lo >= 1.0:
        rule = "Evans: PRR >= 2, chi-square >= 4, lower bound clears 1"
    elif p >= 2.0 and x2 >= 4.0:
        rule = "PRR and chi-square met but the lower bound does not clear 1"
    else:
        rule = "no rule met"

    json.dump(
        {
            "counts": {"a": a, "b": b, "c": c, "d": d},
            "prr": round(p, 4), "prr_lower_ci": round(p_lo, 4),
            "ror": round(r, 4), "ror_lower_ci": round(r_lo, 4),
            "ebgm": round(e, 4), "eb05": round(e05, 4),
            "chi_square": round(x2, 4),
            "crosses_threshold": bool(crosses),
            "rule": rule,
            # Said plainly because it is the single most common
            # misreading of these numbers.
            "caveat": (
                "Disproportionality measures reporting, not risk. A high ratio "
                "means this pair is reported more often than expected given the "
                "rest of the database. It is not evidence of causality."
            ),
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
