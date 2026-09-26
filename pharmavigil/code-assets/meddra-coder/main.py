"""MedDRA autocoder — pure stdlib.

Maps verbatim reaction terms from a safety report onto the MedDRA hierarchy.
Reads {"terms": [...]} from stdin and writes candidates with a match score.

Three passes, in order of how much we trust them:

  1. exact       — the verbatim string is an LLT, after normalisation
  2. synonym     — a known reporter phrasing for an LLT ("heart attack")
  3. fuzzy       — token overlap plus edit distance over the LLT index

The dictionary shipped here is a demonstration subset, not licensed MedDRA.
Point MEDDRA_DICT_PATH at a real LLT export to use this for anything real;
the matching logic does not change.

The agent that calls this adjudicates anything below `review_threshold` or
with more than one close candidate. That split is deliberate: the dictionary
does what a dictionary is good at, and the model only judges the cases a
dictionary genuinely cannot settle.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REVIEW_THRESHOLD = 0.80
MAX_CANDIDATES = 4

# Demonstration subset. llt -> (pt, hlt, soc, code, is_ime)
# IME = Important Medical Event, which forces a seriousness review even when
# no other CIOMS criterion is met.
DICT: dict[str, tuple[str, str, str, str, bool]] = {
    "anaphylactic reaction": ("Anaphylactic reaction", "Anaphylactic and anaphylactoid responses", "Immune system disorders", "10002198", True),
    "angioedema": ("Angioedema", "Angioedema and urticaria", "Skin and subcutaneous tissue disorders", "10002424", True),
    "hepatic failure": ("Hepatic failure", "Hepatic failure and associated disorders", "Hepatobiliary disorders", "10019663", True),
    "hepatotoxicity": ("Hepatotoxicity", "Hepatic and hepatobiliary disorders NEC", "Hepatobiliary disorders", "10019851", True),
    "stevens-johnson syndrome": ("Stevens-Johnson syndrome", "Epidermal and dermal conditions", "Skin and subcutaneous tissue disorders", "10042033", True),
    "agranulocytosis": ("Agranulocytosis", "Neutropenias", "Blood and lymphatic system disorders", "10001507", True),
    "rhabdomyolysis": ("Rhabdomyolysis", "Muscle disorders", "Musculoskeletal and connective tissue disorders", "10039020", True),
    "torsade de pointes": ("Torsade de pointes", "Ventricular arrhythmias and cardiac arrest", "Cardiac disorders", "10044066", True),
    "myocardial infarction": ("Myocardial infarction", "Ischaemic coronary artery disorders", "Cardiac disorders", "10028596", True),
    "seizure": ("Seizure", "Seizures and seizure disorders NEC", "Nervous system disorders", "10039906", True),
    "acute kidney injury": ("Acute kidney injury", "Renal failure and impairment", "Renal and urinary disorders", "10069339", True),
    "pancreatitis": ("Pancreatitis", "Acute and chronic pancreatitis", "Gastrointestinal disorders", "10033645", True),
    "nausea": ("Nausea", "Nausea and vomiting symptoms", "Gastrointestinal disorders", "10028813", False),
    "vomiting": ("Vomiting", "Nausea and vomiting symptoms", "Gastrointestinal disorders", "10047700", False),
    "diarrhoea": ("Diarrhoea", "Diarrhoea (excl infective)", "Gastrointestinal disorders", "10012735", False),
    "abdominal pain": ("Abdominal pain", "Gastrointestinal and abdominal pains", "Gastrointestinal disorders", "10000081", False),
    "headache": ("Headache", "Headaches NEC", "Nervous system disorders", "10019211", False),
    "dizziness": ("Dizziness", "Neurological signs and symptoms NEC", "Nervous system disorders", "10013573", False),
    "fatigue": ("Fatigue", "Asthenic conditions", "General disorders and administration site conditions", "10016256", False),
    "rash": ("Rash", "Rashes, eruptions and exanthems NEC", "Skin and subcutaneous tissue disorders", "10037844", False),
    "pruritus": ("Pruritus", "Pruritus NEC", "Skin and subcutaneous tissue disorders", "10037087", False),
    "urticaria": ("Urticaria", "Angioedema and urticaria", "Skin and subcutaneous tissue disorders", "10046735", False),
    "dyspnoea": ("Dyspnoea", "Breathing abnormalities", "Respiratory, thoracic and mediastinal disorders", "10013968", False),
    "cough": ("Cough", "Coughing and associated symptoms", "Respiratory, thoracic and mediastinal disorders", "10011224", False),
    "pyrexia": ("Pyrexia", "Febrile disorders", "General disorders and administration site conditions", "10037660", False),
    "hypotension": ("Hypotension", "Vascular hypotensive disorders", "Vascular disorders", "10021097", False),
    "hypertension": ("Hypertension", "Vascular hypertensive disorders", "Vascular disorders", "10020772", False),
    "tachycardia": ("Tachycardia", "Cardiac arrhythmias NEC", "Cardiac disorders", "10043071", False),
    "palpitations": ("Palpitations", "Cardiac signs and symptoms NEC", "Cardiac disorders", "10033557", False),
    "myalgia": ("Myalgia", "Muscle pains", "Musculoskeletal and connective tissue disorders", "10028411", False),
    "arthralgia": ("Arthralgia", "Joint related signs and symptoms", "Musculoskeletal and connective tissue disorders", "10003239", False),
    "insomnia": ("Insomnia", "Disturbances in initiating and maintaining sleep", "Psychiatric disorders", "10022437", False),
    "anxiety": ("Anxiety", "Anxiety symptoms", "Psychiatric disorders", "10002855", False),
    "depression": ("Depression", "Depressive disorders", "Psychiatric disorders", "10012378", False),
    "confusional state": ("Confusional state", "Mental impairment disorders", "Psychiatric disorders", "10010305", False),
    "blood glucose increased": ("Blood glucose increased", "Carbohydrate tolerance analyses", "Investigations", "10005557", False),
    "alanine aminotransferase increased": ("Alanine aminotransferase increased", "Hepatic enzymes and function abnormalities", "Investigations", "10001551", False),
    "weight increased": ("Weight increased", "Weight changes", "Investigations", "10047899", False),
    "oedema peripheral": ("Oedema peripheral", "Peripheral oedemas", "General disorders and administration site conditions", "10030124", False),
    "dry mouth": ("Dry mouth", "Salivary gland conditions NEC", "Gastrointestinal disorders", "10013781", False),
    "constipation": ("Constipation", "Gastrointestinal atonic and hypomotility disorders NEC", "Gastrointestinal disorders", "10010774", False),
    "vision blurred": ("Vision blurred", "Visual disorders NEC", "Eye disorders", "10047513", False),
    "tinnitus": ("Tinnitus", "Hearing disorders NEC", "Ear and labyrinth disorders", "10043882", False),
    "alopecia": ("Alopecia", "Alopecias", "Skin and subcutaneous tissue disorders", "10001760", False),
}

# How reporters actually write things -> the LLT they mean.
SYNONYMS: dict[str, str] = {
    "heart attack": "myocardial infarction",
    "mi": "myocardial infarction",
    "hives": "urticaria",
    "itching": "pruritus",
    "itchiness": "pruritus",
    "throwing up": "vomiting",
    "threw up": "vomiting",
    "being sick": "vomiting",
    "feeling sick": "nausea",
    "queasy": "nausea",
    "loose stools": "diarrhoea",
    "diarrhea": "diarrhoea",
    "the runs": "diarrhoea",
    "stomach ache": "abdominal pain",
    "stomach pain": "abdominal pain",
    "belly pain": "abdominal pain",
    "tummy pain": "abdominal pain",
    "short of breath": "dyspnoea",
    "shortness of breath": "dyspnoea",
    "breathless": "dyspnoea",
    "can't breathe": "dyspnoea",
    "trouble breathing": "dyspnoea",
    "dyspnea": "dyspnoea",
    "fever": "pyrexia",
    "temperature": "pyrexia",
    "high temperature": "pyrexia",
    "tired": "fatigue",
    "exhausted": "fatigue",
    "worn out": "fatigue",
    "no energy": "fatigue",
    "light headed": "dizziness",
    "lightheaded": "dizziness",
    "giddy": "dizziness",
    "room spinning": "dizziness",
    "racing heart": "tachycardia",
    "fast heartbeat": "tachycardia",
    "heart racing": "palpitations",
    "fluttering heart": "palpitations",
    "low blood pressure": "hypotension",
    "high blood pressure": "hypertension",
    "bp up": "hypertension",
    "swollen ankles": "oedema peripheral",
    "swollen legs": "oedema peripheral",
    "puffy feet": "oedema peripheral",
    "muscle pain": "myalgia",
    "aching muscles": "myalgia",
    "joint pain": "arthralgia",
    "achy joints": "arthralgia",
    "can't sleep": "insomnia",
    "couldn't sleep": "insomnia",
    "trouble sleeping": "insomnia",
    "hair loss": "alopecia",
    "hair falling out": "alopecia",
    "losing hair": "alopecia",
    "skin peeling": "stevens-johnson syndrome",
    "blistering rash": "stevens-johnson syndrome",
    "yellow skin": "hepatotoxicity",
    "jaundice": "hepatotoxicity",
    "yellow eyes": "hepatotoxicity",
    "liver failure": "hepatic failure",
    "liver problems": "hepatotoxicity",
    "raised liver enzymes": "alanine aminotransferase increased",
    "alt up": "alanine aminotransferase increased",
    "fit": "seizure",
    "fits": "seizure",
    "convulsion": "seizure",
    "convulsions": "seizure",
    "blackout": "seizure",
    "kidney failure": "acute kidney injury",
    "kidneys failing": "acute kidney injury",
    "swollen face": "angioedema",
    "swollen lips": "angioedema",
    "lip swelling": "angioedema",
    "throat closing": "anaphylactic reaction",
    "anaphylaxis": "anaphylactic reaction",
    "allergic shock": "anaphylactic reaction",
    "blurred vision": "vision blurred",
    "ringing in ears": "tinnitus",
    "ringing in the ears": "tinnitus",
    "muscle breakdown": "rhabdomyolysis",
    "dark urine and muscle pain": "rhabdomyolysis",
    "confused": "confusional state",
    "confusion": "confusional state",
    "muddled": "confusional state",
    "low mood": "depression",
    "feeling down": "depression",
    "on edge": "anxiety",
    "panicky": "anxiety",
    "sugar up": "blood glucose increased",
    "blood sugar high": "blood glucose increased",
    "put on weight": "weight increased",
    "gained weight": "weight increased",
    "bunged up": "constipation",
    "cant go to the toilet": "constipation",
}

_PUNCT = re.compile(r"[^a-z0-9\s-]")
_WS = re.compile(r"\s+")
# Words that carry no diagnostic signal and only dilute token overlap.
_STOP = {
    "the", "a", "an", "of", "and", "or", "with", "some", "very", "really",
    "patient", "reported", "had", "has", "have", "been", "was", "were",
    "felt", "feeling", "experienced", "complained", "severe", "mild",
    "moderate", "slight", "bad", "lot", "bit", "my", "his", "her", "their",
}


def normalise(term: str) -> str:
    t = _PUNCT.sub(" ", (term or "").lower().strip())
    return _WS.sub(" ", t).strip()


def tokens(term: str) -> set[str]:
    return {w for w in normalise(term).split() if w and w not in _STOP}


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    """Token overlap and edit distance, whichever is kinder, 0..1."""
    ta, tb = tokens(a), tokens(b)
    jaccard = len(ta & tb) / len(ta | tb) if (ta or tb) else 0.0
    longest = max(len(a), len(b)) or 1
    edit = 1.0 - (levenshtein(a, b) / longest)
    return max(jaccard, edit)


def load_dictionary() -> dict[str, tuple[str, str, str, str, bool]]:
    """Real MedDRA is licensed, so the shipped dictionary is a subset.

    Set MEDDRA_DICT_PATH to a JSON export of
    {llt: [pt, hlt, soc, code, is_ime]} to use a full one.
    """
    path = os.environ.get("MEDDRA_DICT_PATH")
    if not path:
        return DICT
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return {k.lower(): tuple(v) for k, v in raw.items()}  # type: ignore[misc]
    except Exception:
        return DICT


def entry(llt: str, table) -> dict:
    pt, hlt, soc, code, ime = table[llt]
    return {
        "llt": llt, "pt": pt, "hlt": hlt, "soc": soc,
        "meddra_code": code, "is_ime": ime,
    }


def code_term(verbatim: str, table) -> dict:
    norm = normalise(verbatim)
    if not norm:
        return {"verbatim": verbatim, "candidates": [], "match": "empty",
                "needs_review": True}

    if norm in table:
        return {"verbatim": verbatim, "match": "exact", "needs_review": False,
                "candidates": [{**entry(norm, table), "score": 1.0}]}

    if norm in SYNONYMS and SYNONYMS[norm] in table:
        return {"verbatim": verbatim, "match": "synonym", "needs_review": False,
                "candidates": [{**entry(SYNONYMS[norm], table), "score": 0.95}]}

    # A synonym phrase inside a longer sentence: "I had really bad hives".
    for phrase, llt in SYNONYMS.items():
        if llt in table and re.search(rf"\b{re.escape(phrase)}\b", norm):
            return {"verbatim": verbatim, "match": "synonym_contained",
                    "needs_review": False,
                    "candidates": [{**entry(llt, table), "score": 0.90}]}

    scored = sorted(
        ({**entry(llt, table), "score": round(similarity(norm, llt), 3)}
         for llt in table),
        key=lambda c: c["score"],
        reverse=True,
    )[:MAX_CANDIDATES]
    top = scored[0]["score"] if scored else 0.0
    # Two candidates within a hair of each other is exactly the case a
    # dictionary cannot settle, so hand it up even when the top score is high.
    close = len([c for c in scored if top - c["score"] < 0.05])
    return {
        "verbatim": verbatim,
        "match": "fuzzy",
        "needs_review": top < REVIEW_THRESHOLD or close > 1,
        "candidates": [c for c in scored if c["score"] > 0.3],
    }


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # noqa: BLE001
        json.dump({"error": f"invalid JSON on stdin: {exc}"}, sys.stdout)
        return

    raw = payload.get("terms") or []
    if isinstance(raw, str):
        raw = [raw]
    # The pipeline may hand us the intake node's reaction objects rather than
    # bare strings, so accept either shape.
    terms = [t.get("verbatim", "") if isinstance(t, dict) else str(t) for t in raw]

    table = load_dictionary()
    results = [code_term(t, table) for t in terms if str(t).strip()]

    json.dump(
        {
            "results": results,
            "coded": sum(1 for r in results if not r["needs_review"]),
            "needs_review": sum(1 for r in results if r["needs_review"]),
            "ime_hits": sorted({
                c["pt"] for r in results for c in r["candidates"]
                if c.get("is_ime") and not r["needs_review"]
            }),
            "dictionary_size": len(table),
            "review_threshold": REVIEW_THRESHOLD,
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
