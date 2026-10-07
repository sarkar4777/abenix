"""ML Model Registry — upload, deploy, and serve ML models."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.user import User
from models.ml_model import (
    MLModel,
    MLModelDeployment,
    MLModelFramework,
    MLModelStatus,
    DeploymentType,
    DeploymentStatus,
)
from models.ml_model_invocation import MLModelInvocation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ml-models", tags=["ml-models"])

UPLOAD_DIR = Path(os.environ.get("ML_MODELS_DIR", "/tmp/ml-models"))
ALLOWED_EXTENSIONS = {
    ".pkl": MLModelFramework.SKLEARN,
    ".joblib": MLModelFramework.SKLEARN,
    ".pt": MLModelFramework.PYTORCH,
    ".pth": MLModelFramework.PYTORCH,
    ".onnx": MLModelFramework.ONNX,
    ".h5": MLModelFramework.TENSORFLOW,
    ".keras": MLModelFramework.TENSORFLOW,
    ".xgb": MLModelFramework.XGBOOST,
}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
# formats with no runtime behind them, refused with a conversion hint
UNRUNNABLE = {
    MLModelFramework.TENSORFLOW: (
        "TensorFlow/Keras files (.h5, .keras) cannot run on Abenix yet. "
        "Convert the model to ONNX (for example with tf2onnx) and upload the .onnx file."
    ),
    MLModelFramework.CUSTOM: (
        "Abenix cannot tell how to run this file. Upload a scikit-learn or XGBoost model "
        "saved with joblib (.joblib, .pkl), an ONNX model (.onnx) or a PyTorch model (.pt, .pth)."
    ),
}
FRAMEWORK_LABELS = {
    MLModelFramework.SKLEARN: "scikit-learn",
    MLModelFramework.XGBOOST: "XGBoost",
    MLModelFramework.ONNX: "ONNX",
    MLModelFramework.PYTORCH: "PyTorch",
    MLModelFramework.TENSORFLOW: "TensorFlow",
    MLModelFramework.CUSTOM: "custom",
}
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,49}$")


def _deployment_dict(d: MLModelDeployment) -> dict:
    return {
        "id": str(d.id),
        "deployment_type": d.deployment_type.value,
        "endpoint_url": d.endpoint_url,
        "replicas": d.replicas,
        "status": d.status.value,
        "pod_name": d.pod_name,
        "service_name": d.service_name,
        "k8s_namespace": d.k8s_namespace,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def _status_message(m: MLModel) -> str | None:
    tm = m.training_metrics if isinstance(m.training_metrics, dict) else {}
    if m.status == MLModelStatus.ERROR:
        return tm.get("validation_error") or (
            "This model failed validation. Upload a new version."
        )
    return None


def _serialize(m: MLModel, deployments: list[MLModelDeployment] | None = None) -> dict:
    return {
        "id": str(m.id),
        "name": m.name,
        "version": m.version,
        "framework": m.framework.value,
        "description": m.description,
        "file_uri": m.file_uri,
        "file_size_bytes": m.file_size_bytes,
        "original_filename": m.original_filename,
        "input_schema": m.input_schema,
        "output_schema": m.output_schema,
        "status": m.status.value,
        "status_message": _status_message(m),
        "is_active": m.is_active,
        "training_metrics": m.training_metrics,
        "tags": m.tags,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "deployments": [_deployment_dict(d) for d in (deployments or [])],
    }


async def _serialize_with_deployments(m: MLModel, db: AsyncSession) -> dict:
    result = await db.execute(
        select(MLModelDeployment).where(MLModelDeployment.model_id == m.id)
    )
    return _serialize(m, deployments=list(result.scalars().all()))


async def _serialize_many(models: list[MLModel], db: AsyncSession) -> list[dict]:
    if not models:
        return []
    ids = [m.id for m in models]
    result = await db.execute(
        select(MLModelDeployment).where(MLModelDeployment.model_id.in_(ids))
    )
    deps = list(result.scalars().all())
    by_model: dict = {}
    for d in deps:
        by_model.setdefault(d.model_id, []).append(d)
    return [_serialize(m, deployments=by_model.get(m.id, [])) for m in models]


def _detect_framework(filename: str, explicit: str | None = None) -> MLModelFramework:
    if explicit:
        try:
            return MLModelFramework(explicit)
        except ValueError:
            pass
    ext = Path(filename).suffix.lower()
    return ALLOWED_EXTENSIONS.get(ext, MLModelFramework.CUSTOM)


def _load_check(file_path: str, framework: MLModelFramework) -> dict:
    # raises with the loader's own words when the file is not a usable model
    if framework in (MLModelFramework.SKLEARN, MLModelFramework.XGBOOST):
        import joblib

        model = joblib.load(file_path)
        if not hasattr(model, "predict"):
            raise ValueError(
                f"the file holds a {type(model).__name__}, which has no predict() method"
            )
        info: dict = {"type": type(model).__name__}
        if hasattr(model, "n_features_in_"):
            info["n_features"] = int(model.n_features_in_)
        if hasattr(model, "feature_names_in_"):
            info["feature_names"] = [str(f) for f in model.feature_names_in_]
        if hasattr(model, "classes_"):
            info["classes"] = [str(c) for c in model.classes_]
        return info
    if framework == MLModelFramework.ONNX:
        import onnxruntime as ort

        sess = ort.InferenceSession(file_path)
        inputs = [
            {"name": i.name, "shape": i.shape, "type": i.type}
            for i in sess.get_inputs()
        ]
        outputs = [
            {"name": o.name, "shape": o.shape, "type": o.type}
            for o in sess.get_outputs()
        ]
        info = {"inputs": inputs, "outputs": outputs}
        shape = inputs[0]["shape"] if inputs else None
        if isinstance(shape, list) and len(shape) == 2 and isinstance(shape[1], int):
            info["n_features"] = shape[1]
        return info
    if framework == MLModelFramework.PYTORCH:
        import torch

        model = torch.load(file_path, map_location="cpu", weights_only=False)
        if not callable(model):
            raise ValueError(
                "the file holds weights only (a state_dict). Save the whole model "
                "with torch.save(model) or export it to ONNX"
            )
        return {"type": type(model).__name__}
    raise ValueError(UNRUNNABLE.get(framework, "unsupported framework"))


async def _validate_model(
    file_path: str, framework: MLModelFramework
) -> tuple[dict | None, str | None]:
    """Load the model once. Returns (info, None) or (None, plain reason)."""
    label = FRAMEWORK_LABELS.get(framework, framework.value)
    try:
        return await asyncio.to_thread(_load_check, file_path, framework), None
    except ImportError as e:
        logger.warning("Model validation failed, missing library: %s", e)
        return None, (
            f"The {label} runtime is not installed on this server ({e.name or e}), "
            "so the model cannot be loaded. Export it to ONNX and upload the .onnx file."
        )
    except Exception as e:
        logger.warning("Model validation failed: %s", e)
        msg = str(e).strip().rstrip(".")
        detail = f"{type(e).__name__}: {msg}" if msg else type(e).__name__
        return None, (
            f"This file could not be loaded as a {label} model. "
            "Check it is the trained model saved with joblib.dump, pickle.dump, "
            "torch.save or an ONNX exporter, not a renamed or corrupted file. "
            f"Technical detail: {detail}."
        )


def _parse_version(v: str) -> tuple[int, ...] | None:
    parts = (v or "").lstrip("vV").split(".")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def _next_version(existing: list[str]) -> str:
    """Next free version for a model name: 1.0.0, then a minor bump of the highest."""
    parsed = [p for p in (_parse_version(v) for v in existing) if p]
    if not parsed:
        candidate = (1, 0, 0)
    else:
        top = list(max(parsed))
        while len(top) < 3:
            top.append(0)
        candidate = (top[0], top[1] + 1, 0)
    taken = set(existing)
    while ".".join(map(str, candidate)) in taken:
        candidate = (candidate[0], candidate[1] + 1, 0)
    return ".".join(map(str, candidate))


def _feature_names(model: MLModel | None, info: dict | None = None) -> list[str]:
    schema = (model.input_schema if model is not None else None) or {}
    if isinstance(schema, dict):
        if isinstance(schema.get("features"), list):
            return [str(f) for f in schema["features"]]
        prop = (schema.get("properties") or {}).get("input_data") or {}
        if isinstance(prop, dict) and isinstance(prop.get("x-feature-order"), list):
            return [str(f) for f in prop["x-feature-order"]]
    tm = info or (model.training_metrics if model is not None else None) or {}
    if isinstance(tm, dict) and isinstance(tm.get("feature_names"), list):
        return [str(f) for f in tm["feature_names"]]
    return []


class PredictInputError(ValueError):
    """Input the model cannot take. Reported to the caller as 422."""


def _feature_count_message(expected: int, sent: int, names: list[str]) -> str:
    noun = "feature" if expected == 1 else "features"
    msg = f"This model expects {expected} {noun}, you sent {sent}."
    if names and len(names) == expected:
        msg += f" Send them in this order: {', '.join(names)}."
    return msg


def _to_matrix(input_data: Any, names: list[str]) -> Any:
    """Turn the accepted input shapes into rows of features."""
    import numpy as np

    if isinstance(input_data, str):
        try:
            input_data = json.loads(input_data)
        except ValueError:
            pass
    if isinstance(input_data, dict):
        if "features" in input_data:
            features = input_data["features"]
        elif names and set(input_data) <= set(names):
            missing = [n for n in names if n not in input_data]
            if missing:
                raise PredictInputError(
                    f"Missing {', '.join(missing)}. This model expects "
                    f"{len(names)} features: {', '.join(names)}."
                )
            features = [input_data[n] for n in names]
        else:
            features = list(input_data.values())
    elif isinstance(input_data, list):
        features = input_data
    else:
        raise PredictInputError(
            'input_data must be a list of numbers, a list of rows, or {"features": [...]}'
        )
    if not isinstance(features, list) or not features:
        raise PredictInputError("input_data has no feature values.")
    first = features[0]
    if isinstance(first, str):
        return features
    try:
        rows = np.array(
            features if isinstance(first, list) else [features], dtype=float
        )
    except (TypeError, ValueError):
        raise PredictInputError(
            "Every feature value must be a number, and every row the same length."
        )
    if rows.ndim != 2:
        raise PredictInputError("Each row must be a flat list of numbers.")
    return rows


def _infer_ml_schemas(
    validation: dict | None, framework: MLModelFramework
) -> tuple[dict | None, dict | None]:
    """Build JSON schemas from validation introspection."""
    if not validation:
        return None, None

    if framework in (MLModelFramework.SKLEARN, MLModelFramework.XGBOOST):
        n = validation.get("n_features")
        names = validation.get("feature_names") or []
        input_schema: dict = {
            "type": "object",
            "required": ["input_data"],
            "properties": {
                "input_data": {
                    "type": "array",
                    "description": (
                        f"Array of samples; each sample is an array of {n} numeric features."
                        if n
                        else "Array of samples; each sample is an array of numeric features."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        **({"minItems": n, "maxItems": n} if n else {}),
                    },
                },
            },
        }
        if names:
            input_schema["properties"]["input_data"]["x-feature-order"] = names
        classes = validation.get("classes")
        output_schema: dict = {
            "type": "object",
            "properties": {
                "predictions": {
                    "type": "array",
                    "items": {"type": "string"} if classes else {"type": "number"},
                    "description": "One prediction per input sample.",
                },
            },
        }
        if classes:
            output_schema["properties"]["classes"] = {
                "type": "array",
                "items": {"type": "string"},
                "description": "Class labels in the order used by probabilities[].",
                "enum": [classes],
            }
            output_schema["properties"]["probabilities"] = {
                "type": "array",
                "description": "Predicted probability per class, one row per input sample.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": len(classes),
                    "maxItems": len(classes),
                },
            }
        return input_schema, output_schema

    if framework == MLModelFramework.ONNX:
        inputs = validation.get("inputs") or []
        outputs = validation.get("outputs") or []
        if not inputs:
            return None, None
        input_schema = {
            "type": "object",
            "properties": {
                "input_data": {
                    "type": "array",
                    "description": f"ONNX input tensor(s): {', '.join(i['name'] for i in inputs)}",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
            },
            "required": ["input_data"],
        }
        output_schema = {
            "type": "object",
            "properties": {
                "predictions": {
                    "type": "array",
                    "description": f"ONNX output tensor(s): {', '.join(o['name'] for o in outputs)}",
                },
            },
        }
        return input_schema, output_schema

    return None, None


async def _existing_versions(db: AsyncSession, tenant_id, name: str) -> list[str]:
    rows = await db.execute(
        select(MLModel.version).where(
            MLModel.tenant_id == tenant_id,
            MLModel.name == name,
            MLModel.status != MLModelStatus.DELETED,
        )
    )
    return [str(v) for v in rows.scalars().all()]


async def _resolve_version(
    db: AsyncSession, tenant_id, name: str, requested: str
) -> tuple[str | None, JSONResponse | None]:
    existing = await _existing_versions(db, tenant_id, name)
    nxt = _next_version(existing)
    if not requested:
        return nxt, None
    if not _VERSION_RE.match(requested):
        return None, error(
            "Version can use letters, digits, dots, dashes and underscores, up to 50 characters (for example 1.2.0).",
            422,
            error_code="INVALID_VERSION",
            details={"next_version": nxt},
        )
    if requested in existing:
        return None, error(
            f"{name} already has a version {requested}. "
            f"Upload it as version {nxt} instead, or delete the old version first.",
            409,
            error_code="VERSION_EXISTS",
            details={"next_version": nxt, "existing_versions": existing},
        )
    return requested, None


async def _register_model(
    db: AsyncSession,
    user: User,
    *,
    content: bytes,
    filename: str,
    name: str,
    version: str,
    framework: MLModelFramework,
    description: str,
    input_schema: dict | None,
    output_schema: dict | None,
    tags: list,
) -> tuple[MLModel | None, str | None, JSONResponse | None]:
    """Store, load-check and record a model. Returns (model, load_error, failure)."""
    model_dir = UPLOAD_DIR / str(user.tenant_id)
    model_dir.mkdir(parents=True, exist_ok=True)
    file_path = model_dir / f"{uuid.uuid4().hex[:12]}_{Path(filename).name}"
    file_path.write_bytes(content)
    from app.core.artifact_store import ArtifactStoreError, mirror

    try:
        await mirror(file_path)
    except ArtifactStoreError as e:
        file_path.unlink(missing_ok=True)
        return None, None, error(str(e), 503)

    validation, reason = await _validate_model(str(file_path), framework)
    ok = validation is not None

    # only a loadable upload replaces the active version
    if ok:
        from sqlalchemy import update as sql_update

        await db.execute(
            sql_update(MLModel)
            .where(
                MLModel.tenant_id == user.tenant_id,
                MLModel.name == name,
                MLModel.is_active.is_(True),
            )
            .values(is_active=False)
        )

    model = MLModel(
        tenant_id=user.tenant_id,
        name=name,
        version=version,
        framework=framework,
        description=description,
        file_uri=str(file_path),
        file_size_bytes=len(content),
        original_filename=Path(filename).name,
        input_schema=input_schema,
        output_schema=output_schema,
        status=MLModelStatus.READY if ok else MLModelStatus.ERROR,
        is_active=ok,
        training_metrics=validation if ok else {"validation_error": reason},
        tags=tags,
        created_by=user.id,
    )
    if ok and (not input_schema or not output_schema):
        # inferred schemas give agents and the test form a shape to send
        inferred_in, inferred_out = _infer_ml_schemas(validation, framework)
        if not input_schema and inferred_in:
            model.input_schema = inferred_in
        if not output_schema and inferred_out:
            model.output_schema = inferred_out
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model, reason, None


@router.post("")
async def upload_model(
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Upload a trained model file with metadata.

    A file that cannot be loaded is kept as an inactive version in status
    error with the reason, and the call answers 422 with that reason.
    """
    if not file.filename:
        return error("No file provided", 400)

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS and ext not in (".bin",):
        return error(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS.keys())}",
            400,
        )

    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError:
        return error("Invalid metadata JSON", 400)
    if not isinstance(meta, dict):
        return error("metadata must be a JSON object", 400)

    name = str(meta.get("name") or Path(file.filename).stem).strip()[:255]
    if not name:
        return error("Model name is required", 422)
    framework = _detect_framework(file.filename, meta.get("framework"))
    if framework in UNRUNNABLE:
        return error(UNRUNNABLE[framework], 422, error_code="UNSUPPORTED_FRAMEWORK")
    input_schema = meta.get("input_schema")
    output_schema = meta.get("output_schema")
    for label, schema in (
        ("input_schema", input_schema),
        ("output_schema", output_schema),
    ):
        if schema is not None and not isinstance(schema, dict):
            return error(f"{label} must be a JSON object", 422)
    tags = meta.get("tags") or []
    if not isinstance(tags, list):
        return error("tags must be a list of strings", 422)

    version, conflict = await _resolve_version(
        db, user.tenant_id, name, str(meta.get("version") or "").strip()
    )
    if conflict is not None:
        return conflict

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        return error(f"File too large. Max: {MAX_FILE_SIZE // (1024*1024)}MB", 400)
    if not content:
        return error("The file is empty", 422)

    model, reason, failure = await _register_model(
        db,
        user,
        content=content,
        filename=file.filename,
        name=name,
        version=version,
        framework=framework,
        description=str(meta.get("description") or ""),
        input_schema=input_schema,
        output_schema=output_schema,
        tags=[str(t) for t in tags][:32],
    )
    if failure is not None:
        return failure
    if reason:
        return error(
            reason,
            422,
            error_code="MODEL_LOAD_FAILED",
            details={"model": _serialize(model)},
        )
    return success(_serialize(model), status_code=201)


@router.post("/samples/{sample_id}")
async def register_sample_model(
    sample_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Register a small sample model shipped with Abenix so a new user can try the page."""
    from app.core import ml_samples

    spec = ml_samples.SAMPLES.get(sample_id)
    if spec is None:
        return error(
            f"Unknown sample '{sample_id}'. Available: {', '.join(ml_samples.SAMPLES)}",
            404,
        )
    existing = (
        await db.execute(
            select(MLModel)
            .where(
                MLModel.tenant_id == user.tenant_id,
                MLModel.name == spec["name"],
                MLModel.created_by == user.id,
                MLModel.status == MLModelStatus.READY,
            )
            .order_by(MLModel.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return success(await _serialize_with_deployments(existing, db))

    src = ml_samples.sample_file(sample_id)
    if not src.exists():
        try:
            await asyncio.to_thread(ml_samples.build_iris, src)
        except Exception as e:
            logger.warning("sample model build failed: %s", e)
            return error("The sample model file is missing from this install.", 500)
    version = _next_version(await _existing_versions(db, user.tenant_id, spec["name"]))
    model, reason, failure = await _register_model(
        db,
        user,
        content=src.read_bytes(),
        filename=spec["filename"],
        name=spec["name"],
        version=version,
        framework=MLModelFramework.SKLEARN,
        description=spec["description"],
        input_schema=spec["input_schema"],
        output_schema=spec["output_schema"],
        tags=list(spec["tags"]),
    )
    if failure is not None:
        return failure
    if reason:
        return error(
            reason,
            500,
            error_code="MODEL_LOAD_FAILED",
            details={"model": _serialize(model)},
        )
    return success(_serialize(model), status_code=201)


@router.get("")
async def list_models(
    search: str = Query(""),
    framework: str = Query(""),
    status: str = Query(""),
    scope: str = Query("all"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List ML models visible to the caller."""
    from app.core.permissions import (
        accessible_resource_ids,
        apply_resource_scope,
        is_admin,
    )

    if scope == "tenant" and not is_admin(user):
        return error("scope=tenant requires admin role", 403)
    accessible = await accessible_resource_ids(db, user, kind="ml_model")
    query = select(MLModel).where(MLModel.status != MLModelStatus.DELETED)
    query = apply_resource_scope(
        query,
        MLModel,
        user,
        kind="ml_model",
        scope=scope,
        accessible_ids=accessible,
    )
    if search:
        query = query.where(MLModel.name.ilike(f"%{search}%"))
    if framework:
        query = query.where(MLModel.framework == framework)
    if status:
        query = query.where(MLModel.status == status)
    query = query.order_by(MLModel.updated_at.desc())
    result = await db.execute(query)
    models = list(result.scalars().all())
    return success(await _serialize_many(models, db))


@router.get("/{model_id}")
async def get_model(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get model detail with deployments."""
    result = await db.execute(
        select(MLModel).where(
            MLModel.id == model_id,
            MLModel.tenant_id == user.tenant_id,
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        return error("Model not found", 404)
    return success(await _serialize_with_deployments(model, db))


@router.put("/{model_id}")
async def update_model_metadata(
    model_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Update description / input_schema / output_schema / tags on a model."""
    result = await db.execute(
        select(MLModel).where(
            MLModel.id == model_id,
            MLModel.tenant_id == user.tenant_id,
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        return error("Model not found", 404)
    if "description" in body:
        model.description = (body.get("description") or "")[:2000]
    if "input_schema" in body:
        schema = body.get("input_schema")
        if schema is not None and not isinstance(schema, dict):
            return error("input_schema must be a JSON object or null", 400)
        model.input_schema = schema
    if "output_schema" in body:
        schema = body.get("output_schema")
        if schema is not None and not isinstance(schema, dict):
            return error("output_schema must be a JSON object or null", 400)
        model.output_schema = schema
    if "tags" in body:
        tags = body.get("tags")
        if not isinstance(tags, list):
            return error("tags must be a list of strings", 400)
        model.tags = [str(t) for t in tags][:32]
    await db.commit()
    await db.refresh(model)
    return success(await _serialize_with_deployments(model, db))


@router.delete("/{model_id}")
async def delete_model(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Delete a model and its file."""
    result = await db.execute(
        select(MLModel).where(
            MLModel.id == model_id,
            MLModel.tenant_id == user.tenant_id,
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        return error("Model not found", 404)

    # the file and its durable copy
    from app.core.artifact_store import remove

    if model.file_uri:
        await remove(model.file_uri)

    model.status = MLModelStatus.DELETED
    await db.commit()
    return success({"deleted": True})


@router.post("/{model_id}/deploy")
async def deploy_model(
    model_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Deploy a model locally (in-process) or as a k8s pod.

    Idempotent per model and target: a second call while one is deploying
    or running with the same settings returns that deployment.
    """
    # row lock serialises concurrent deploys of one model
    result = await db.execute(
        select(MLModel)
        .where(
            MLModel.id == model_id,
            MLModel.tenant_id == user.tenant_id,
            MLModel.status != MLModelStatus.DELETED,
        )
        .with_for_update()
    )
    model = result.scalar_one_or_none()
    if not model:
        return error("Model not found", 404)
    if model.status != MLModelStatus.READY:
        return error(
            "This model failed validation, so it cannot be deployed. "
            + (_status_message(model) or ""),
            409,
            error_code="MODEL_NOT_READY",
        )

    dep_type = body.get("deployment_type", "local")
    replicas = int(body.get("replicas", 1))
    if replicas < 1 or replicas > 10:
        return error(
            "replicas must be between 1 and 10",
            400,
            error_code="INVALID_REPLICAS",
            details={"received": replicas},
        )
    _RESOURCE_PRESETS = {
        "small": {
            "req_cpu": "100m",
            "req_mem": "256Mi",
            "lim_cpu": "500m",
            "lim_mem": "1Gi",
        },
        "medium": {
            "req_cpu": "250m",
            "req_mem": "512Mi",
            "lim_cpu": "1",
            "lim_mem": "2Gi",
        },
        "large": {
            "req_cpu": "500m",
            "req_mem": "1Gi",
            "lim_cpu": "2",
            "lim_mem": "4Gi",
        },
    }
    preset_name = (body.get("resource_preset") or "medium").lower()
    if preset_name not in _RESOURCE_PRESETS:
        return error(
            f"resource_preset must be one of {list(_RESOURCE_PRESETS)}",
            400,
            error_code="INVALID_RESOURCE_PRESET",
            details={"received": preset_name},
        )
    preset = _RESOURCE_PRESETS[preset_name]

    try:
        dtype = DeploymentType(dep_type)
    except ValueError:
        return error("Invalid deployment_type. Use 'local' or 'k8s'.", 400)

    current = (
        (
            await db.execute(
                select(MLModelDeployment)
                .where(
                    MLModelDeployment.model_id == model.id,
                    MLModelDeployment.deployment_type == dtype,
                    MLModelDeployment.status.in_(
                        [DeploymentStatus.DEPLOYING, DeploymentStatus.RUNNING]
                    ),
                )
                .order_by(MLModelDeployment.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    for dep in current:
        same = dtype == DeploymentType.LOCAL or (
            dep.replicas == replicas
            and (dep.config or {}).get("resource_preset", "medium") == preset_name
        )
        if same:
            await db.commit()
            return success(
                {
                    "deployment_id": str(dep.id),
                    "deployment_type": dep.deployment_type.value,
                    "status": dep.status.value,
                    "endpoint_url": dep.endpoint_url,
                    "already_deployed": True,
                }
            )

    if dtype == DeploymentType.K8S:
        # Role gate: only admins can spawn cluster pods.
        role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
        if role_val not in ("admin", "owner"):
            return error(
                "K8s model deployments require an admin role. "
                "Use deployment_type='local' for in-process serving.",
                403,
            )
        # Per-tenant quota: count currently-active k8s deployments for
        # this tenant. Prevents a single tenant from exhausting the
        # cluster even with admin role.
        max_k8s = int(os.environ.get("ML_MODEL_MAX_K8S_PER_TENANT", "10"))
        q = await db.execute(
            select(MLModelDeployment)
            .join(MLModel, MLModel.id == MLModelDeployment.model_id)
            .where(
                MLModel.tenant_id == user.tenant_id,
                MLModelDeployment.deployment_type == DeploymentType.K8S,
                MLModelDeployment.status.in_(
                    [DeploymentStatus.DEPLOYING, DeploymentStatus.RUNNING]
                ),
            )
        )
        active = q.scalars().all()
        if len(active) >= max_k8s:
            return error(
                f"Tenant at k8s deploy cap ({len(active)}/{max_k8s}). "
                "Undeploy an existing model before deploying another.",
                429,
            )

    deployment = MLModelDeployment(
        model_id=model.id,
        deployment_type=dtype,
        replicas=replicas,
        status=DeploymentStatus.DEPLOYING,
        config=(
            {"resource_preset": preset_name} if dtype == DeploymentType.K8S else None
        ),
    )
    db.add(deployment)
    await db.commit()
    await db.refresh(deployment)

    if dtype == DeploymentType.LOCAL:
        # Local: just mark as running (the tool will load in-process)
        deployment.status = DeploymentStatus.RUNNING
        deployment.endpoint_url = None
        await db.commit()
    elif dtype == DeploymentType.K8S:
        # K8s: create Deployment + Service
        try:
            svc_name = f"ml-model-{str(model.id)[:8]}"
            namespace = deployment.k8s_namespace

            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except Exception:
                config.load_kube_config()

            apps_v1 = client.AppsV1Api()
            core_v1 = client.CoreV1Api()

            download_url = f"http://abenix-api.{namespace}.svc.cluster.local:8000/api/ml-models/{model.id}/download"
            from app.core.security import create_access_token

            fetch_token = create_access_token(
                user.id,
                user.tenant_id,
                user.role.value if hasattr(user.role, "value") else str(user.role),
            )

            image_ref = os.environ.get(
                "ML_MODEL_SERVING_IMAGE",
                "localhost:5000/abenix/model-serving:latest",
            )
            container = client.V1Container(
                name="model-server",
                image=image_ref,
                image_pull_policy="IfNotPresent",
                ports=[client.V1ContainerPort(container_port=8080)],
                env=[
                    client.V1EnvVar(name="MODEL_URI", value=download_url),
                    client.V1EnvVar(
                        name="MODEL_FRAMEWORK", value=model.framework.value
                    ),
                    client.V1EnvVar(
                        name="MODEL_AUTH_HEADER", value=f"Bearer {fetch_token}"
                    ),
                ],
                resources=client.V1ResourceRequirements(
                    requests={"cpu": preset["req_cpu"], "memory": preset["req_mem"]},
                    limits={"cpu": preset["lim_cpu"], "memory": preset["lim_mem"]},
                ),
            )

            # Deployment
            dep_spec = client.V1Deployment(
                api_version="apps/v1",
                kind="Deployment",
                metadata=client.V1ObjectMeta(
                    name=svc_name,
                    namespace=namespace,
                    labels={
                        "app": "abenix-model-serving",
                        "model-id": str(model.id)[:8],
                    },
                ),
                spec=client.V1DeploymentSpec(
                    replicas=replicas,
                    selector=client.V1LabelSelector(
                        match_labels={
                            "app": "abenix-model-serving",
                            "model-id": str(model.id)[:8],
                        },
                    ),
                    template=client.V1PodTemplateSpec(
                        metadata=client.V1ObjectMeta(
                            labels={
                                "app": "abenix-model-serving",
                                "model-id": str(model.id)[:8],
                            },
                        ),
                        spec=client.V1PodSpec(containers=[container]),
                    ),
                ),
            )
            from kubernetes.client.exceptions import ApiException as _K8sApi

            try:
                apps_v1.create_namespaced_deployment(namespace=namespace, body=dep_spec)
            except _K8sApi as e:
                if e.status != 409:
                    raise
                # Already exists — replace spec so image/env refresh
                apps_v1.replace_namespaced_deployment(
                    name=svc_name, namespace=namespace, body=dep_spec
                )

            # Service
            svc_spec = client.V1Service(
                api_version="v1",
                kind="Service",
                metadata=client.V1ObjectMeta(name=svc_name, namespace=namespace),
                spec=client.V1ServiceSpec(
                    selector={
                        "app": "abenix-model-serving",
                        "model-id": str(model.id)[:8],
                    },
                    ports=[client.V1ServicePort(port=8080, target_port=8080)],
                    type="ClusterIP",
                ),
            )
            try:
                core_v1.create_namespaced_service(namespace=namespace, body=svc_spec)
            except _K8sApi as e:
                if e.status != 409:
                    raise
                # Service already exists — leave it (selectors match)

            # Mark ANY older k8s deployment rows for this model as
            # superseded so we don't end up with "2 failed + 1 running"
            # drift in the UI after a retry.
            from sqlalchemy import update as _update

            await db.execute(
                _update(MLModelDeployment)
                .where(
                    MLModelDeployment.model_id == model.id,
                    MLModelDeployment.deployment_type == DeploymentType.K8S,
                    MLModelDeployment.id != deployment.id,
                    MLModelDeployment.status.in_(
                        [
                            DeploymentStatus.FAILED,
                            DeploymentStatus.DEPLOYING,
                            DeploymentStatus.RUNNING,
                        ]
                    ),
                )
                .values(status=DeploymentStatus.STOPPED)
            )

            deployment.pod_name = svc_name
            deployment.service_name = svc_name
            deployment.endpoint_url = (
                f"http://{svc_name}.{namespace}.svc.cluster.local:8080/predict"
            )
            deployment.status = DeploymentStatus.DEPLOYING
            await db.commit()
            deployment_id = deployment.id

            import asyncio
            from app.core.deps import async_session

            async def _poll_ready(dep_id, svc, ns, api):
                try:
                    for _ in range(40):
                        await asyncio.sleep(3)
                        try:
                            st = api.read_namespaced_deployment_status(svc, ns)
                            if (
                                st.status.ready_replicas
                                and st.status.ready_replicas >= 1
                            ):
                                async with async_session() as bg_db:
                                    bg_dep = await bg_db.get(MLModelDeployment, dep_id)
                                    if bg_dep is not None:
                                        bg_dep.status = DeploymentStatus.RUNNING
                                        await bg_db.commit()
                                return
                        except Exception as _p:
                            logger.debug("deployment poll: %s", _p)
                            continue
                    # Timed out — mark failed so the UI stops showing
                    # 'deploying' forever.
                    async with async_session() as bg_db:
                        bg_dep = await bg_db.get(MLModelDeployment, dep_id)
                        if bg_dep and bg_dep.status == DeploymentStatus.DEPLOYING:
                            bg_dep.status = DeploymentStatus.FAILED
                            bg_dep.config = {
                                "error": "timed out waiting for ready_replicas>=1 after 120s"
                            }
                            await bg_db.commit()
                except Exception:
                    logger.exception("poll_ready background task crashed")

            asyncio.create_task(
                _poll_ready(deployment_id, svc_name, namespace, apps_v1)
            )

        except Exception as e:
            logger.exception("K8s deployment failed")
            deployment.status = DeploymentStatus.FAILED
            deployment.config = {"error": str(e)}
            await db.commit()
            return error(f"K8s deployment failed: {e}", 500)

    await db.refresh(deployment)
    return success(
        {
            "deployment_id": str(deployment.id),
            "deployment_type": deployment.deployment_type.value,
            "status": deployment.status.value,
            "endpoint_url": deployment.endpoint_url,
        }
    )


def _invocation_summary(output: Any) -> tuple[str | None, float | None]:
    if not isinstance(output, dict):
        return None, None
    cls = output.get("predicted_class")
    conf = None
    probs = output.get("probabilities")
    if isinstance(probs, list) and probs and isinstance(probs[0], list) and probs[0]:
        try:
            conf = float(max(probs[0]))
        except (TypeError, ValueError):
            conf = None
    return (str(cls)[:255] if cls is not None else None), conf


async def _record_invocation(
    db: AsyncSession,
    model: MLModel,
    *,
    input_data: Any,
    output: Any,
    duration_ms: int,
    error_message: str | None,
    source: str | None,
) -> None:
    # never let bookkeeping fail a prediction
    try:
        cls, conf = _invocation_summary(output)
        db.add(
            MLModelInvocation(
                tenant_id=model.tenant_id,
                ml_model_id=model.id,
                operation="predict",
                input_payload={"input_data": input_data},
                output=output if isinstance(output, dict) else None,
                predicted_class=cls,
                confidence=conf,
                duration_ms=duration_ms,
                is_error=error_message is not None,
                error_message=error_message[:4000] if error_message else None,
                deployment_type=source,
                caller_source="api",
            )
        )
        await db.commit()
    except Exception as e:
        logger.warning("ml invocation log failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass


@router.post("/{model_id}/predict")
async def predict(
    model_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run inference. Works right after upload, a deployment is optional."""
    start = time.monotonic()

    result = await db.execute(
        select(MLModel).where(
            MLModel.id == model_id,
            MLModel.tenant_id == user.tenant_id,
            MLModel.status != MLModelStatus.DELETED,
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        return error("Model not found", 404)
    if model.status != MLModelStatus.READY:
        return error(
            _status_message(model) or "This model is not ready.",
            409,
            error_code="MODEL_NOT_READY",
        )

    input_data = body.get("input_data")
    if input_data is None or input_data == [] or input_data == {}:
        names = _feature_names(model)
        hint = f" with {len(names)} values: {', '.join(names)}" if names else ""
        return error(
            'input_data is required, for example {"features": [...]}' + hint + ".",
            422,
            error_code="INVALID_INPUT",
        )

    dep_result = await db.execute(
        select(MLModelDeployment)
        .where(
            MLModelDeployment.model_id == model.id,
            MLModelDeployment.status == DeploymentStatus.RUNNING,
            MLModelDeployment.endpoint_url.is_not(None),
        )
        .order_by(MLModelDeployment.created_at.desc())
        .limit(1)
    )
    k8s_dep = dep_result.scalar_one_or_none()

    output: Any = None
    source = "local"

    if k8s_dep and k8s_dep.endpoint_url:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    k8s_dep.endpoint_url, json={"input_data": input_data}
                )
                resp.raise_for_status()
                resp_data = resp.json()
                if resp_data.get("predictions") is not None:
                    output = resp_data
                    source = "k8s"
        except Exception as e:
            logger.warning("K8s prediction failed, falling back to local: %s", e)

    if output is None:
        try:
            output = await _local_predict(
                model.file_uri, model.framework, input_data, _feature_names(model)
            )
            source = "local"
        except PredictInputError as e:
            await _record_invocation(
                db,
                model,
                input_data=input_data,
                output=None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error_message=str(e),
                source="local",
            )
            return error(str(e), 422, error_code="INVALID_INPUT")
        except Exception as e:
            logger.warning("local prediction failed: %s", e)
            msg = f"Prediction failed: {e}"
            await _record_invocation(
                db,
                model,
                input_data=input_data,
                output=None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error_message=msg,
                source="local",
            )
            return error(msg, 500, error_code="PREDICTION_FAILED")

    latency_ms = int((time.monotonic() - start) * 1000)
    await _record_invocation(
        db,
        model,
        input_data=input_data,
        output=output,
        duration_ms=latency_ms,
        error_message=None,
        source=source,
    )
    extra = (
        {k: v for k, v in output.items() if k != "predictions"}
        if isinstance(output, dict)
        else {}
    )
    return success(
        {
            "predictions": (
                output.get("predictions") if isinstance(output, dict) else output
            ),
            **extra,
            "model_name": model.name,
            "model_version": model.version,
            "framework": model.framework.value,
            "source": source,
            "latency_ms": latency_ms,
        }
    )


def _predict_sync(
    file_uri: str, framework: MLModelFramework, input_data: Any, names: list[str]
) -> dict:
    import numpy as np

    X = _to_matrix(input_data, names)
    sent = None if isinstance(X, list) else int(X.shape[1])

    if framework in (MLModelFramework.SKLEARN, MLModelFramework.XGBOOST):
        import joblib

        model = joblib.load(file_uri)
        expected = getattr(model, "n_features_in_", None)
        if sent is not None and expected is not None and int(expected) != sent:
            names = names or [str(f) for f in getattr(model, "feature_names_in_", [])]
            raise PredictInputError(_feature_count_message(int(expected), sent, names))
        try:
            preds = model.predict(X)
        except ValueError as e:
            raise PredictInputError(f"The model rejected this input: {e}")
        out: dict[str, Any] = {"predictions": preds.tolist()}
        if hasattr(model, "predict_proba"):
            try:
                out["probabilities"] = model.predict_proba(X).tolist()
            except Exception:
                pass
        if hasattr(model, "classes_"):
            out["classes"] = [str(c) for c in model.classes_]
            out["predicted_class"] = str(preds[0]) if len(preds) else None
        return out

    if framework == MLModelFramework.ONNX:
        import onnxruntime as ort

        sess = ort.InferenceSession(file_uri)
        first = sess.get_inputs()[0]
        shape = first.shape
        if (
            sent is not None
            and isinstance(shape, list)
            and len(shape) == 2
            and isinstance(shape[1], int)
            and shape[1] != sent
        ):
            raise PredictInputError(_feature_count_message(shape[1], sent, names))
        try:
            preds = sess.run(None, {first.name: np.asarray(X).astype(np.float32)})
        except Exception as e:
            raise PredictInputError(f"The model rejected this input: {e}")
        return {
            "predictions": [p.tolist() if hasattr(p, "tolist") else p for p in preds]
        }

    if framework == MLModelFramework.PYTORCH:
        import torch

        model = torch.load(file_uri, map_location="cpu", weights_only=False)
        model.eval()
        with torch.no_grad():
            try:
                output = model(torch.FloatTensor(np.asarray(X)))
            except RuntimeError as e:
                raise PredictInputError(f"The model rejected this input: {e}")
            return {"predictions": output.numpy().tolist()}

    raise ValueError(UNRUNNABLE.get(framework, f"Unsupported framework: {framework}"))


async def _local_predict(
    file_uri: str,
    framework: MLModelFramework,
    input_data: Any,
    names: list[str] | None = None,
) -> dict:
    """Load the model and run inference in a worker thread."""
    from app.core.artifact_store import ensure_local

    await ensure_local(Path(file_uri))
    return await asyncio.to_thread(
        _predict_sync, file_uri, framework, input_data, names or []
    )


@router.delete("/{model_id}/undeploy")
async def undeploy_model(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Tear down a model deployment."""
    result = await db.execute(
        select(MLModel).where(
            MLModel.id == model_id,
            MLModel.tenant_id == user.tenant_id,
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        return error("Model not found", 404)

    # Find active deployments
    deps_result = await db.execute(
        select(MLModelDeployment).where(
            MLModelDeployment.model_id == model.id,
            MLModelDeployment.status.in_(
                [DeploymentStatus.RUNNING, DeploymentStatus.DEPLOYING]
            ),
        )
    )
    deps = deps_result.scalars().all()

    deleted_k8s = []
    for dep in deps:
        if dep.deployment_type == DeploymentType.K8S and dep.service_name:
            try:
                from kubernetes import client, config

                try:
                    config.load_incluster_config()
                except Exception:
                    config.load_kube_config()

                apps_v1 = client.AppsV1Api()
                core_v1 = client.CoreV1Api()
                ns = dep.k8s_namespace

                try:
                    apps_v1.delete_namespaced_deployment(dep.service_name, ns)
                    deleted_k8s.append(f"deployment/{dep.service_name}")
                except Exception:
                    pass
                try:
                    core_v1.delete_namespaced_service(dep.service_name, ns)
                    deleted_k8s.append(f"service/{dep.service_name}")
                except Exception:
                    pass
            except ImportError:
                logger.warning("kubernetes package not installed, skipping k8s cleanup")

        dep.status = DeploymentStatus.STOPPED
    await db.commit()

    return success(
        {
            "undeployed": len(deps),
            "k8s_resources_deleted": deleted_k8s,
        }
    )


@router.get("/{model_id}/fetch")
async def fetch_model_for_runtime(
    model_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Model file for a runtime pod that does not share the API's volume.

    Authorised only by a short-lived token scoped to this one model.
    """
    from fastapi.responses import FileResponse

    from app.core.security import verify_token

    auth = request.headers.get("authorization", "")
    claims = (
        verify_token(auth.removeprefix("Bearer ")) if auth.startswith("Bearer ") else {}
    )
    if claims.get("type") != "ml_model_fetch" or claims.get("sub") != str(model_id):
        return error("Model not found", 404)
    model = (
        await db.execute(select(MLModel).where(MLModel.id == model_id))
    ).scalar_one_or_none()
    if model is None or str(model.tenant_id) != str(claims.get("tenant_id")):
        return error("Model not found", 404)
    from app.core.artifact_store import ensure_local

    file_path = Path(model.file_uri or "")
    if not await ensure_local(file_path):
        return error("Model file not found on disk", 404)
    return FileResponse(path=str(file_path), media_type="application/octet-stream")


@router.get("/{model_id}/download")
async def download_model_file(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Download the model file — used by model-serving pods to fetch the model."""
    from fastapi.responses import FileResponse

    result = await db.execute(
        select(MLModel).where(
            MLModel.id == model_id,
            MLModel.tenant_id == user.tenant_id,
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        return error("Model not found", 404)

    from app.core.artifact_store import ensure_local

    file_path = Path(model.file_uri)
    if not await ensure_local(file_path):
        return error("Model file not found on disk", 404)

    return FileResponse(
        path=str(file_path),
        filename=model.original_filename or f"{model.name}.pkl",
        media_type="application/octet-stream",
    )


@router.get("/versions/{model_name}")
async def list_versions(
    model_name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List all versions of a model by name."""
    result = await db.execute(
        select(MLModel)
        .where(
            MLModel.tenant_id == user.tenant_id,
            MLModel.name == model_name,
            MLModel.status != MLModelStatus.DELETED,
        )
        .order_by(MLModel.created_at.desc())
    )
    models = result.scalars().all()
    return success([_serialize(m) for m in models])


@router.post("/{model_id}/activate")
async def activate_version(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Set this version as the active one (deactivates others with same name)."""
    result = await db.execute(
        select(MLModel).where(
            MLModel.id == model_id,
            MLModel.tenant_id == user.tenant_id,
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        return error("Model not found", 404)
    if model.status != MLModelStatus.READY:
        return error(
            "Only a model that loaded cleanly can be made active. "
            + (_status_message(model) or ""),
            409,
            error_code="MODEL_NOT_READY",
        )

    # Deactivate all other versions with the same name
    from sqlalchemy import update as sql_update

    await db.execute(
        sql_update(MLModel)
        .where(
            MLModel.tenant_id == user.tenant_id,
            MLModel.name == model.name,
            MLModel.is_active.is_(True),
        )
        .values(is_active=False)
    )
    # Activate this one
    model.is_active = True
    await db.commit()
    await db.refresh(model)

    return success(await _serialize_with_deployments(model, db))


@router.post("/{model_id}/deactivate")
async def deactivate_version(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Deactivate this version (no version will be active for this model name)."""
    result = await db.execute(
        select(MLModel).where(
            MLModel.id == model_id,
            MLModel.tenant_id == user.tenant_id,
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        return error("Model not found", 404)
    model.is_active = False
    await db.commit()
    await db.refresh(model)
    return success(
        {"deactivated": True, **(await _serialize_with_deployments(model, db))}
    )


@router.get("/check/{model_name}")
async def check_model_ready(
    model_name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Check if a model is ready and deployed — used by pipeline validation.

    Returns: { ready: bool, deployed: bool, active_version: str|null, message: str }
    """
    # Find active version
    result = await db.execute(
        select(MLModel)
        .where(
            MLModel.tenant_id == user.tenant_id,
            MLModel.name == model_name,
            MLModel.is_active.is_(True),
            MLModel.status == MLModelStatus.READY,
        )
        .limit(1)
    )
    model = result.scalar_one_or_none()

    if not model:
        return success(
            {
                "ready": False,
                "deployed": False,
                "active_version": None,
                "message": f"No active, ready model named '{model_name}'. Upload one or set a version active on the ML Models page.",
            }
        )

    # Check deployment
    dep_result = await db.execute(
        select(MLModelDeployment)
        .where(
            MLModelDeployment.model_id == model.id,
            MLModelDeployment.status == DeploymentStatus.RUNNING,
        )
        .limit(1)
    )
    deployed = dep_result.scalar_one_or_none() is not None

    return success(
        {
            "ready": True,
            "deployed": deployed,
            "active_version": model.version,
            "model_id": str(model.id),
            "framework": model.framework.value,
            "message": (
                "Model is ready and deployed as its own service."
                if deployed
                else "Model is ready. Agents run it in-process, no deploy needed. "
                "Deploy it as its own service for production traffic."
            ),
        }
    )
