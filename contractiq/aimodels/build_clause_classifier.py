"""Clause-type classifier for ContractIQ.

Given a clause's raw text plus simple structural features, classify it
into one of the ~30 ETRM clause types we extract today. Replaces a per-
clause LLM call in the master extraction pipeline with a fast (<10ms)
TF-IDF + Logistic Regression pass. The pipeline still falls back to the
LLM whenever the classifier's max probability is below a threshold so we
do not silently drop ambiguous clauses.

Trained on synthetic clause text whose surface form matches what shows
up in real PPA / gas / metals / tolling / VPPA contracts. Re-train on
the customer's clause corpus on first install — clauses do not differ
much across jurisdictions but they DO differ across deal types, and the
real win comes from picking up the customer's house naming conventions.

Output:
    contractiq/aimodels/clause_classifier.pkl
    contractiq/aimodels/clause_classifier.meta.json
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

OUT = Path(__file__).parent

# Clause class -> seed phrases that capture the linguistic shape.
# At training time we will randomly combine 1-3 of these per sample with
# small noise so the classifier learns the n-gram fingerprint of each
# class rather than overfitting to literal seeds.
CLAUSE_SEEDS: dict[str, list[str]] = {
    "term_and_termination": [
        "this agreement shall commence on the effective date and continue for a period of",
        "term of years from the effective date unless earlier terminated",
        "either party may terminate this agreement upon written notice",
        "automatic renewal for successive one-year terms",
    ],
    "delivery_point": [
        "the seller shall deliver the product at the delivery point",
        "delivery point means the interconnection facility located at",
        "title to the product shall pass at the delivery point",
        "the parties acknowledge the delivery point is the substation bus",
    ],
    "pricing_formula": [
        "the contract price for each settlement period shall be determined as",
        "fixed price multiplied by the metered quantity",
        "price equals the henry hub index plus a fixed basis",
        "indexed pricing referenced to the LBMA AM fix",
    ],
    "indexation": [
        "the price shall be adjusted annually by the change in CPI",
        "the indexation factor equals the published producer price index",
        "escalation shall apply on each anniversary of the effective date",
        "monthly indexation against the gas reference price",
    ],
    "tolerance_band": [
        "scheduled quantity may vary by up to plus or minus ten percent",
        "tolerance of 5% above or below the nominated daily quantity",
        "imbalance volumes outside the tolerance band shall be cashed out",
    ],
    "minimum_quantity": [
        "the buyer shall purchase a minimum annual contract quantity of",
        "minimum take-or-pay obligation of",
        "annual minimum offtake shall not be less than",
    ],
    "take_or_pay": [
        "buyer shall pay for the contract minimum quantity even if not taken",
        "take-or-pay obligation applies regardless of nomination",
        "shortfall quantities shall be invoiced at the contract price",
    ],
    "force_majeure": [
        "neither party shall be liable for any failure caused by an event of force majeure",
        "force majeure means an event beyond the reasonable control of the party",
        "the affected party shall give prompt written notice of the force majeure event",
        "force majeure does not include lack of finance or change in market price",
    ],
    "credit_support": [
        "buyer shall provide a letter of credit issued by a bank rated",
        "the credit support amount shall be calculated as the mark-to-market exposure",
        "parent company guarantee in form acceptable to the counterparty",
        "credit support requirement may be increased upon downgrade",
    ],
    "change_of_law": [
        "if a change in law materially affects the economics of this agreement",
        "the parties shall negotiate in good faith to restore the economic benefit",
        "change of law includes new regulation that increases the cost of performance",
    ],
    "regulatory_compliance": [
        "each party shall comply with all applicable laws, rules and regulations",
        "the seller represents that it holds all permits required to perform",
        "compliance with environmental and safety regulations",
    ],
    "warranties": [
        "the seller warrants that the product shall meet the quality specifications",
        "warranty period of months from the date of delivery",
        "exclusive remedy for breach of warranty shall be replacement",
    ],
    "liability_cap": [
        "in no event shall either party's aggregate liability exceed",
        "limitation of liability shall not apply to indemnification obligations",
        "neither party shall be liable for indirect, incidental or consequential damages",
    ],
    "indemnity": [
        "the seller shall indemnify and hold harmless the buyer from any claim",
        "indemnification obligations survive termination of this agreement",
        "mutual indemnity for third-party claims arising from gross negligence",
    ],
    "confidentiality": [
        "each party shall maintain the confidentiality of the other party's information",
        "confidential information does not include information already in the public domain",
        "confidentiality obligations shall survive for a period of",
    ],
    "assignment": [
        "this agreement may not be assigned without the prior written consent",
        "assignment to an affiliate or in connection with a merger is permitted",
        "any purported assignment in violation of this clause shall be void",
    ],
    "governing_law": [
        "this agreement shall be governed by and construed in accordance with the laws of",
        "the parties submit to the exclusive jurisdiction of the courts of",
        "any dispute arising out of this agreement shall be referred to arbitration in",
    ],
    "dispute_resolution": [
        "the parties shall first attempt to resolve any dispute through good-faith negotiation",
        "any dispute not resolved within thirty days shall be submitted to binding arbitration",
        "arbitration shall be conducted under the rules of the LCIA",
    ],
    "notices": [
        "all notices required under this agreement shall be in writing",
        "notice shall be deemed given upon receipt by the recipient party",
        "addressed to the addresses set forth in the schedule",
    ],
    "entire_agreement": [
        "this agreement constitutes the entire agreement between the parties",
        "supersedes all prior negotiations, representations and understandings",
        "no modification shall be effective unless in writing and signed",
    ],
    "tax": [
        "all taxes imposed on the seller's revenue shall be borne by the seller",
        "value-added tax shall be added to the contract price where applicable",
        "withholding tax shall be deducted in accordance with applicable law",
    ],
    "settlement": [
        "invoices shall be issued within ten business days of the end of each calendar month",
        "payment shall be made by wire transfer in immediately available funds",
        "disputed invoice amounts shall be paid when due subject to retroactive adjustment",
    ],
    "delivery_obligations": [
        "the seller shall use commercially reasonable efforts to deliver",
        "scheduled delivery quantities for each nomination period",
        "delivery shall be made at the rates set forth in schedule a",
    ],
    "metering": [
        "metering equipment shall be installed and maintained at the delivery point",
        "the metered quantity as recorded by the buyer's metering system shall be definitive",
        "annual calibration of the metering equipment shall be performed by an independent contractor",
    ],
    "insurance": [
        "the seller shall maintain comprehensive general liability insurance",
        "evidence of insurance shall be provided upon request",
        "the buyer shall be named as additional insured on all liability policies",
    ],
    "environmental": [
        "the seller shall be responsible for any environmental compliance arising from",
        "remediation of any environmental contamination caused by the seller",
        "compliance with the Clean Air Act and applicable state regulations",
    ],
    "ip_rights": [
        "all intellectual property rights in the deliverables shall remain with the developer",
        "the buyer shall be granted a non-exclusive license to use",
        "the seller retains ownership of all background intellectual property",
    ],
    "audit_rights": [
        "the buyer shall have the right to audit the seller's records",
        "audit rights may be exercised no more than once per calendar year",
        "audit findings shall be subject to a 30-day cure period",
    ],
    "step_in_rights": [
        "upon the occurrence of an event of default the buyer shall have step-in rights",
        "step-in shall allow the buyer to operate the facility",
        "step-in rights shall be exercised in accordance with this clause",
    ],
    "decommissioning": [
        "the developer shall be responsible for decommissioning the facility",
        "decommissioning security shall be posted no later than year ten",
        "decommissioning plan shall be submitted three years prior to expiry",
    ],
}


def _build_corpus(rng: np.random.Generator, samples_per_class: int = 60):
    texts: list[str] = []
    labels: list[str] = []
    for cls, seeds in CLAUSE_SEEDS.items():
        for _ in range(samples_per_class):
            pick = rng.integers(low=1, high=min(3, len(seeds)) + 1)
            chosen = rng.choice(seeds, size=int(pick), replace=False)
            text = ". ".join(str(s) for s in chosen)
            # Light surface noise so the classifier picks up shape, not literal strings
            if rng.random() < 0.3:
                text = text.upper() if rng.random() < 0.5 else text.title()
            if rng.random() < 0.4:
                text = f"{rng.integers(1, 30)}. {text}"
            texts.append(text)
            labels.append(cls)
    return texts, labels


def train_and_save() -> None:
    rng = np.random.default_rng(20260522)
    texts, labels = _build_corpus(rng, samples_per_class=80)
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=8000, lowercase=True)),
        ("clf", LogisticRegression(max_iter=2000, multi_class="multinomial", C=2.0)),
    ])
    pipe.fit(texts, labels)

    # Hold-out
    rng_eval = np.random.default_rng(7777)
    Xe, ye = _build_corpus(rng_eval, samples_per_class=30)
    score = float(pipe.score(Xe, ye))

    out_pkl = OUT / "clause_classifier.pkl"
    out_meta = OUT / "clause_classifier.meta.json"
    with out_pkl.open("wb") as f:
        pickle.dump(pipe, f)

    meta = {
        "name": "contractiq-clause-classifier",
        "version": "1.0.0",
        "framework": "sklearn",
        "description": (
            "Classifies a contract clause into one of ~30 ETRM clause types "
            "(term, delivery_point, pricing_formula, indexation, force_majeure, "
            "credit_support, tax, settlement, ...) using TF-IDF + multinomial "
            "logistic regression. Used by the ContractIQ extractor pipeline "
            "as a fast pre-filter before the deep LLM extraction pass. When "
            "the top class probability is below 0.55 the pipeline falls back "
            "to a full LLM read."
        ),
        "input_schema": {
            "features": ["text"],
            "types": ["string"],
            "example": [
                "either party may terminate this agreement upon written notice of material breach"
            ],
        },
        "output_schema": {
            "type": "classification",
            "classes": sorted(CLAUSE_SEEDS.keys()),
            "returns": "clause type label + per-class probabilities",
        },
        "tags": ["contractiq", "extraction", "clause-classification", "pre-filter"],
        "training": {
            "samples": len(texts),
            "algorithm": "TF-IDF (1-2 grams) + Multinomial Logistic Regression",
            "synthetic": True,
            "holdout_accuracy": round(score, 4),
            "classes": sorted(CLAUSE_SEEDS.keys()),
        },
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    print(f"Wrote {out_pkl} ({out_pkl.stat().st_size} bytes)")
    print(f"Wrote {out_meta}")
    print(f"Holdout accuracy: {score:.4f}  classes: {len(CLAUSE_SEEDS)}")


if __name__ == "__main__":
    train_and_save()
