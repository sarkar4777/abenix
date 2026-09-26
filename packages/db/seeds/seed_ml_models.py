"""Seed the sample ML models shipped in aimodels/ as MLModel rows."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from models.ml_model import (
    MLModel,
    MLModelDeployment,
    MLModelFramework,
    MLModelStatus,
    DeploymentType,
    DeploymentStatus,
)
from models.tenant import Tenant

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix",
)
# Must match apps/api/app/routers/ml_models.py UPLOAD_DIR default.
UPLOAD_DIR = Path(os.environ.get("ML_MODELS_DIR", "/tmp/ml-models"))

REPO_ROOT = Path(__file__).resolve().parents[3]
# Tenant-wide samples live at the root; use-case-specific models live
# under <use-case>/aimodels/ so the catalogue lines up with the vertical.
AIMODELS_DIRS = [
    REPO_ROOT / "aimodels",
    REPO_ROOT / "industrial-iot" / "aimodels",
    REPO_ROOT / "wingman" / "aimodels",
    REPO_ROOT / "wingman" / "ml-models",
    REPO_ROOT / "contractiq" / "aimodels",
    REPO_ROOT / "mideasttourism" / "aimodels",
    REPO_ROOT / "resolveai" / "aimodels",
    REPO_ROOT / "pharmavigil" / "aimodels",
    REPO_ROOT / "claimsiq" / "aimodels",
]
# Kept for backwards compat with anything that imported it.
AIMODELS_DIR = AIMODELS_DIRS[0]


def _framework_from_ext(ext: str) -> MLModelFramework:
    return {
        ".pkl": MLModelFramework.SKLEARN,
        ".joblib": MLModelFramework.SKLEARN,
        ".pt": MLModelFramework.PYTORCH,
        ".pth": MLModelFramework.PYTORCH,
        ".onnx": MLModelFramework.ONNX,
        ".h5": MLModelFramework.TENSORFLOW,
        ".keras": MLModelFramework.TENSORFLOW,
        ".xgb": MLModelFramework.XGBOOST,
    }.get(ext.lower(), MLModelFramework.CUSTOM)


def _discover_samples() -> list[tuple[Path, dict]]:
    """Return (pkl_path, meta) pairs for every sample with a matching .meta.json."""
    out: list[tuple[Path, dict]] = []
    for root in AIMODELS_DIRS:
        if not root.is_dir():
            continue
        for meta_path in sorted(root.glob("*.meta.json")):
            stem = meta_path.name.removesuffix(".meta.json")
            # Accept .pkl / .joblib / .pt / .onnx etc — pick the first one that exists.
            for ext in (
                ".pkl",
                ".joblib",
                ".pt",
                ".pth",
                ".onnx",
                ".h5",
                ".keras",
                ".xgb",
            ):
                candidate = root / f"{stem}{ext}"
                if candidate.exists():
                    try:
                        meta = json.loads(meta_path.read_text())
                    except Exception as e:  # pragma: no cover — malformed meta
                        print(f"  ! Skipping {meta_path.name} — invalid JSON: {e}")
                        break
                    out.append((candidate, meta))
                    break
    return out


async def _ensure_for_tenant(
    db: AsyncSession, tenant: Tenant, samples: list[tuple[Path, dict]]
) -> int:
    """Create MLModel + LOCAL deployment rows for any sample not yet present."""
    created = 0
    tenant_upload_dir = UPLOAD_DIR / str(tenant.id)
    tenant_upload_dir.mkdir(parents=True, exist_ok=True)

    for pkl_path, meta in samples:
        model_name = meta.get("name") or pkl_path.stem
        version = meta.get("version", "1.0.0")

        existing_q = await db.execute(
            select(MLModel).where(
                MLModel.tenant_id == tenant.id,
                MLModel.name == model_name,
                MLModel.version == version,
                MLModel.status != MLModelStatus.DELETED,
            )
        )
        if existing_q.scalar_one_or_none() is not None:
            continue

        file_id = uuid.uuid4().hex[:12]
        dest = tenant_upload_dir / f"{file_id}_{pkl_path.name}"
        # shutil.copyfile (bytes only, no chmod, no utime) — Azure
        # Files's SMB mount rejects BOTH `chmod` and `utime` with
        # `Operation not permitted`. copy2 calls both via copystat,
        # copy calls chmod via copymode. Only copyfile skips both.
        # Default share permissions are fine for the runtime to read.
        shutil.copyfile(pkl_path, dest)

        # deactivate prior versions of the same name before inserting
        await db.execute(
            update(MLModel)
            .where(
                MLModel.tenant_id == tenant.id,
                MLModel.name == model_name,
                MLModel.is_active.is_(True),
            )
            .values(is_active=False)
        )

        m = MLModel(
            tenant_id=tenant.id,
            name=model_name,
            version=version,
            framework=_framework_from_ext(pkl_path.suffix),
            description=meta.get("description", ""),
            file_uri=str(dest),
            file_size_bytes=dest.stat().st_size,
            original_filename=pkl_path.name,
            input_schema=meta.get("input_schema"),
            output_schema=meta.get("output_schema"),
            status=MLModelStatus.READY,
            is_active=True,
            training_metrics=meta.get("training_metrics"),
            tags=meta.get("tags", []) + ["oob", "sample"],
        )
        db.add(m)
        await db.flush()

        deployment = MLModelDeployment(
            model_id=m.id,
            deployment_type=DeploymentType.LOCAL,
            endpoint_url=None,
            replicas=1,
            status=DeploymentStatus.RUNNING,
        )
        db.add(deployment)
        created += 1
        print(f"  + Seeded {model_name} v{version} for tenant {tenant.slug}")

    await db.commit()
    return created


async def seed_ml_models() -> None:
    samples = _discover_samples()
    if not samples:
        print(
            "No sample ML models found in aimodels/ — run aimodels/build_samples.py first."
        )
        return
    print(f"Found {len(samples)} sample models in aimodels/")

    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as db:
        tenants = (await db.execute(select(Tenant))).scalars().all()
        if not tenants:
            print("No tenants in DB — run seed_users.py first.")
            return

        total = 0
        for t in tenants:
            total += await _ensure_for_tenant(db, t, samples)
        print(f"Seeded {total} new MLModel row(s) across {len(tenants)} tenant(s).")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_ml_models())
