# Supplier risk scorer

`python main.py` reads a JSON object on stdin and writes JSON on stdout.

Input:

```json
{"suppliers": [{"name": "Nordtek", "current_ratio": 0.8, "debt_to_equity": 2.1,
  "on_time_delivery_pct": 86, "single_source": true, "country_risk": "medium"}]}
```

Output has `scored`, one row per supplier with `risk_score` from 0 to 100,
`tier` red, amber or green and the two `top_drivers`, plus a `portfolio`
summary. Standard library only, no build step.
