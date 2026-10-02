"""ML Model Tool — run inference on registered ML models."""

from __future__ import annotations

import json
import tempfile
import asyncio
import logging
import os
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# LRU-style cache for loaded models (local mode)
_MODEL_CACHE: dict[str, Any] = {}
_MAX_CACHE = 5


def _safe_parse_json(content: str | None):
    if not content:
        return None
    try:
        import json as _json

        return _json.loads(content)
    except Exception:
        return {"raw": str(content)[:2000]}


_FETCH_LOCKS: dict[str, asyncio.Lock] = {}


async def _ensure_local(model_id: str, file_uri: str, tenant_id: str) -> str:
    """A readable path for the model file on this pod.

    The API and the runtime need not share a volume, so a file the runtime
    cannot see is fetched once from the API with a token scoped to this
    model, written atomically and reused afterwards.
    """
    if file_uri and os.path.isfile(file_uri):
        return file_uri
    cache_dir = os.path.join(tempfile.gettempdir(), "ml-model-cache", tenant_id or "_")
    os.makedirs(cache_dir, exist_ok=True)
    local = os.path.join(
        cache_dir, f"{model_id}_{os.path.basename(file_uri or 'model.bin')}"
    )
    if os.path.isfile(local) and os.path.getsize(local) > 0:
        return local
    lock = _FETCH_LOCKS.setdefault(model_id, asyncio.Lock())
    async with lock:
        if os.path.isfile(local) and os.path.getsize(local) > 0:
            return local
        import httpx

        from engine.tools.invoke_agent import mint_fetch_token

        token = mint_fetch_token("ml_model_fetch", model_id, tenant_id)
        if not token:
            raise FileNotFoundError(
                f"model file {file_uri} is not on this pod and no fetch token could be signed"
            )
        base = os.environ.get("ABENIX_INTERNAL_URL") or os.environ.get(
            "ABENIX_API_URL", "http://abenix-api:8000"
        )
        tmp = f"{local}.part"
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "GET",
                f"{base.rstrip('/')}/api/ml-models/{model_id}/fetch",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status_code != 200:
                    raise FileNotFoundError(
                        f"model file {file_uri} is not on this pod and the API returned {resp.status_code}"
                    )
                with open(tmp, "wb") as fh:
                    async for chunk in resp.aiter_bytes():
                        fh.write(chunk)
        if os.path.getsize(tmp) == 0:
            os.unlink(tmp)
            raise FileNotFoundError(f"model file {file_uri} came back empty")
        os.replace(tmp, local)
    return local


class MLModelTool(BaseTool):
    name = "ml_model"
    description = (
        "Run inference on registered ML models (sklearn, PyTorch, ONNX, XGBoost). "
        "Operations: 'list_models' (catalog), 'predict' (single inference), "
        "'predict_proba' (classifier probabilities), 'batch_predict' (vectorised inference "
        "on N rows), 'get_model_info' (schemas + metrics), 'get_metrics' (just training "
        "metrics), 'explain' (feature importance / linear coefficients), 'health_check' "
        "(verify a model is reachable + warm)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "list_models",
                    "predict",
                    "predict_proba",
                    "batch_predict",
                    "get_model_info",
                    "get_metrics",
                    "explain",
                    "health_check",
                ],
                "description": "Which operation to perform",
            },
            "model_name": {
                "type": "string",
                "description": "Name of the model (required for everything except list_models)",
            },
            "model_version": {
                "type": "string",
                "description": "Version of the model (default: latest)",
                "default": "latest",
            },
            "input_data": {
                "type": "object",
                "description": "Input features for prediction. Usually {features: [1.0, 2.0, ...]} or {col1: val1, col2: val2}. For batch_predict pass {batch: [[...], [...], ...]} or {rows: [{...}, {...}]}",
            },
        },
        "required": ["operation"],
    }

    def __init__(
        self,
        db_url: str = "",
        tenant_id: str = "",
        execution_id: str = "",
        agent_id: str = "",
    ) -> None:
        self.db_url = db_url or os.environ.get("DATABASE_URL", "")
        self.tenant_id = tenant_id
        self._execution_id = execution_id
        self._agent_id = agent_id

    async def _get_conn(self) -> Any:
        import asyncpg

        url = self.db_url.replace("postgresql+asyncpg://", "postgresql://")
        # Strip ssl params that asyncpg doesn't understand
        if "?" in url:
            base, query = url.split("?", 1)
            kept = [
                p
                for p in query.split("&")
                if not p.lower().startswith(("ssl=", "sslmode="))
            ]
            url = base + ("?" + "&".join(kept) if kept else "")
        return await asyncpg.connect(url)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = arguments.get("operation", "")
        if not op:
            return ToolResult(content="Error: operation is required", is_error=True)

        import time as _time

        _t0 = _time.monotonic()
        try:
            if op == "list_models":
                result = await self._list_models()
            elif op == "predict":
                result = await self._predict(arguments)
            elif op == "predict_proba":
                result = await self._predict(arguments, probabilities_only=True)
            elif op == "batch_predict":
                result = await self._predict(arguments, batch=True)
            elif op == "get_model_info":
                result = await self._get_model_info(arguments)
            elif op == "get_metrics":
                result = await self._get_metrics(arguments)
            elif op == "explain":
                result = await self._explain(arguments)
            elif op == "health_check":
                result = await self._health_check(arguments)
            else:
                result = ToolResult(content=f"Unknown operation: {op}", is_error=True)
        except Exception as e:
            logger.error("MLModelTool error: %s", e)
            result = ToolResult(content=f"ML model error: {e}", is_error=True)
        _duration_ms = int((_time.monotonic() - _t0) * 1000)
        if op in ("predict", "predict_proba", "batch_predict"):
            try:
                from engine import invocation_log

                md = result.metadata or {}
                output_obj = (
                    _safe_parse_json(result.content) if not result.is_error else None
                )
                predicted_class = None
                confidence = None
                if isinstance(output_obj, dict):
                    pred = output_obj.get("prediction") or output_obj.get(
                        "predicted_class"
                    )
                    if isinstance(pred, (str, int, float)):
                        predicted_class = str(pred)
                    conf = output_obj.get("confidence") or output_obj.get("probability")
                    if isinstance(conf, (int, float)):
                        confidence = float(conf)
                invocation_log.fire_and_forget(
                    invocation_log.record_ml_model(
                        tenant_id=self.tenant_id or None,
                        ml_model_id=md.get("ml_model_id") or "",
                        execution_id=self._execution_id or None,
                        agent_id=self._agent_id or None,
                        operation=op,
                        input_payload=arguments.get("input_data")
                        or arguments.get("input"),
                        output=output_obj,
                        predicted_class=predicted_class,
                        confidence=confidence,
                        duration_ms=_duration_ms,
                        is_error=bool(result.is_error),
                        error_message=result.content if result.is_error else None,
                        deployment_type=md.get("deployment_type"),
                    )
                )
            except Exception:
                pass
        return result

    async def _list_models(self) -> ToolResult:
        conn = await self._get_conn()
        try:
            rows = await conn.fetch(
                """
                SELECT name, version, framework, status, description,
                       input_schema, output_schema, training_metrics, tags, is_active
                FROM ml_models
                WHERE tenant_id = $1::uuid AND status != 'deleted'
                ORDER BY name, is_active DESC, updated_at DESC
                LIMIT 50
            """,
                self.tenant_id,
            )

            if not rows:
                return ToolResult(
                    content="No ML models registered. Upload one via POST /api/ml-models."
                )

            lines = [f"Available ML Models ({len(rows)}):\n"]
            for r in rows:
                tags_str = ", ".join(r["tags"]) if r["tags"] else ""
                active_badge = " [ACTIVE]" if r.get("is_active") else ""
                lines.append(
                    f"- **{r['name']}** v{r['version']} ({r['framework']}) — {r['status']}{active_badge}\n"
                    f"  {r['description'] or 'No description'}\n"
                    f"  Tags: {tags_str or 'none'}"
                )
            return ToolResult(
                content="\n".join(lines),
                metadata={"count": len(rows)},
            )
        finally:
            await conn.close()

    async def _predict(
        self, args: dict, *, probabilities_only: bool = False, batch: bool = False
    ) -> ToolResult:
        model_name = args.get("model_name", "")
        input_data = args.get("input_data")
        if not model_name:
            return ToolResult(
                content="Error: model_name is required for predict", is_error=True
            )
        if not input_data:
            return ToolResult(
                content="Error: input_data is required for predict", is_error=True
            )
        # batch_predict accepts {batch: [[...], [...]]} or {rows: [{...}, {...}]}
        if batch and isinstance(input_data, dict):
            if "batch" in input_data:
                input_data = input_data["batch"]
            elif "rows" in input_data:
                input_data = input_data["rows"]

        conn = await self._get_conn()
        try:
            # Find the ACTIVE version of the model (is_active=true takes priority)
            row = await conn.fetchrow(
                """
                SELECT id, file_uri, framework, input_schema, output_schema, name, version
                FROM ml_models
                WHERE tenant_id = $1::uuid AND name = $2 AND status = 'ready'
                ORDER BY is_active DESC, updated_at DESC LIMIT 1
            """,
                self.tenant_id,
                model_name,
            )

            if not row:
                return ToolResult(
                    content=f"Model '{model_name}' not found or not ready. Use list_models to see available models.",
                    is_error=True,
                )

            str(row["id"])

            # Check for k8s deployment
            dep_row = await conn.fetchrow(
                """
                SELECT endpoint_url, deployment_type, status
                FROM ml_model_deployments
                WHERE model_id = $1::uuid AND status = 'running' AND endpoint_url IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
            """,
                row["id"],
            )

            predictions = None
            source = "local"

            # Try k8s endpoint first
            if dep_row and dep_row["endpoint_url"]:
                try:
                    import httpx

                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post(
                            dep_row["endpoint_url"], json={"input_data": input_data}
                        )
                        resp.raise_for_status()
                        predictions = resp.json().get("predictions")
                        source = "k8s"
                except Exception as e:
                    logger.warning(
                        "K8s prediction failed, falling back to local: %s", e
                    )

            # Fall back to local inference
            if predictions is None:
                predictions = await self._local_predict(
                    await _ensure_local(
                        str(row["id"]), row["file_uri"], self.tenant_id
                    ),
                    row["framework"],
                    input_data,
                )
                source = "local"

            # predict_proba: strip the deterministic predictions and surface
            # only the probability matrix (classifiers only).
            if probabilities_only:
                if isinstance(predictions, dict) and "probabilities" in predictions:
                    predictions = {
                        "probabilities": predictions["probabilities"],
                        "classes": predictions.get("classes"),
                    }
                else:
                    return ToolResult(
                        content=f"Model '{row['name']}' does not expose probabilities (not a classifier).",
                        is_error=True,
                    )

            op_label = (
                "batch prediction"
                if batch
                else ("probability inference" if probabilities_only else "prediction")
            )
            result_text = (
                f"{op_label.title()} from model '{row['name']}' v{row['version']} ({source} inference):\n\n"
                f"{json.dumps(predictions, indent=2)}"
            )
            return ToolResult(
                content=result_text,
                metadata={
                    "model_name": row["name"],
                    "model_version": row["version"],
                    "framework": row["framework"],
                    "source": source,
                    "ml_model_id": str(row.get("id") or ""),
                    "deployment_type": source,
                    "batch": batch,
                    "probabilities_only": probabilities_only,
                },
            )
        finally:
            await conn.close()

    async def _local_predict(
        self, file_uri: str, framework: str, input_data: Any
    ) -> Any:
        """Load model from disk and run inference."""
        import numpy as np

        # Some LLM clients pass tool arguments JSON-stringified rather
        # than as objects. Accept both shapes.
        if isinstance(input_data, str):
            try:
                input_data = json.loads(input_data)
            except (TypeError, ValueError):
                pass

        # Parse input
        if isinstance(input_data, dict):
            features = input_data.get("features") or list(input_data.values())
        elif isinstance(input_data, list):
            features = input_data
        else:
            raise ValueError(f"input_data must be dict or list, got {type(input_data)}")

        first = features[0] if features else None
        if isinstance(first, str):
            X = features
        else:
            X = (
                np.array([features])
                if not isinstance(first, (list, np.ndarray))
                else np.array(features)
            )

        # Load model (with simple cache)
        cache_key = f"{file_uri}:{framework}"
        if cache_key not in _MODEL_CACHE:
            if len(_MODEL_CACHE) >= _MAX_CACHE:
                oldest = next(iter(_MODEL_CACHE))
                del _MODEL_CACHE[oldest]

            if framework in ("sklearn", "xgboost"):
                import joblib

                _MODEL_CACHE[cache_key] = joblib.load(file_uri)
            elif framework == "onnx":
                import onnxruntime as ort

                _MODEL_CACHE[cache_key] = ort.InferenceSession(file_uri)
            elif framework == "pytorch":
                import torch

                model = torch.load(file_uri, map_location="cpu", weights_only=False)
                model.eval()
                _MODEL_CACHE[cache_key] = model
            else:
                raise ValueError(f"Unsupported framework: {framework}")

        model = _MODEL_CACHE[cache_key]

        # Run inference
        if framework in ("sklearn", "xgboost"):
            preds = model.predict(X)
            result: dict[str, Any] = {"predictions": preds.tolist()}
            if hasattr(model, "predict_proba"):
                result["probabilities"] = model.predict_proba(X).tolist()
            if hasattr(model, "classes_"):
                result["classes"] = [str(c) for c in model.classes_]
                # sklearn classifiers return class labels from predict(),
                # not class indices — `model.classes_[label]` errors when
                # the label is a string (which it is for any non-binary
                # classifier and for label-string binary too). Just take
                # the first prediction directly.
                result["predicted_class"] = str(preds[0]) if preds.size > 0 else None
            return result
        elif framework == "onnx":
            input_name = model.get_inputs()[0].name
            preds = model.run(None, {input_name: X.astype(np.float32)})
            return {
                "predictions": [
                    p.tolist() if hasattr(p, "tolist") else p for p in preds
                ]
            }
        elif framework == "pytorch":
            import torch

            with torch.no_grad():
                output = model(torch.FloatTensor(X))
                return {"predictions": output.numpy().tolist()}
        else:
            raise ValueError(f"Unsupported framework: {framework}")

    async def _get_metrics(self, args: dict) -> ToolResult:
        """Just the training_metrics blob — handy when an agent wants to
        compare candidate models without pulling the full schema."""
        model_name = args.get("model_name", "")
        if not model_name:
            return ToolResult(content="Error: model_name is required", is_error=True)
        conn = await self._get_conn()
        try:
            row = await conn.fetchrow(
                """
                SELECT name, version, framework, training_metrics
                FROM ml_models
                WHERE tenant_id = $1::uuid AND name = $2 AND status != 'deleted'
                ORDER BY is_active DESC, updated_at DESC LIMIT 1
                """,
                self.tenant_id,
                model_name,
            )
            if not row:
                return ToolResult(
                    content=f"Model '{model_name}' not found.", is_error=True
                )
            metrics = row["training_metrics"]
            if isinstance(metrics, str):
                try:
                    metrics = json.loads(metrics)
                except Exception:
                    metrics = {"raw": metrics}
            return ToolResult(
                content=(
                    f"Training metrics for '{row['name']}' v{row['version']} ({row['framework']}):\n\n"
                    f"{json.dumps(metrics or {}, indent=2, default=str)}"
                ),
                metadata={
                    "model_name": row["name"],
                    "model_version": row["version"],
                    "framework": row["framework"],
                    "metrics": metrics or {},
                },
            )
        finally:
            await conn.close()

    async def _explain(self, args: dict) -> ToolResult:
        """Feature importance for tree models, coefficients for linear models.

        Doesn't run SHAP (too heavy for a tool call); returns the model's
        built-in attributions so an agent can rank features."""
        model_name = args.get("model_name", "")
        if not model_name:
            return ToolResult(content="Error: model_name is required", is_error=True)
        conn = await self._get_conn()
        try:
            row = await conn.fetchrow(
                """
                SELECT id, file_uri, framework, name, version, input_schema
                FROM ml_models
                WHERE tenant_id = $1::uuid AND name = $2 AND status = 'ready'
                ORDER BY is_active DESC, updated_at DESC LIMIT 1
                """,
                self.tenant_id,
                model_name,
            )
            if not row:
                return ToolResult(
                    content=f"Model '{model_name}' not ready.", is_error=True
                )
            framework = row["framework"]
            if framework not in ("sklearn", "xgboost"):
                return ToolResult(
                    content=f"explain only supports sklearn/xgboost; '{model_name}' is {framework}.",
                    is_error=True,
                )
            import joblib

            local = await _ensure_local(str(row["id"]), row["file_uri"], self.tenant_id)
            cache_key = f"{local}:{framework}"
            if cache_key not in _MODEL_CACHE:
                if len(_MODEL_CACHE) >= _MAX_CACHE:
                    del _MODEL_CACHE[next(iter(_MODEL_CACHE))]
                _MODEL_CACHE[cache_key] = joblib.load(local)
            model = _MODEL_CACHE[cache_key]
            schema = row["input_schema"]
            if isinstance(schema, str):
                try:
                    schema = json.loads(schema)
                except Exception:
                    schema = {}
            feature_names = (schema or {}).get("feature_names") or list(
                (schema or {}).get("properties", {}).keys()
            )
            attrs: dict[str, Any] = {"model_name": row["name"], "framework": framework}
            if hasattr(model, "feature_importances_"):
                imps = list(model.feature_importances_)
                pairs = sorted(
                    zip(feature_names or [f"f{i}" for i in range(len(imps))], imps),
                    key=lambda kv: -float(kv[1]),
                )
                attrs["method"] = "feature_importances_"
                attrs["ranked_features"] = [
                    {"name": n, "importance": float(v)} for n, v in pairs[:20]
                ]
            elif hasattr(model, "coef_"):
                import numpy as np

                coef = np.atleast_1d(np.asarray(model.coef_)).ravel()
                pairs = sorted(
                    zip(feature_names or [f"f{i}" for i in range(len(coef))], coef),
                    key=lambda kv: -abs(float(kv[1])),
                )
                attrs["method"] = "linear_coefficients"
                attrs["ranked_features"] = [
                    {"name": n, "coefficient": float(v)} for n, v in pairs[:20]
                ]
                if hasattr(model, "intercept_"):
                    inter = model.intercept_
                    attrs["intercept"] = (
                        float(inter[0]) if hasattr(inter, "__len__") else float(inter)
                    )
            else:
                return ToolResult(
                    content=f"Model '{model_name}' exposes no importances/coefficients to explain.",
                    is_error=True,
                )
            return ToolResult(
                content=f"Feature attributions for '{row['name']}':\n\n{json.dumps(attrs, indent=2)}",
                metadata=attrs,
            )
        finally:
            await conn.close()

    async def _health_check(self, args: dict) -> ToolResult:
        """Confirm a model is registered, ready, and (if deployed) its k8s
        endpoint responds. Returns a structured status so a supervisor agent
        can pre-flight before a long inference run."""
        model_name = args.get("model_name", "")
        if not model_name:
            return ToolResult(content="Error: model_name is required", is_error=True)
        conn = await self._get_conn()
        try:
            row = await conn.fetchrow(
                """
                SELECT id, name, version, framework, status, file_uri, is_active
                FROM ml_models
                WHERE tenant_id = $1::uuid AND name = $2 AND status != 'deleted'
                ORDER BY is_active DESC, updated_at DESC LIMIT 1
                """,
                self.tenant_id,
                model_name,
            )
            if not row:
                return ToolResult(
                    content=json.dumps({"healthy": False, "reason": "model not found"}),
                    is_error=True,
                )
            dep_row = await conn.fetchrow(
                """
                SELECT endpoint_url, deployment_type, status
                FROM ml_model_deployments
                WHERE model_id = $1::uuid AND endpoint_url IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                row["id"],
            )
            checks: dict[str, Any] = {
                "model_name": row["name"],
                "model_version": row["version"],
                "framework": row["framework"],
                "registry_status": row["status"],
                "is_active": bool(row["is_active"]),
                "file_present": False,
                "k8s_endpoint": None,
                "k8s_endpoint_ok": None,
            }
            try:
                checks["file_present"] = bool(row["file_uri"]) and os.path.exists(
                    row["file_uri"]
                )
            except Exception:
                checks["file_present"] = False
            if dep_row and dep_row["endpoint_url"]:
                checks["k8s_endpoint"] = dep_row["endpoint_url"]
                try:
                    import httpx

                    async with httpx.AsyncClient(timeout=5.0) as client:
                        r = await client.get(
                            dep_row["endpoint_url"].rstrip("/") + "/health"
                        )
                        checks["k8s_endpoint_ok"] = r.status_code == 200
                except Exception:
                    checks["k8s_endpoint_ok"] = False
            healthy = row["status"] == "ready" and (
                checks["file_present"] or checks["k8s_endpoint_ok"]
            )
            checks["healthy"] = bool(healthy)
            return ToolResult(
                content=f"Health for '{row['name']}':\n\n{json.dumps(checks, indent=2)}",
                metadata=checks,
                is_error=not healthy,
            )
        finally:
            await conn.close()

    async def _get_model_info(self, args: dict) -> ToolResult:
        model_name = args.get("model_name", "")
        if not model_name:
            return ToolResult(content="Error: model_name is required", is_error=True)

        conn = await self._get_conn()
        try:
            row = await conn.fetchrow(
                """
                SELECT name, version, framework, status, description,
                       input_schema, output_schema, training_metrics, tags,
                       file_size_bytes, created_at
                FROM ml_models
                WHERE tenant_id = $1::uuid AND name = $2 AND status != 'deleted'
                ORDER BY updated_at DESC LIMIT 1
            """,
                self.tenant_id,
                model_name,
            )

            if not row:
                return ToolResult(
                    content=f"Model '{model_name}' not found.", is_error=True
                )

            info = {
                "name": row["name"],
                "version": row["version"],
                "framework": row["framework"],
                "status": row["status"],
                "description": row["description"],
                "input_schema": (
                    json.loads(row["input_schema"])
                    if isinstance(row["input_schema"], str)
                    else row["input_schema"]
                ),
                "output_schema": (
                    json.loads(row["output_schema"])
                    if isinstance(row["output_schema"], str)
                    else row["output_schema"]
                ),
                "training_metrics": (
                    json.loads(row["training_metrics"])
                    if isinstance(row["training_metrics"], str)
                    else row["training_metrics"]
                ),
                "tags": row["tags"],
                "file_size_mb": (
                    round(row["file_size_bytes"] / (1024 * 1024), 2)
                    if row["file_size_bytes"]
                    else None
                ),
            }
            return ToolResult(
                content=f"Model info for '{model_name}':\n\n{json.dumps(info, indent=2, default=str)}",
                metadata=info,
            )
        finally:
            await conn.close()
