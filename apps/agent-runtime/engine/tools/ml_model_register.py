"""Register a model file made earlier in the same run as an Abenix ML model."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from typing import Any

import httpx

from engine.tools.base import BaseTool, Effect, ToolResult

logger = logging.getLogger(__name__)

MAX_BYTES = 500 * 1024 * 1024
FRAMEWORK_EXT = {
    "sklearn": ".joblib",
    "xgboost": ".joblib",
    "onnx": ".onnx",
    "pytorch": ".pt",
}


def export_roots() -> list[str]:
    """Folders a run writes files to, the only places a model file is read from."""
    from engine.tools import code_executor, data_exporter

    roots = []
    for d in (code_executor.EXPORT_DIR, data_exporter.EXPORT_DIR):
        real = os.path.realpath(d)
        if real not in roots:
            roots.append(real)
    return roots


def resolve_export_path(path: str, roots: list[str]) -> str | None:
    """The real path of a file inside one of roots, None when it is anywhere else."""
    candidates = (
        [path] if os.path.isabs(path) else [os.path.join(r, path) for r in roots]
    )
    for c in candidates:
        real = os.path.realpath(c)
        for r in roots:
            try:
                inside = os.path.commonpath([real, r]) == r
            except ValueError:
                inside = False
            if inside and real != r and os.path.isfile(real):
                return real
    return None


def feature_schema(names: list[str], base: dict[str, Any] | None) -> dict[str, Any]:
    names = [str(n) for n in names]
    if base:
        return {**base, "features": names}
    n = len(names)
    return {
        "type": "object",
        "required": ["input_data"],
        "features": names,
        "properties": {
            "input_data": {
                "type": "array",
                "description": f"Array of samples, each an array of {n} numeric features in this order: {', '.join(names)}.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": n,
                    "maxItems": n,
                },
                "x-feature-order": names,
            }
        },
    }


def _error(resp: httpx.Response) -> dict[str, Any]:
    try:
        body = resp.json() or {}
    except ValueError:
        return {"message": resp.text[:300]}
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return err
    detail = body.get("detail") if isinstance(body, dict) else None
    return {"message": str(err or detail or f"HTTP {resp.status_code}")}


class MLModelRegisterTool(BaseTool):
    name = "ml_model_register"
    risk_tier = "medium"
    effect = Effect(
        kind="write", label="Register an ML model", target_param="model_name"
    )
    description = (
        "Register a trained model file made earlier in this run as an Abenix ML model, "
        "so a training pipeline can publish its own output. Give the file as file_path "
        "(a file the run saved to its export folder, for example with save_export in "
        "code_executor or with data_exporter) or as file_base64 (for example from a code "
        "step's output). The model is loaded and checked like an upload on the ML Models "
        "page, gets the next version of model_name and becomes the active version when it "
        "loads. It is owned by the user who started the run. Supported files: .joblib and "
        ".pkl (scikit-learn, XGBoost), .onnx, .pt and .pth (PyTorch)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "model_name": {
                "type": "string",
                "description": "Name in the registry. A new name starts at 1.0.0, an existing one gets its next version.",
            },
            "file_path": {
                "type": "string",
                "description": "Path of the model file in the run's export folder, or just its file name.",
            },
            "file_base64": {
                "type": "string",
                "description": "The model file as base64. Use instead of file_path.",
            },
            "filename": {
                "type": "string",
                "description": "File name with its extension, for example churn.joblib. Needed with file_base64 unless framework is set.",
            },
            "framework": {
                "type": "string",
                "enum": ["sklearn", "xgboost", "onnx", "pytorch"],
                "description": "Read from the file extension when left out.",
            },
            "version": {
                "type": "string",
                "description": "Version to register, for example 2.1.0. The next free version when left out.",
            },
            "description": {
                "type": "string",
                "description": "What the model predicts, shown on the ML Models page.",
            },
            "feature_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Feature order the model expects, so predictions can take rows by name.",
            },
            "input_schema": {
                "type": "object",
                "description": "JSON schema of the prediction input. Read from the model when left out.",
            },
            "output_schema": {
                "type": "object",
                "description": "JSON schema of the prediction output. Read from the model when left out.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Labels to find the model by.",
            },
        },
        "required": ["model_name"],
    }

    def __init__(
        self,
        *,
        tenant_id: str = "",
        execution_id: str = "",
        agent_id: str = "",
        user_id: str = "",
        user_role: str = "",
        api_base: str = "",
    ) -> None:
        self.tenant_id = str(tenant_id or "")
        self._execution_id = str(execution_id or "")
        self._agent_id = str(agent_id or "")
        self._user_id = str(user_id or "")
        self._user_role = user_role or "user"
        self._api_base = (
            api_base
            or os.environ.get("ABENIX_INTERNAL_URL", "")
            or os.environ.get("ABENIX_API_URL", "http://abenix-api:8000")
        )

    def _read(self, args: dict[str, Any]) -> tuple[str, bytes] | str:
        """(filename, bytes), or the reason the file cannot be used."""
        path = str(args.get("file_path") or "").strip()
        b64 = args.get("file_base64")
        framework = args.get("framework")
        if bool(path) == bool(b64):
            return "Give the model file as file_path or as file_base64, one of the two."
        filename = str(args.get("filename") or "").strip()
        if path:
            # the export area is shared by every tenant, so only this tenant's own folder is readable
            if not self.tenant_id:
                return "A model file can only be read for a known workspace. Pass it as file_base64."
            roots = [os.path.join(r, self.tenant_id) for r in export_roots()]
            real = resolve_export_path(path, roots)
            if real is None:
                return (
                    f"{path} is not a file in the run's export folder ({', '.join(roots)}). "
                    "Save the model there first, for example with save_export in code_executor, "
                    "or pass it as file_base64."
                )
            if os.path.getsize(real) > MAX_BYTES:
                return "The model file is over 500 MB."
            with open(real, "rb") as fh:
                return filename or os.path.basename(real), fh.read()
        if not isinstance(b64, str):
            return "file_base64 must be a base64 string."
        raw = b64.strip()
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        try:
            content = base64.b64decode("".join(raw.split()), validate=True)
        except (binascii.Error, ValueError):
            return "file_base64 is not valid base64."
        if len(content) > MAX_BYTES:
            return "The model file is over 500 MB."
        if not filename and framework in FRAMEWORK_EXT:
            filename = f"{args.get('model_name')}{FRAMEWORK_EXT[framework]}"
        if not filename:
            return (
                "With file_base64 give a filename such as model.joblib, or a framework."
            )
        return filename, content

    def _metadata(self, args: dict[str, Any]) -> dict[str, Any] | str:
        meta: dict[str, Any] = {
            "name": str(args.get("model_name") or "").strip(),
            "description": str(args.get("description") or ""),
        }
        for key in ("framework", "version"):
            if args.get(key):
                meta[key] = str(args[key])
        for key in ("input_schema", "output_schema"):
            val = args.get(key)
            if val is not None and not isinstance(val, dict):
                return f"{key} must be a JSON object."
            if val:
                meta[key] = val
        names = args.get("feature_names")
        if names:
            if not isinstance(names, list):
                return "feature_names must be a list of names."
            meta["input_schema"] = feature_schema(names, meta.get("input_schema"))
        tags = args.get("tags")
        if tags:
            if not isinstance(tags, list):
                return "tags must be a list of strings."
            meta["tags"] = [str(t) for t in tags]
        return meta

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments.get("model_name") or "").strip()
        if not name:
            return ToolResult(content="model_name is required.", is_error=True)
        if not self._user_id:
            return ToolResult(
                content="ml_model_register needs the user who started the run, a model always has an owner.",
                is_error=True,
            )
        meta = self._metadata(arguments)
        if isinstance(meta, str):
            return ToolResult(content=meta, is_error=True)
        got = self._read(arguments)
        if isinstance(got, str):
            return ToolResult(content=got, is_error=True)
        filename, content = got
        if not content:
            return ToolResult(content="The model file is empty.", is_error=True)

        from engine.tools.invoke_agent import mint_user_token

        token = mint_user_token(self._user_id, self.tenant_id, self._user_role)
        if not token:
            return ToolResult(
                content="Could not sign a token for the calling user (JWT_PRIVATE_KEY or SECRET_KEY missing on the runtime).",
                is_error=True,
            )
        try:
            async with httpx.AsyncClient(
                base_url=self._api_base, timeout=300.0
            ) as client:
                resp = await client.post(
                    "/api/ml-models",
                    headers={"Authorization": f"Bearer {token}"},
                    data={"metadata": json.dumps(meta)},
                    files={"file": (filename, content, "application/octet-stream")},
                )
        except httpx.HTTPError as e:
            return ToolResult(
                content=f"Could not reach the model registry: {e}", is_error=True
            )

        if resp.status_code >= 400:
            err = _error(resp)
            code = err.get("error_code")
            message = err.get("message") or f"HTTP {resp.status_code}"
            if code == "MODEL_LOAD_FAILED":
                stored = ((err.get("details") or {}).get("model")) or {}
                message = (
                    f"The file did not load as a model: {message} It is kept as inactive "
                    f"version {stored.get('version', '?')} with status error, the active version did not change."
                )
            return ToolResult(
                content=message,
                is_error=True,
                metadata={
                    "status": resp.status_code,
                    "failure_code": code or "REGISTER_FAILED",
                    "model_name": name,
                },
            )

        model = (resp.json() or {}).get("data") or {}
        out = {
            "model_id": model.get("id"),
            "model_name": model.get("name", name),
            "version": model.get("version"),
            "framework": model.get("framework"),
            "status": model.get("status"),
            "is_active": model.get("is_active"),
            "input_schema": model.get("input_schema"),
            "output_schema": model.get("output_schema"),
            "message": (
                f"Registered {model.get('name', name)} version {model.get('version')}. "
                f"Use the ml_model tool with model_name {model.get('name', name)} to predict."
            ),
        }
        logger.info(
            "ml_model_register: %s %s registered by run %s",
            out["model_name"],
            out["version"],
            self._execution_id or "-",
        )
        return ToolResult(
            content=json.dumps(out),
            metadata={
                "model_id": out["model_id"],
                "model_name": out["model_name"],
                "version": out["version"],
            },
        )
