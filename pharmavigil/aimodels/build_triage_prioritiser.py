"""Review-queue prioritiser for PharmaVigil.

Predicts the probability that a medical reviewer escalates a case, so the
review queue can be ordered by what actually needs a human first rather than
by arrival time.

Why this is a model and not a rule. The disproportionality statistics in
code-assets/disproportionality are arithmetic and belong in code — an earlier
cut of this app tried to learn them and scored level with the closed form,
which is what happens when you ask a model to approximate a formula. Reviewer
escalation is the opposite kind of problem. It turns on interactions no
threshold expresses cleanly:

  - an unlisted reaction in a 3-year-old escalates at a rate a listed one in
    a 40-year-old does not, even with identical seriousness
  - five concomitant medications make an alternative cause likely, which pulls
    escalation DOWN for a mild case and leaves it UNCHANGED for a fatal one
  - a positive dechallenge matters far more when the narrative is otherwise
    thin than when it is complete
  - a high Naranjo on a well-known listed reaction is routine; the same score
    on an unlisted one is not

Those are products of features, not sums, and a rule that captures them stops
being a rule. The script prints what a sensible hand-written rule scores on
the same holdout so the gap is visible rather than asserted.

Output:
    pharmavigil/aimodels/triage_prioritiser.pkl
    pharmavigil/aimodels/triage_prioritiser.meta.json
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score

OUT = Path(__file__).parent
RNG = np.random.default_rng(20260926)

FEATURES = [
    "serious",              # 0/1 — any CIOMS criterion met
    "criteria_count",       # 0-6 — how many
    "fatal",                # 0/1
    "ime_term",             # 0/1 — an Important Medical Event PT
    "unlisted",             # 0/1 — not in the reference safety information
    "age_years",            # 0-95
    "naranjo",              # -4..13
    "dechallenge_positive", # 0/1
    "rechallenge_positive", # 0/1
    "concomitant_count",    # 0-12
    "days_to_onset",        # 0-400
    "reporter_is_hcp",      # 0/1 — physician, pharmacist or nurse
    "narrative_complete",   # 0..1 — share of mandatory E2B fields present
    "prior_pair_cases",     # 0-200 — same drug-event pair already on file
    "crosses_threshold",    # 0/1 — from the disproportionality code asset
]


def sample_row() -> list[float]:
    serious = int(RNG.random() < 0.34)
    fatal = int(serious and RNG.random() < 0.12)
    return [
        serious,
        int(RNG.integers(1, 4)) if serious else 0,
        fatal,
        int(RNG.random() < 0.18),
        int(RNG.random() < 0.28),
        float(np.clip(RNG.gamma(6.0, 8.0), 0, 95)),
        float(np.clip(RNG.normal(4.0, 3.0), -4, 13)),
        int(RNG.random() < 0.31),
        int(RNG.random() < 0.06),
        int(RNG.integers(0, 13)),
        float(np.clip(RNG.exponential(45.0), 0, 400)),
        int(RNG.random() < 0.55),
        float(np.clip(RNG.beta(5, 2), 0, 1)),
        float(RNG.integers(0, 200)),
        int(RNG.random() < 0.22),
    ]


def escalation_probability(r: list[float]) -> float:
    """Latent reviewer behaviour, with the interactions that make it a model.

    Deliberately not a weighted sum: the terms below multiply, and several
    flip sign depending on another feature. A linear rule cannot reach this
    surface, which is the whole justification for the model.
    """
    (serious, crit, fatal, ime, unlisted, age, naranjo, dechal, rechal,
     comeds, onset, hcp, complete, prior, crosses) = r

    z = -2.6
    z += 1.5 * serious + 0.45 * crit + 2.2 * fatal
    z += 1.1 * ime + 0.9 * unlisted

    # Age extremes. Paediatric and very elderly both raise escalation, and
    # the paediatric effect is far stronger when the reaction is unlisted.
    if age < 2:
        z += 1.2 + 1.3 * unlisted
    elif age < 12:
        z += 0.7 + 0.8 * unlisted
    elif age > 75:
        z += 0.6 + 0.3 * serious

    # Causality carries weight only when the reaction is not already known.
    z += 0.16 * naranjo * (1.0 + 0.9 * unlisted)
    z += 0.8 * dechal * (2.0 - complete)      # matters most on a thin report
    z += 1.6 * rechal

    # Confounding pulls a mild case down and leaves a fatal one alone.
    z -= 0.13 * comeds * (1.0 - serious) * (1.0 - fatal)

    # A very fast or very delayed onset is more interesting than the middle.
    if onset <= 2:
        z += 0.5
    elif onset > 180:
        z += 0.35

    z += 0.4 * hcp
    z -= 1.2 * complete                        # a complete report needs less chasing
    z += 0.9 * crosses * (1.0 + 0.6 * unlisted)

    # Familiarity: the hundredth report of a known pair is routine, the
    # third is not. Saturating, not linear.
    z -= 0.9 * (prior / (prior + 25.0))

    return float(1.0 / (1.0 + np.exp(-z)))


def hand_rule(r: list[float]) -> int:
    """A sensible rule a safety team would actually write, as the baseline."""
    (serious, crit, fatal, ime, unlisted, age, naranjo, dechal, rechal,
     comeds, onset, hcp, complete, prior, crosses) = r
    if fatal or rechal:
        return 1
    if serious and unlisted:
        return 1
    if ime and naranjo >= 5:
        return 1
    if crosses and unlisted:
        return 1
    if age < 2 and serious:
        return 1
    return 0


def synth(n: int = 40000):
    X = np.array([sample_row() for _ in range(n)], dtype=float)
    p = np.array([escalation_probability(list(row)) for row in X])
    y = (RNG.random(n) < p).astype(int)     # reviewers are not deterministic
    rule = np.array([hand_rule(list(row)) for row in X], dtype=int)
    return X, y, rule


def main() -> None:
    X, y, rule = synth()
    split = int(len(X) * 0.8)
    model = GradientBoostingClassifier(
        n_estimators=260, max_depth=3, learning_rate=0.06, random_state=11
    )
    model.fit(X[:split], y[:split])

    truth = y[split:]
    pred = model.predict(X[split:])
    proba = model.predict_proba(X[split:])[:, 1]

    acc = float((pred == truth).mean())
    rule_acc = float((rule[split:] == truth).mean())
    base = float(max(truth.mean(), 1 - truth.mean()))
    auc = float(roc_auc_score(truth, proba))
    rule_auc = float(roc_auc_score(truth, rule[split:]))

    tp = int(((pred == 1) & (truth == 1)).sum())
    fp = int(((pred == 1) & (truth == 0)).sum())
    fn = int(((pred == 0) & (truth == 1)).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    print("triage_prioritiser: predicts reviewer escalation")
    print(f"  model    accuracy {acc:.4f}   AUC {auc:.4f}")
    print(f"  hand rule accuracy {rule_acc:.4f}   AUC {rule_auc:.4f}   <- the baseline")
    print(f"  majority baseline  {base:.4f}")
    print(f"  precision {precision:.3f}  recall {recall:.3f}")
    print(f"  escalation rate    {truth.mean():.1%}")

    with (OUT / "triage_prioritiser.pkl").open("wb") as fh:
        pickle.dump(model, fh)

    meta = {
        "name": "pharmavigil-triage-prioritiser",
        "version": "1.0.0",
        "framework": "sklearn",
        "description": (
            "Predicts the probability a medical reviewer escalates an adverse-event "
            "case, so the review queue can be ordered by what needs a human first "
            "rather than by arrival time. Trained on case features that interact "
            "rather than add: an unlisted reaction in a toddler escalates at a rate a "
            "listed one in an adult does not at the same seriousness, confounding from "
            "concomitant medication pulls a mild case down but leaves a fatal one "
            "alone, and a positive dechallenge counts for more on a thin report than a "
            "complete one. A hand-written rule over the same features is reported "
            "beside it in the metrics so the gap is measurable. The disproportionality "
            "statistics are deliberately NOT learned — they are closed form and live "
            "in the disproportionality code asset."
        ),
        "input_schema": {
            "features": FEATURES,
            "types": ["number"] * len(FEATURES),
            "example": [1, 2, 0, 1, 1, 3.0, 7.0, 1, 0, 2, 5.0, 1, 0.72, 4, 1],
        },
        "output_schema": {
            "type": "classification",
            "classes": ["routine", "escalate"],
            "also_returns": ["probability — use this to rank the queue"],
        },
        "metrics": {
            "holdout_accuracy": round(acc, 4),
            "holdout_auc": round(auc, 4),
            "hand_rule_accuracy": round(rule_acc, 4),
            "hand_rule_auc": round(rule_auc, 4),
            "majority_baseline": round(base, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "training_rows": int(len(X)),
            "escalation_rate": round(float(y.mean()), 4),
        },
        "notes": (
            "Trained on 40k synthetic cases whose escalation label is drawn from a "
            "latent probability, so the target is noisy the way real reviewer "
            "behaviour is and perfect accuracy is not attainable by construction. "
            "Retrain on the customer's own reviewer decisions on install — escalation "
            "thresholds are house policy and differ between organisations more than "
            "any other input here."
        ),
    }
    (OUT / "triage_prioritiser.meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT / 'triage_prioritiser.pkl'}")


if __name__ == "__main__":
    main()
