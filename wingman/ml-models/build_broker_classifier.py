"""Train and pickle the Wingman broker-email intent classifier.

A tiny but real sklearn pipeline (TF-IDF + Logistic Regression) that
classifies broker email text into one of the typed intents Wingman
recognises:
  - offer       (firm or indication to sell)
  - bid         (asking to buy)
  - counter     (response to a previous offer/bid with a different price)
  - quarterly   (multi-month slate / strip)
  - spot        (distressed / immediate-window)

Plus per-email confidence and an estimated `urgency` (0..1) from
keyword heuristics applied at inference time.

The training corpus below is synthetic but matches the linguistic shape
of real broker comms — short messages, FOB/CIF/CFR jargon, validity
clauses, counterparty cues. Re-train any time you have real anonymised
samples; the framework is the same.

Output:
    wingman/ml-models/broker_intent_classifier.pkl
    wingman/ml-models/broker_intent_classifier.meta.json

Deploy via the platform's /api/ml-models upload endpoint or the
'ML Models' page in the Abenix UI; reference the resulting model_id
in the wingman-broker-classifier agent's ml_model tool args.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

OUT = Path(__file__).parent

# Each row: (text, intent). Real demos re-train on real anonymised broker
# emails. The corpus is intentionally chunky — short, tonal, jargon-rich
# — so TF-IDF + LR captures the shape rather than memorising tokens.
TRAIN: list[tuple[str, str]] = [
    # offer (firm / indication to sell)
    (
        "25kt propane FOB Houston for Aug-15 lifting indication 610 vs USGC mean - 2 firm by EOD",
        "offer",
    ),
    (
        "Offer 30kt USGC propane Sep-01 fixed 605 mt FOB subject vessel approval",
        "offer",
    ),
    ("We have 22kt FOB Antwerp for Jul-22 lifting at 580 mt firm 24h", "offer"),
    (
        "Indication only 18kt Mont Belvieu propane Aug-08 at 615 mt subj prior sale",
        "offer",
    ),
    ("Selling 12kt FOB Singapore Aug-10 to 14, fixed 645 mt PFOB", "offer"),
    ("Firm offer 50kt USGC propane Q3 strip MoM USGC mean - 1 50/50 split", "offer"),
    (
        "12kt mixed C3/C4 60/40 split FOB Antwerp Jun-22 to Jun-26 fixed 565 mt firm 14:00 GMT today",
        "offer",
    ),
    (
        "Available 25kt propane CFR Daesan Sep-01 to Sep-08 at Saudi CP + 2 firm 24h",
        "offer",
    ),
    ("Selling 22kt FOB Houston Jul-30 fixed 620 mt subj quality", "offer"),
    ("Firm 18kt Belvieu propane Aug-15 fixed 610 mt", "offer"),
    # bid (asking to buy)
    (
        "Looking for 22kt propane CFR Chiba Sep-01 to Sep-10 narrow window floating Saudi CP - 5",
        "bid",
    ),
    ("Bid wanted 25kt FOB USGC for Aug lifting target 600 mt", "bid"),
    ("Need 30kt CFR Singapore Oct narrow window CP basis", "bid"),
    ("Buyer interest 18kt propane Tokyo Sep delivery floating", "bid"),
    ("Looking for offers 40kt CFR Daesan Q4 strip MoM CP basis", "bid"),
    ("End-buyer indication 25kt CFR Far East Aug-25 to Aug-30 floating", "bid"),
    ("Bid level 595 mt FOB Houston Aug-22 firm subj counterparty approval", "bid"),
    ("Need 20kt propane Antwerp Jun lifting fixed prefer 575 mt", "bid"),
    ("Looking for offers 10kt FOB Mont Belvieu spot 24h", "bid"),
    ("Buyer needs 30kt Daesan Oct CP - 8 floating", "bid"),
    # counter (counter to a previous offer/bid)
    (
        "Counter to your last 50kt USGC propane FOB Sep-01 lifting target Chiba Sep-25 buyer offers 640 mt CFR Chiba",
        "counter",
    ),
    ("Re your offer counter at 605 mt FOB Houston same volume Aug-10", "counter"),
    ("Will counter at CP - 3 instead of CP - 2 same lift window", "counter"),
    ("Counter 22kt 575 mt fixed FOB Antwerp same Jul window valid 30 mins", "counter"),
    ("Re your bid counter at 620 mt FOB Belvieu fixed", "counter"),
    (
        "Counter on USGC->FE arb buyer offers 640 mt CFR Chiba freight on their account",
        "counter",
    ),
    ("Re offer 25kt counter at 608 mt subj prior sale", "counter"),
    ("Counter 50kt Q4 strip MoM USGC mean - 0.5 instead of - 1", "counter"),
    # quarterly (multi-month slate)
    (
        "Q4 quarterly slate Oct lifting 30kt USGC propane fixed 605 mt FOB Nov 30kt fixed 612 mt Dec 30kt formula",
        "quarterly",
    ),
    ("Q1 strip 90kt Houston propane MoM USGC mean - 1 firm 48h", "quarterly"),
    ("Multi-month deal 60kt over Jul Aug Sep at fixed 600 mt FOB", "quarterly"),
    ("Yearly slate 360kt 2026 USGC propane MoM CP - 2", "quarterly"),
    ("Q3 quarterly 90kt Antwerp lifting Jul Aug Sep fixed 580 585 590", "quarterly"),
    ("H2 strip 180kt USGC propane MoM at USGC mean", "quarterly"),
    # spot (distressed / immediate)
    (
        "Distressed spot offer vessel in port must lift 12kt mixed C3/C4 FOB Antwerp Jun-22 fixed 565 mt 14:00 GMT today",
        "spot",
    ),
    ("Immediate window 8kt FOB Houston Jul-08 to Jul-10 firm 2h 590 mt", "spot"),
    ("Vessel arriving Antwerp Jun-25 must place 10kt fixed 555 mt firm 30 min", "spot"),
    ("Cargo distressed must move today 14kt FOB Belvieu 595 mt subj quality", "spot"),
    ("Spot opportunity 6kt FOB Houston Jul-12 firm 1h", "spot"),
    (
        "Cancellation released 15kt FOB Antwerp Jun lifting must clear 24h fixed 570 mt",
        "spot",
    ),
]


def train_and_save() -> None:
    texts = [t for t, _ in TRAIN]
    labels = [y for _, y in TRAIN]

    pipe = Pipeline(
        [
            (
                "vec",
                TfidfVectorizer(ngram_range=(1, 2), max_features=4000, lowercase=True),
            ),
            ("clf", LogisticRegression(max_iter=400, C=2.0)),
        ]
    )
    pipe.fit(texts, labels)

    out_pkl = OUT / "broker_intent_classifier.pkl"
    out_meta = OUT / "broker_intent_classifier.meta.json"
    with out_pkl.open("wb") as f:
        pickle.dump(pipe, f)

    classes = list(pipe.named_steps["clf"].classes_)
    meta = {
        "name": "wingman-broker-intent-classifier",
        "version": "1.0.0",
        "framework": "sklearn",
        "description": (
            "Classifies a broker email body into one of "
            "{offer, bid, counter, quarterly, spot}. Trained on a curated "
            "synthetic corpus that matches the linguistic shape of real "
            "broker comms (FOB/CFR jargon, validity clauses, "
            "counterparty cues). Re-train on real anonymised samples in "
            "production for higher accuracy."
        ),
        "input_schema": {
            "features": ["text"],
            "types": ["str"],
            "example": [
                "25kt propane FOB Houston for Aug-15 indication 610 vs USGC mean - 2 firm by EOD"
            ],
        },
        "output_schema": {
            "type": "classification",
            "classes": classes,
            "returns": "predicted intent + per-class probability",
        },
        "tags": ["wingman", "trading", "broker-comms", "intent"],
        "training": {
            "samples": len(TRAIN),
            "algorithm": "TF-IDF + Logistic Regression",
            "ngram": "1-2",
        },
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    print(f"Wrote {out_pkl} ({out_pkl.stat().st_size} bytes)")
    print(f"Wrote {out_meta}")
    print(f"Classes: {classes}")


if __name__ == "__main__":
    train_and_save()
