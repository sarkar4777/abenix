# ML Models — upload, deploy, invoke

Besides LLMs, Abenix runs classical ML models. Upload a trained scikit-learn, XGBoost, ONNX or PyTorch model, test it on the page, then let agents call it through the `ml_model` tool.

Wingman's fair-value model, E&C-Copilot's clause classifier and risk-tier predictor, and Industrial-IoT's failure classifier all run this way.

## The user path on `/ml-models`

1. **Upload a trained model.** Pick the file, give it a name, optionally a version and a description of its inputs. The API loads the file before answering. A file that loads becomes **Ready** and **Active**. A file that does not load is refused with the loader's reason.
2. **Describe its inputs.** Feature names in order plus one example row. Agents and the test form use it. Left blank, Abenix infers the feature count from the file.
3. **Test it.** Test inference sends a row and shows the prediction. No deploy is needed, predictions run in-process.
4. **Use it in an agent.** Use in Agent opens `/builder?tool=ml_model&model_name=<name>` with the tool added and pointed at the model.

A new user with no model can press **Try with a sample model**. It registers `iris-sample`, a small LogisticRegression shipped in `apps/api/app/core/ml_samples/`, with its input description and example filled in so Test inference works straight away.

The page has a "How this works" panel, an empty state, and stacks to one column below the `lg` breakpoint.

## Supported files

| Framework | Extensions | Loader | Notes |
|---|---|---|---|
| `sklearn` | `.joblib`, `.pkl` | `joblib.load` | Must have `predict()`. `predict_proba()` and `classes_` are used when present |
| `xgboost` | `.xgb` or `framework: xgboost` | `joblib.load` | The scikit-learn wrapper, saved with joblib |
| `onnx` | `.onnx` | `onnxruntime.InferenceSession` | First input gets the rows as float32 |
| `pytorch` | `.pt`, `.pth` | `torch.load` | A whole model saved with `torch.save(model)`. A bare state dict is refused. Needs torch on the API image |

TensorFlow (`.h5`, `.keras`) and unknown `.bin` files are refused at upload with a hint to convert to ONNX. Nothing in the platform can run them.

## What a developer ships

```python
import joblib
from sklearn.linear_model import LogisticRegression

model = LogisticRegression(max_iter=500).fit(X, y)
joblib.dump(model, "churn.joblib")
```

Upload through the page or the API:

```bash
curl -X POST "$ABENIX/api/ml-models" -H "Authorization: Bearer $TOKEN" \
  -F file=@churn.joblib \
  -F 'metadata={"name":"churn","input_schema":{"features":["age","income","tenure"],"example":[35,50000,24]}}'
```

`metadata` takes `name`, `version`, `description`, `framework`, `input_schema`, `output_schema` and `tags`. All are optional except a name, which defaults to the file stem.

## Upload outcomes

| Case | Answer | What is stored |
|---|---|---|
| File loads | `201` with the model | `status=ready`, `is_active=true`, earlier active version of the name deactivated, inferred schemas filled in |
| File does not load | `422 MODEL_LOAD_FAILED`, message is the reason, `details.model` is the stored row | `status=error`, `is_active=false`, reason in `training_metrics.validation_error`, served as `status_message`. The active version is untouched |
| Version already taken | `409 VERSION_EXISTS`, `details.next_version` | Nothing |
| TensorFlow or `.bin` | `422 UNSUPPORTED_FRAMEWORK` | Nothing |
| Any other extension | `400` "Unsupported file type" | Nothing |

A model in `error` cannot be predicted, deployed or set active. Those calls answer `409 MODEL_NOT_READY` with the stored reason.

## From the SDK

```python
model = await client.ml_models.upload(
    "churn", "churn.joblib", feature_names=["age", "income", "tenure"], description="Churn risk",
)
print(model["version"], model["status"])
print(await client.ml_models.predict("churn", {"age": 35, "income": 50000, "tenure": 24}))
```

`upload` raises `AbenixError` with the codes in the table above. The TypeScript SDK has the same calls on `forge.mlModels`. See [03-sdk/01-python](../03-sdk/01-python.md#ml-models).

## Register from a run

A training pipeline can publish its own output with the `ml_model_register` tool, no client hop needed. It sends the file through the same upload path as the page, so the load check, versioning and the outcomes above all apply. The model is owned by the user who started the run, a run with no user is refused.

Give the file one of two ways:

- `file_path`, a file the run saved to its export folder (`EXPORT_DIR`, `/data/exports` in the cluster), for example with `save_export("churn.joblib", data)` in `code_executor` or with `data_exporter`. A bare file name is looked up there. Paths outside that folder are refused
- `file_base64`, the file as base64, for example a field the trainer prints in its JSON output, read as `{{train.result.<field>}}`. Add `filename` with the extension, or `framework` and the tool names it for you

```yaml
- id: train
  tool_name: code_asset
  arguments: {code_asset_id: "<trainer>", input: {rows: "{{load.rows}}"}}

- id: publish
  tool_name: ml_model_register
  depends_on: [train]
  arguments:
    model_name: churn
    file_base64: "{{train.result.model_b64}}"
    framework: sklearn
    feature_names: ["age", "income", "tenure"]
```

The tool returns `model_id`, `model_name`, `version`, `status`, `is_active` and the schemas. A file that does not load comes back as an error naming the stored error version, the active version stays as it was. It is a medium risk tool with a write effect. The tenant's medium tier policy decides whether a lower risk run may call it, the default allows it.

## Versions

A model has a stable `name` and a `version`. Leave the version blank and the API picks the next free one: `1.0.0` first, then a minor bump of the highest (`1.1.0`, `1.2.0`). Uploading an explicit version that already exists for the name is refused with the next free version in the message.

Agents call a model by name. The tool picks the ready version with `is_active=true`, else the most recently updated ready version. `POST /api/ml-models/{id}/activate` makes a version active and deactivates the others of that name. `POST /api/ml-models/{id}/deactivate` turns it off. Both return the updated model.

## Predictions

`POST /api/ml-models/{id}/predict` with `{"input_data": ...}`. Accepted shapes:

- `{"features": [5.1, 3.5, 1.4, 0.2]}` for one row
- `[[...], [...]]` for several rows
- `{"sepal_length": 5.1, ...}` keyed by the names in `input_schema.features`, reordered to match

A wrong feature count answers `422 INVALID_INPUT` with a plain message, for example `This model expects 4 features, you sent 2. Send them in this order: sepal_length, sepal_width, petal_length, petal_width.` Values the model rejects also answer 422. Only a failure inside the model answers 500.

When a Kubernetes deployment is running the call goes to its endpoint, otherwise it runs in-process. Every call that reaches the model, ok or failed, writes an `ml_model_invocations` row with `caller_source=api`. A 404, a 409 `MODEL_NOT_READY` or an empty `input_data` writes none. Agent calls write the same row from the runtime with `caller_source=agent_runtime`. The Invocations panel and `/api/ml-models/{id}/stats` read those rows.

The caller must own the model, hold a share on it or be an admin. Anyone else gets 404, the same as the detail page.

## Explanations

`POST /api/ml-models/{id}/explain` answers why the model gave one row its prediction. Send `{"input_data": ..., "baseline": ...}`. `input_data` takes the same shapes as predict but only one row. `baseline` is optional, either an object keyed by feature name (missing names keep the default) or a list with one number per feature.

The answer holds `prediction`, `base_value` (the model output for the baseline row), one entry per feature in `contributions` (`feature`, `value`, `baseline`, `contribution`, largest first) and a `waterfall` that walks from `base_value` to `prediction` one feature at a time. The contributions always add up to `prediction - base_value`, `additivity_gap` shows the rounding left over.

`target` says which number was explained. A regressor explains its prediction, a classifier the probability of the class it picked, an outlier model such as IsolationForest its anomaly score.

`method` says how the split was made:

| Method | When | What it is |
|---|---|---|
| `linear` | Linear regressors, also behind StandardScaler steps | Coefficient times distance from baseline, exact |
| `exact-shapley` | Everything else with up to 10 features | Shapley values over every mix of input and baseline values |
| `sampled-shapley` | More than 10 features | Shapley values averaged over 64 random orders, still adds up exactly |
| `tree-shap`, `linear-shap` | The `shap` package is installed in the API image | SHAP against the same baseline, used only when it adds up |

`baseline_source` says where the baseline came from:

- `request` when the call sent it
- `training_means` from `training_metrics.feature_means` or `input_schema["x-feature-means"]`
- `training_means_from_model` from the means a leading StandardScaler learned
- `zeros` when none of those exist, so ship `feature_means` with the model if zero is not a sensible reference

It runs in-process on the cached model, also when a Kubernetes deployment exists. Access and the `409 MODEL_NOT_READY` rule are the same as predict. Bad input answers `422 INVALID_INPUT` with a plain message, for example `Explain takes one row at a time, you sent 2.` or `baseline names unknown features: zz.` Every call writes an `ml_model_invocations` row with `operation=explain`.

```python
why = await client.ml_models.explain("churn", {"age": 35, "income": 50000, "tenure": 24})
for c in why["contributions"]:
    print(c["feature"], round(c["contribution"], 3))
```

## Deploy (optional)

Predictions and agents work as soon as a model is ready. Deploy runs it as its own service for production traffic.

- **Local** marks the model as served in-process. Nothing new starts.
- **Kubernetes** creates a `ml-model-<id8>` Deployment and Service from `ML_MODEL_SERVING_IMAGE` (built from `docker/Dockerfile.model-serving`, default `localhost:5000/abenix/model-serving:latest`, Helm `mlModels.servingImage`). Admin or owner only. Over `ML_MODEL_MAX_K8S_PER_TENANT` the API answers 429. A background task flips the row to `running` when a replica is ready, or `failed` after 120 seconds.

Deploy is idempotent per model and target. The model row is locked for the call, and a deployment of the same type that is already `deploying` or `running` with the same replicas and preset is returned with `already_deployed: true`. A Kubernetes deploy with new replicas or preset replaces the spec and stops the older row. The page disables the button while a deploy is in flight and shows "Running locally" once a local deployment exists.

`DELETE /api/ml-models/{id}/undeploy` stops every active deployment and deletes the Kubernetes objects.

## Sample models

`POST /api/ml-models/samples/iris` registers the shipped iris classifier for the caller as `iris-sample`. A second call returns the caller's existing ready copy instead of adding another. Rebuild the file with `python -m app.core.ml_samples.build_samples` from `apps/api`. If the file is missing the endpoint trains it on the fly from the dataset bundled with scikit-learn.

## Where to look

- REST API: [`apps/api/app/routers/ml_models.py`](../../apps/api/app/routers/ml_models.py)
- Explanation maths: `apps/api/app/core/ml_explain.py`
- Page: `apps/web/src/app/(app)/ml-models/page.tsx`, helpers in `helpers.ts` next to it
- Sample models: `apps/api/app/core/ml_samples/`
- The `ml_model` tool: [`apps/agent-runtime/engine/tools/ml_model_tool.py`](../../apps/agent-runtime/engine/tools/ml_model_tool.py)
- The `ml_model_register` tool: [`apps/agent-runtime/engine/tools/ml_model_register.py`](../../apps/agent-runtime/engine/tools/ml_model_register.py)
- Invocation and stats routes: `apps/api/app/routers/invocations.py`
- Tables: `packages/db/models/ml_model.py`, `ml_model_invocation.py`
- Serving image: `docker/Dockerfile.model-serving`
- Tests: `tests/unit/test_ml_models.py`, `tests/unit/test_ml_explain.py`, `apps/agent-runtime/tests/test_ml_model_register.py`, `tests/unit/test_sdk_registry_clients.py`

## Reference deployments

- Wingman: `wingman/ml-models/build_*.py`, 5 sklearn models (broker-intent LogisticRegression, freight-forecast GradientBoosting, mispricing Bayesian Ridge fair value and Isolation Forest anomaly, GaussianNB scenario prior)
- E&C-Copilot: `contractiq/aimodels/`, 9 sklearn models (clause classifier, risk tier, counterparty default, price anomaly, gas and power fair value, three offtake models)
- Industrial-IoT: `industrial-iot/aimodels/`, a wind-turbine failure classifier (pickle and metadata only). Its RUL estimator is a code asset in `industrial-iot/code-assets/rul-estimator/`

The build scripts in the Wingman and E&C-Copilot folders show the contract end to end.
