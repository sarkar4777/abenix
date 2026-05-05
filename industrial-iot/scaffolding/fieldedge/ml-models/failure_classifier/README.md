# failure_classifier

Random-Forest classifier that maps eight turbine sensor features to one
of five common failure classes.

## Classes

| label | physical signature |
| --- | --- |
| `bearing` | high-frequency vibration band + slight temperature rise |
| `blade` | rotor imbalance, mid-RMS vibration, AEP loss |
| `gearbox` | oil iron-ppm spike + broadband mid-frequency vibration |
| `generator` | winding temperature rise + low insulation resistance |
| `control` | erratic yaw-position error + fault-code rate spike |

## Features (canonical order)

1. `vibration_rms_mm_s` (ISO 10816 RMS velocity)
2. `vibration_hf_band_g` (1–3 kHz band peak, g)
3. `gearbox_oil_iron_ppm`
4. `generator_winding_temp_c`
5. `generator_insulation_mohm` (low = bad)
6. `yaw_position_error_deg`
7. `fault_code_rate_per_hour`
8. `ambient_wind_mps` (context, weak signal)

## Usage

```bash
# Train (idempotent — overwrites the .pkl + metadata.json)
python train.py

# Predict
echo '{"vibration_rms_mm_s":8.5,"vibration_hf_band_g":3.2,"gearbox_oil_iron_ppm":35,"generator_winding_temp_c":60,"generator_insulation_mohm":22,"yaw_position_error_deg":0.8,"fault_code_rate_per_hour":4,"ambient_wind_mps":8}' \
  | python predict.py
```

## Output

```json
{
  "predicted_class": "bearing",
  "confidence": 0.9123,
  "probabilities": {
    "bearing": 0.91, "blade": 0.04, "gearbox": 0.03,
    "generator": 0.01, "control": 0.01
  },
  "model_version": "2026-05-05T12:34:56Z",
  "model_type": "RandomForestClassifier",
  "used_features": [...],
  "imputed_features": [],
  "test_accuracy_at_train_time": 0.9417
}
```

Missing features are filled from the global mean and listed under
`imputed_features` so the caller knows confidence may be inflated.

## Notes

- **Synthetic data.** The training set is drawn from class-specific
  Gaussians whose means / stds approximate real engineering ranges.
  Good enough to demonstrate the end-to-end ML lifecycle (model
  registration, prediction call, lineage) — not for production
  diagnosis.
- **Determinism.** `RANDOM_STATE=42` everywhere — re-running `train.py`
  produces a bit-identical artefact, which keeps the checked-in
  `.pkl` reproducible.
- **Size budget.** ~600 KB pickle, fits comfortably in a code-asset
  upload.
