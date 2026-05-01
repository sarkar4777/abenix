"""ML Model Registry — upload, deploy, and serve ML models."""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
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


def _serialize(m: MLModel) -> dict:
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
        "is_active": m.is_active,
        "training_metrics": m.training_metrics,
        "tags": m.tags,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        # deployments are loaded separately to avoid async lazy-load issues
        "deployments": [],
    }


async def _serialize_with_deployments(m: MLModel, db: AsyncSession) -> dict:
    """Serialize with deployments (requires a DB session for the join)."""
    data = _serialize(m)
    result = await db.execute(
        select(MLModelDeployment).where(MLModelDeployment.model_id == m.id)
    )
    deps = result.scalars().all()
    data["deployments"] = [
        {
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
        for d in deps
    ]
    return data


def _detect_framework(filename: str, explicit: str | None = None) -> MLModelFramework:
    if explicit:
        try:
            return MLModelFramework(explicit)
        except ValueError:
            pass
    ext = Path(filename).suffix.lower()
    return ALLOWED_EXTENSIONS.get(ext, MLModelFramework.CUSTOM)


async def _validate_model(file_path: str, framework: MLModelFramework) -> dict | None:
    """Try to load the model and return basic metadata. Returns None on failure."""
    try:
        if framework in (MLModelFramework.SKLEARN, MLModelFramework.XGBOOST):
            import joblib

            model = joblib.load(file_path)
            info = {"type": type(model).__name__}
            if hasattr(model, "n_features_in_"):
                info["n_features"] = int(model.n_features_in_)
            if hasattr(model, "feature_names_in_"):
                info["feature_names"] = list(model.feature_names_in_)
            if hasattr(model, "classes_"):
                info["classes"] = [str(c) for c in model.classes_]
            return info
        elif framework == MLModelFramework.ONNX:
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
            return {"inputs": inputs, "outputs": outputs}
        elif framework == MLModelFramework.PYTORCH:
            import torch

            model = torch.load(file_path, map_location="cpu", weights_only=False)
            return {"type": type(model).__name__}
        else:
            return {"type": "unknown"}
    except Exception as e:
        logger.warning("Model validation failed: %s", e)
        return None


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


@router.post("")
async def upload_model(
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Upload a trained model file with metadata."""
    if not file.filename:
        return error("No file provided", 400)

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS and ext not in (".bin",):
        return error(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS.keys())}",
            400,
        )

    # Parse metadata
    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError:
        return error("Invalid metadata JSON", 400)

    name = meta.get("name") or Path(file.filename).stem
    version = meta.get("version", "1.0.0")
    framework = _detect_framework(file.filename, meta.get("framework"))
    description = meta.get("description", "")
    input_schema = meta.get("input_schema")
    output_schema = meta.get("output_schema")
    tags = meta.get("tags", [])

    # Read and store file
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        return error(f"File too large. Max: {MAX_FILE_SIZE // (1024*1024)}MB", 400)

    # Create storage directory
    model_dir = UPLOAD_DIR / str(user.tenant_id)
    model_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex[:12]
    file_path = model_dir / f"{file_id}_{file.filename}"
    file_path.write_bytes(content)

    # Deactivate previous versions of the same model name for this tenant
    # (only the latest upload is active by default)
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

    # Create DB record
    model = MLModel(
        tenant_id=user.tenant_id,
        name=name,
        version=version,
        framework=framework,
        description=description,
        file_uri=str(file_path),
        file_size_bytes=len(content),
        original_filename=file.filename,
        input_schema=input_schema,
        output_schema=output_schema,
        status=MLModelStatus.VALIDATING,
        is_active=True,
        tags=tags,
        created_by=user.id,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)

    # Validate the model (try loading it)
    validation = await _validate_model(str(file_path), framework)
    if validation:
        model.status = MLModelStatus.READY
        if not model.training_metrics:
            model.training_metrics = validation
        # Fill in input/output schemas from introspection if the
        # uploader didn't supply them. Without this, pipelines that
        # embed ml_model have an empty arguments form and the LLM
        # has no tool-schema hint, leading to hallucinated payloads.
        if not model.input_schema or not model.output_schema:
            inferred_in, inferred_out = _infer_ml_schemas(validation, framework)
            if not model.input_schema and inferred_in:
                model.input_schema = inferred_in
            if not model.output_schema and inferred_out:
                model.output_schema = inferred_out
    else:
        model.status = MLModelStatus.ERROR
    await db.commit()
    await db.refresh(model)

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
    models = result.scalars().all()
    return success([_serialize(m) for m in models])


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

    # Clean up file
    try:
        Path(model.file_uri).unlink(missing_ok=True)
    except Exception:
        pass

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
    """Deploy a model locally (in-process) or as a k8s pod."""
    result = await db.execute(
        select(MLModel).where(
            MLModel.id == model_id,
            MLModel.tenant_id == user.tenant_id,
            MLModel.status == MLModelStatus.READY,
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        return error("Model not found or not ready", 404)

    dep_type = body.get("deployment_type", "local")
    replicas = int(body.get("replicas", 1))

    try:
        dtype = DeploymentType(dep_type)
    except ValueError:
        return error("Invalid deployment_type. Use 'local' or 'k8s'.", 400)

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
                    requests={"cpu": "250m", "memory": "512Mi"},
                    limits={"cpu": "1", "memory": "2Gi"},
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
                        [DeploymentStatus.FAILED, DeploymentStatus.DEPLOYING]
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


@router.post("/{model_id}/predict")
async def predict(
    model_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run inference on a deployed model."""
    import time

    start = time.monotonic()

    result = await db.execute(
        select(MLModel).where(
            MLModel.id == model_id,
            MLModel.tenant_id == user.tenant_id,
            MLModel.status == MLModelStatus.READY,
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        return error("Model not found or not ready", 404)

    input_data = body.get("input_data")
    if not input_data:
        return error("input_data is required", 400)

    # Check for k8s deployment with endpoint
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

    predictions = None
    source = "local"

    if k8s_dep and k8s_dep.endpoint_url:
        # Route to k8s endpoint
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    k8s_dep.endpoint_url, json={"input_data": input_data}
                )
                resp.raise_for_status()
                resp_data = resp.json()
                predictions = resp_data.get("predictions")
                source = "k8s"
        except Exception as e:
            logger.warning("K8s prediction failed, falling back to local: %s", e)

    if predictions is None:
        # Local inference
        try:
            predictions = await _local_predict(
                model.file_uri, model.framework, input_data
            )
            source = "local"
        except Exception as e:
            return error(f"Prediction failed: {e}", 500)

    latency_ms = int((time.monotonic() - start) * 1000)
    return success(
        {
            "predictions": predictions,
            "model_name": model.name,
            "model_version": model.version,
            "framework": model.framework.value,
            "source": source,
            "latency_ms": latency_ms,
        }
    )


async def _local_predict(
    file_uri: str, framework: MLModelFramework, input_data: Any
) -> Any:
    """Load model and run inference locally."""
    import numpy as np

    # Parse input
    if isinstance(input_data, dict):
        features = input_data.get("features") or list(input_data.values())
    elif isinstance(input_data, list):
        features = input_data
    else:
        raise ValueError(f"input_data must be a dict or list, got {type(input_data)}")

    X = (
        np.array([features])
        if not isinstance(features[0], list)
        else np.array(features)
    )

    if framework in (MLModelFramework.SKLEARN, MLModelFramework.XGBOOST):
        import joblib

        model = joblib.load(file_uri)
        preds = model.predict(X)
        # If classifier, also get probabilities
        result: dict[str, Any] = {"predictions": preds.tolist()}
        if hasattr(model, "predict_proba"):
            probs = model.predict_proba(X)
            result["probabilities"] = probs.tolist()
        if hasattr(model, "classes_"):
            result["classes"] = [str(c) for c in model.classes_]
            result["predicted_class"] = str(preds[0])
        return result

    elif framework == MLModelFramework.ONNX:
        import onnxruntime as ort

        sess = ort.InferenceSession(file_uri)
        input_name = sess.get_inputs()[0].name
        preds = sess.run(None, {input_name: X.astype(np.float32)})
        return {
            "predictions": [p.tolist() if hasattr(p, "tolist") else p for p in preds]
        }

    elif framework == MLModelFramework.PYTORCH:
        import torch

        model = torch.load(file_uri, map_location="cpu", weights_only=False)
        model.eval()
        with torch.no_grad():
            tensor = torch.FloatTensor(X)
            output = model(tensor)
            return {"predictions": output.numpy().tolist()}

    else:
        raise ValueError(f"Unsupported framework: {framework}")


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

    file_path = Path(model.file_uri)
    if not file_path.exists():
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

    return success(_serialize(model))


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
    return success({"deactivated": True})


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
                "message": f"No active model named '{model_name}' found. Upload one via /ml-models.",
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
            "message": "Model is ready"
            + (" and deployed" if deployed else " but NOT deployed. Deploy it first."),
        }
    )
