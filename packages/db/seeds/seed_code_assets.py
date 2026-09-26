"""Seed code assets shipped under <use-case>/code-assets/<asset>/agentforge.yaml.

Every directory containing both an `agentforge.yaml` and at least one source
file (`main.go`, `main.py`, `main.rs`, …) is treated as a code asset. The
manifest carries `name`, `description`, `input_schema`, `output_schema`,
and an optional `example_input`. We zip the folder, write a CodeAsset row
in READY status, and copy the analyzer signal (language / entrypoint /
suggested run command) so the Builder can wire the asset into agents
without a UI round-trip.

Idempotent: if a (tenant, name, version) row already exists we skip.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
import zipfile
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.code_asset import CodeAsset, CodeAssetSource, CodeAssetStatus
from models.tenant import Tenant

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix",
)
# Must match apps/api/app/routers/code_assets.py CODE_STORE_DIR default.
CODE_STORE_DIR = Path(os.environ.get("CODE_ASSET_STORE", "/data/code-assets"))

REPO_ROOT = Path(__file__).resolve().parents[3]

# Roots we walk to discover use-case-scoped code assets. Each path is
# scanned recursively for `agentforge.yaml`. Standalone-app folders own
# their own assets so the catalogue lines up with the use case.
DISCOVERY_ROOTS = [
    REPO_ROOT / "industrial-iot",
    REPO_ROOT / "wingman",
    REPO_ROOT / "contractiq",
    REPO_ROOT / "mideasttourism",
    REPO_ROOT / "pharmavigil",
    REPO_ROOT / "resolveai",
    REPO_ROOT / "claimsiq",
    # Generic shared examples (kept for tenants that haven't enabled a
    # specific vertical yet).
    REPO_ROOT / "examples" / "code-assets",
]

# Heuristics for entrypoint + language detection. Mirrors the smaller
# subset of code_analyzer.py that the API uses on upload — kept local so
# the seed doesn't need a full analyzer import.
_LANG_BY_FILE = {
    "main.go": ("go", "main.go"),
    "main.py": ("python", "main.py"),
    "predict.py": ("python", "predict.py"),
    "main.rs": ("rust", "main.rs"),
    "index.js": ("javascript", "index.js"),
    "main.js": ("javascript", "main.js"),
    "Main.java": ("java", "Main.java"),
}

_RUN_BY_LANG = {
    "go": "go run .",
    "python": "python {entrypoint}",
    "rust": "cargo run --release",
    "javascript": "node {entrypoint}",
    "java": "java {entrypoint}",
}


def _detect_entry(folder: Path) -> tuple[str | None, str | None]:
    for fname, (lang, _) in _LANG_BY_FILE.items():
        if (folder / fname).exists():
            return lang, fname
        # Also probe `cmd/<fname>` for Go-style layouts.
        if (folder / "cmd" / fname).exists():
            return lang, f"cmd/{fname}"
    return None, None


def _zip_folder(folder: Path, out_path: Path) -> int:
    """Zip `folder` into `out_path`. Returns size in bytes."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            # Skip vendored / build outputs that bloat the archive
            rel = path.relative_to(folder)
            parts = set(rel.parts)
            if parts & {
                ".git",
                "node_modules",
                "target",
                "dist",
                "build",
                "__pycache__",
                ".venv",
            }:
                continue
            if rel.name.endswith((".pyc", ".pyo")):
                continue
            zf.write(path, str(rel))
    return out_path.stat().st_size


def _discover_assets() -> list[tuple[Path, dict]]:
    """Return (asset_dir, manifest_dict) for every agentforge.yaml found."""
    out: list[tuple[Path, dict]] = []
    for root in DISCOVERY_ROOTS:
        if not root.is_dir():
            continue
        for manifest in root.rglob("agentforge.yaml"):
            # Skip nested examples/ that ship inside an asset itself
            try:
                manifest_dict = yaml.safe_load(manifest.read_text()) or {}
            except Exception as e:
                print(f"  ! Skipping {manifest} — invalid yaml: {e}")
                continue
            if not manifest_dict.get("name"):
                print(f"  ! Skipping {manifest} — no `name` field")
                continue
            out.append((manifest.parent, manifest_dict))
    return out


async def _ensure_for_tenant(
    db: AsyncSession,
    tenant: Tenant,
    assets: list[tuple[Path, dict]],
) -> int:
    created = 0
    tenant_dir = CODE_STORE_DIR / str(tenant.id)
    tenant_dir.mkdir(parents=True, exist_ok=True)

    for folder, manifest in assets:
        name = manifest["name"]
        existing_q = await db.execute(
            select(CodeAsset).where(
                CodeAsset.tenant_id == tenant.id,
                CodeAsset.name == name,
                CodeAsset.status != CodeAssetStatus.DELETED,
            )
        )
        if existing_q.scalar_one_or_none() is not None:
            continue

        asset_id = uuid.uuid4().hex[:16]
        zip_path = tenant_dir / f"{asset_id}_{folder.name}.zip"
        size = _zip_folder(folder, zip_path)

        lang, entry = _detect_entry(folder)
        run_template = _RUN_BY_LANG.get(lang or "", "")
        suggested_run = (
            run_template.format(entrypoint=entry) if entry and run_template else None
        )
        suggested_image = {
            "go": "golang:1.22-alpine",
            "python": "python:3.12-slim",
            "rust": "rust:1.78-slim",
            "javascript": "node:20-alpine",
            "java": "eclipse-temurin:21-jdk",
        }.get(lang or "")

        # Inline the example_input on the input_schema so the Builder
        # can pre-fill, matching the upload-path behaviour.
        input_schema = manifest.get("input_schema")
        example_input = manifest.get("example_input")
        if isinstance(input_schema, dict) and example_input is not None:
            input_schema = {**input_schema, "x-example": example_input}

        asset = CodeAsset(
            tenant_id=tenant.id,
            name=name,
            description=manifest.get("description"),
            source_type=CodeAssetSource.ZIP,
            storage_uri=str(zip_path),
            file_size_bytes=size,
            detected_language=lang,
            detected_entrypoint=entry,
            suggested_image=suggested_image,
            suggested_run_command=suggested_run,
            analysis_notes=[
                {
                    "level": "info",
                    "message": f"Seeded from {folder.relative_to(REPO_ROOT)}",
                }
            ],
            input_schema=input_schema,
            output_schema=manifest.get("output_schema"),
            status=CodeAssetStatus.READY,
        )
        db.add(asset)
        created += 1
        print(f"  + Seeded {name} ({lang or '?'}) for tenant {tenant.slug}")

    await db.commit()
    return created


async def seed_code_assets() -> None:
    assets = _discover_assets()
    if not assets:
        print("No code assets discovered.")
        return
    print(f"Discovered {len(assets)} code asset(s):")
    for folder, manifest in assets:
        print(f"  - {manifest['name']:30s}  {folder.relative_to(REPO_ROOT)}")

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
            total += await _ensure_for_tenant(db, t, assets)
        print(f"Seeded {total} new CodeAsset row(s) across {len(tenants)} tenant(s).")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_code_assets())
