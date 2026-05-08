# rul-estimator

Fits an exponential degradation curve — `health = a · exp(-k · t)` —
to a recent history of health-index readings, then extrapolates to
the failure threshold to produce a remaining-useful-life (RUL)
estimate in hours.

Falls back to a linear fit if the exponential fit is worse (R²
lower) or numerically unstable. Pure-Python stdlib only — no
SciPy, no NumPy — so the image is tiny and cold-start is fast.

## Run

```
cat input.json | python main.py
```
