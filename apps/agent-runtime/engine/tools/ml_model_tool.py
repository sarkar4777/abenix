"""ML Model Tool — run inference on registered ML models."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# LRU-style cache for loaded models (local mode)
_MODEL_CACHE: dict[str, Any] = {}
_MAX_CACHE = 5


class MLModelTool(BaseTool):
    name = "ml_model"
    description = (
        "Run inference on registered ML models (sklearn, PyTorch, ONNX, XGBoost). "
        "Use 'list_models' to see available models with their frameworks and status. "
        "Use 'predict' with a model_name and input_data to get predictions. "
        "Use 'get_model_info' to see a model's input/output schemas and deployment status."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["list_models", "predict", "get_model_info"],
                "description": "Which operation to perform",
            },
            "model_name": {
                "type": "string",
                "description": "Name of the model (for predict and get_model_info)",
            },
            "model_version": {
                "type": "string",
                "description": "Version of the model (default: latest)",
                "default": "latest",
            },
            "input_data": {
                "type": "object",
                "description": "Input features for prediction. Usually {features: [1.0, 2.0, ...]} or {col1: val1, col2: val2}",
            },
        },
        "required": ["operation"],
    }

    def __init__(self, db_url: str = "", tenant_id: str = "") -> None:
        self.db_url = db_url or os.environ.get("DATABASE_URL", "")
        self.tenant_id = tenant_id

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

        try:
            if op == "list_models":
                return await self._list_models()
            elif op == "predict":
                return await self._predict(arguments)
            elif op == "get_model_info":
                return await self._get_model_info(arguments)
            else:
                return ToolResult(content=f"Unknown operation: {op}", is_error=True)
        except Exception as e:
            logger.error("MLModelTool error: %s", e)
            return ToolResult(content=f"ML model error: {e}", is_error=True)

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

    async def _predict(self, args: dict) -> ToolResult:
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
                    row["file_uri"],
                    row["framework"],
                    input_data,
                )
                source = "local"

            # Format output for the agent
            result_text = (
                f"Prediction from model '{row['name']}' v{row['version']} ({source} inference):\n\n"
                f"{json.dumps(predictions, indent=2)}"
            )
            return ToolResult(
                content=result_text,
                metadata={
                    "model_name": row["name"],
                    "model_version": row["version"],
                    "framework": row["framework"],
                    "source": source,
                },
            )
        finally:
            await conn.close()

    async def _local_predict(
        self, file_uri: str, framework: str, input_data: Any
    ) -> Any:
        """Load model from disk and run inference."""
        import numpy as np

        # Parse input
        if isinstance(input_data, dict):
            features = input_data.get("features") or list(input_data.values())
        elif isinstance(input_data, list):
            features = input_data
        else:
            raise ValueError(f"input_data must be dict or list, got {type(input_data)}")

        X = (
            np.array([features])
            if not isinstance(features[0], (list, np.ndarray))
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
                result["predicted_class"] = (
                    str(model.classes_[preds[0]]) if preds.size > 0 else None
                )
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
