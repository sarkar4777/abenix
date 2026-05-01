# pump-dsp-correction

Vibration-signal DSP for rotating machinery. Produces the classic
indicators that a predictive-maintenance agent reasons about —
bearing wear, imbalance, misalignment, cavitation — from one window
of raw accelerometer samples.

## Pipeline

1. Drift removal (moving-average detrend)
2. Median-filter de-noise (kernel=5)
3. Global metrics: RMS, peak, crest factor, kurtosis
4. FFT (radix-2, Cooley–Tukey) → top-5 dominant frequencies
5. Per-fault scores:
   - **bearing** — high-frequency energy × kurtosis
   - **imbalance** — amplitude at 1× shaft rpm
   - **misalignment** — amplitude at 2× shaft rpm
   - **cavitation** — broadband high-frequency energy
6. ISO 10816-3 zone mapping (A–D) when shaft RPM + RMS are both known

Everything is done in pure Go with no external dependencies, so the
image stays small and starts fast inside a sandboxed k8s Job.

## Run

```
cat input.json | go run ./cmd/pumpdsp
```
