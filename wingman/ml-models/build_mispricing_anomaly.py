"""Train and pickle the Wingman corridor-spread anomaly detector.

An Isolation Forest over the same 8 features used by the fair-value
regression plus a 9th feature: the trailing-4-week mean spread (so the
detector knows whether the corridor has been *sustained* in this regime
or is bouncing around). Anomaly score in [0,1]; >0.6 means "regime
break, not just a noisy residual" — the fair-value Bayesian residual
won't catch these because the regression slowly drifts to absorb them.

Output:
    wingman/ml-models/mispricing_anomaly.pkl
    wingman/ml-models/mispricing_anomaly.meta.json
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest

OUT = Path(__file__).parent

FEATURE_NAMES = [
    "origin_spot_z",
    "dest_spot_z",
    "freight_per_mt_z",
    "inventory_z",
    "exports_4w_pct",
    "fx_eur_usd_z",
    "weather_dest_gust_z",
    "season_q",
    "spread_4w_mean_z",
]


def _normal_row(rng: np.random.Generator) -> np.ndarray:
    f = np.zeros(len(FEATURE_NAMES))
    f[:7] = rng.normal(0.0, 1.0, 7)
    f[7] = float(rng.integers(1, 5))
    f[8] = rng.normal(0.0, 1.0)
    return f


def _shock_row(rng: np.random.Generator) -> np.ndarray:
    """Construct a regime-break sample: a real-world example would be the
    Strait-of-Hormuz tension or a hurricane shutting USGC export terminals.
    Several features blow out simultaneously in a way `normal` draws don't
    produce in combination."""
    f = _normal_row(rng)
    # Pick a shock kind
    kind = int(rng.integers(0, 3))
    if kind == 0:
        # USGC export shutdown — origin spot collapses, freight spikes
        f[0] = rng.normal(-3.5, 0.6)
        f[2] = rng.normal(2.8, 0.5)
        f[4] = rng.normal(-2.5, 0.4)
    elif kind == 1:
        # NWE cold snap — destination spot up + weather spike
        f[1] = rng.normal(3.0, 0.5)
        f[6] = rng.normal(2.6, 0.4)
    else:
        # Saudi CP shock — Far East spread compresses, inventory bleeds
        f[1] = rng.normal(-2.4, 0.4)
        f[3] = rng.normal(-2.2, 0.3)
        f[8] = rng.normal(-3.0, 0.4)
    return f


def train_and_save() -> None:
    rng = np.random.default_rng(20260511)
    normal = np.asarray([_normal_row(rng) for _ in range(900)])
    # IsolationForest learns from clean data; we DON'T pollute training
    # with shocks. We hold the shocks back to validate detection rate.
    model = IsolationForest(
        n_estimators=200,
        contamination=0.05,
        random_state=42,
    )
    model.fit(normal)

    # Validate on a fresh batch: should flag shocks as anomalies (-1)
    rng_eval = np.random.default_rng(7)
    eval_normal = np.asarray([_normal_row(rng_eval) for _ in range(200)])
    eval_shock = np.asarray([_shock_row(rng_eval) for _ in range(80)])

    pred_normal = model.predict(eval_normal)  # +1 inlier, -1 outlier
    pred_shock = model.predict(eval_shock)
    fp = float(np.mean(pred_normal == -1))
    tp = float(np.mean(pred_shock == -1))

    out_pkl = OUT / "mispricing_anomaly.pkl"
    out_meta = OUT / "mispricing_anomaly.meta.json"
    with out_pkl.open("wb") as f:
        pickle.dump(model, f)

    meta = {
        "name": "wingman-mispricing-anomaly",
        "version": "1.0.0",
        "framework": "sklearn",
        "description": (
            "Isolation Forest over the 9-feature corridor-market vector "
            "(z-scored spots, freight, inventory, exports, FX, weather, "
            "season, trailing-4w-mean spread). Trained on a clean regime; "
            "flags regime breaks that the Bayesian fair-value regression "
            "would slowly drift to absorb. Returns +1 inlier, -1 anomaly, "
            "plus a continuous score_samples in [-1, 0]."
        ),
        "input_schema": {
            "features": FEATURE_NAMES,
            "types": ["float"] * len(FEATURE_NAMES),
            "example": [0.20, 0.40, -0.10, -0.30, 0.12, 0.15, 0.20, 2, 0.10],
        },
        "output_schema": {
            "type": "anomaly_detection",
            "classes": ["inlier", "anomaly"],
            "returns": "predicted label (+1 / -1) and decision_function score",
        },
        "tags": ["wingman", "trading", "mispricing", "anomaly", "isolation-forest"],
        "training": {
            "samples": int(normal.shape[0]),
            "algorithm": "Isolation Forest (n_estimators=200)",
            "synthetic": True,
            "holdout": {
                "false_positive_rate_on_clean": round(fp, 4),
                "true_positive_rate_on_shocks": round(tp, 4),
            },
            "shock_scenarios": [
                "usgc_export_shutdown",
                "nwe_cold_snap",
                "saudi_cp_shock",
            ],
        },
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    print(f"Wrote {out_pkl} ({out_pkl.stat().st_size} bytes)")
    print(f"Wrote {out_meta}")
    print(f"Detection on shocks: TP={tp:.2%}  FP-on-clean={fp:.2%}")


if __name__ == "__main__":
    train_and_save()
