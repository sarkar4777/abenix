"""Code Assets API — upload a zip / clone a git repo, analyze it,"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from models.code_asset import CodeAsset, CodeAssetSource, CodeAssetStatus
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/code-assets", tags=["code-assets"])


_CODE_STORE_DIR = Path(os.environ.get("CODE_ASSET_STORE", "/data/code-assets"))
_CODE_STORE_DIR.mkdir(parents=True, exist_ok=True)


def _serialize(a: CodeAsset) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "name": a.name,
        "description": a.description,
        "source_type": (
            a.source_type.value
            if hasattr(a.source_type, "value")
            else str(a.source_type)
        ),
        "source_git_url": a.source_git_url,
        "source_ref": a.source_ref,
        "storage_uri": a.storage_uri,
        "file_size_bytes": a.file_size_bytes,
        "detected_language": a.detected_language,
        "detected_version": a.detected_version,
        "detected_package_manager": a.detected_package_manager,
        "detected_entrypoint": a.detected_entrypoint,
        "suggested_image": a.suggested_image,
        "suggested_build_command": a.suggested_build_command,
        "suggested_run_command": a.suggested_run_command,
        "analysis_notes": a.analysis_notes or [],
        "input_schema": a.input_schema,
        "output_schema": a.output_schema,
        "status": a.status.value if hasattr(a.status, "value") else str(a.status),
        "error": a.error,
        "last_test_input": a.last_test_input,
        "last_test_output": a.last_test_output,
        "last_test_ok": a.last_test_ok,
        "last_test_at": a.last_test_at.isoformat() if a.last_test_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


def _looks_like_tgz(path: Path) -> bool:
    """Sniff the first 2 bytes — gzip magic = 1f 8b. Works for .tar.gz,
    .tgz, and any user-renamed variant."""
    try:
        with open(path, "rb") as f:
            return f.read(2) == b"\x1f\x8b"
    except Exception:
        return False


def _tgz_to_zip(tgz_path: Path) -> Path:
    """Repack a tar.gz as a zip so the rest of the pipeline is format-"""
    import tarfile as _tf

    zip_path = tgz_path.with_suffix(".zip")
    with _tf.open(tgz_path, "r:gz") as tar, zipfile.ZipFile(
        zip_path,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as zf:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            src = tar.extractfile(member)
            if src is None:
                continue
            zf.writestr(member.name, src.read())
    # Replace the original so storage_uri points at the zip.
    tgz_path.unlink(missing_ok=True)
    return zip_path


async def _extract_and_analyze(
    zip_path: Path,
    asset_id: str,
) -> tuple[dict[str, Any], int]:
    """Extract the archive to a tmp dir, analyze, return (analysis_dict, size)."""
    import sys

    runtime_path = Path("/app/apps/agent-runtime")
    if runtime_path.exists() and str(runtime_path) not in sys.path:
        sys.path.insert(0, str(runtime_path))
    from engine.code_analyzer import analyze_directory  # noqa: E402

    size = zip_path.stat().st_size if zip_path.exists() else 0
    tmp = Path(tempfile.mkdtemp(prefix=f"code-asset-{asset_id[:8]}-"))
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            members = z.namelist()
            # Detect whether `first` is genuinely a directory root: every
            # member must start with "first/" AND at least one must be a
            # strict prefix match (i.e., a member exists INSIDE the dir).
            has_real_subtree = False
            first = ""
            if members:
                first = members[0].split("/")[0]
                has_real_subtree = any(
                    m.startswith(first + "/") and len(m) > len(first) + 1
                    for m in members
                )
            if has_real_subtree:
                for m in members:
                    if m == first or m == first + "/":
                        continue
                    rel = m[len(first) + 1 :]
                    if not rel:
                        continue
                    dest = tmp / rel
                    if m.endswith("/"):
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(m) as src, open(dest, "wb") as out:
                            shutil.copyfileobj(src, out)
            else:
                # Either flat zip (files at top level) OR single-file
                # archive — both extract safely to tmp with no stripping.
                z.extractall(tmp)
        analysis = analyze_directory(tmp)
        return analysis.to_dict(), size
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _validate_git_url(url: str) -> tuple[bool, str]:
    """Reject SSRF-shaped git URLs.

    Same threat model as MCP server URL validation: an attacker could
    point at `http://abenix-api.abenix.svc.cluster.local/` or
    `http://169.254.169.254/` (cloud metadata) and have the API pod's
    `git clone` proxy requests to internal infrastructure.

    Rules:
      * scheme must be https or git (not http, not ssh unless an
        explicit private key flow is added later, not file://).
      * host cannot be a private, loopback, link-local, or multicast IP.
      * cluster-internal DNS (*.cluster.local) is blocked.
      * if `CODE_ASSET_GIT_ALLOWED_HOSTS` is set (csv of host suffixes),
        the host must match at least one — operators can lock this down
        in production to `github.com,gitlab.com,bitbucket.org`.
    """
    import ipaddress as _ip
    from urllib.parse import urlparse as _urlparse

    try:
        u = _urlparse(url)
    except Exception:
        return False, "invalid url"
    if u.scheme not in ("https", "git"):
        return False, f"scheme must be https or git; got '{u.scheme}'"
    host = (u.hostname or "").strip()
    if not host:
        return False, "host is required"
    lowered = host.lower()
    try:
        ip = _ip.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            return False, f"private/loopback IPs not allowed ({host})"
    except ValueError:
        pass  # hostname, not IP
    if lowered in ("localhost", "host.docker.internal", "host.minikube.internal"):
        return False, f"internal hostname blocked ({host})"
    if lowered.endswith(".svc.cluster.local") or lowered.endswith(".cluster.local"):
        return False, "cluster-internal DNS blocked"
    allow = (os.environ.get("CODE_ASSET_GIT_ALLOWED_HOSTS") or "").strip()
    if allow:
        suffixes = [s.strip().lower() for s in allow.split(",") if s.strip()]
        if not any(lowered == s or lowered.endswith("." + s) for s in suffixes):
            return False, f"host '{host}' not in CODE_ASSET_GIT_ALLOWED_HOSTS"
    return True, ""


async def _clone_git(url: str, ref: str | None) -> Path:
    """Shallow-clone `url` at `ref` into a zip and return the local path."""
    asset_id = uuid.uuid4().hex[:16]
    tmp = Path(tempfile.mkdtemp(prefix=f"git-{asset_id}-"))
    try:
        argv = ["git", "clone", "--depth", "1"]
        if ref:
            argv += ["--branch", ref]
        argv += [url, str(tmp / "repo")]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"git clone timed out after 60s: {url}")
        if proc.returncode != 0:
            err = (await proc.stderr.read()).decode(errors="replace")[:500]
            raise RuntimeError(f"git clone failed: {err}")
        # Zip the cloned tree
        zip_path = _CODE_STORE_DIR / f"{asset_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in (tmp / "repo").rglob("*"):
                if p.is_file() and ".git" not in p.parts:
                    zf.write(p, arcname=str(p.relative_to(tmp / "repo")))
        return zip_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@router.post("")
async def create_asset(
    file: UploadFile | None = File(None),
    metadata: str = Form("{}"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create from uploaded zip OR from git URL (metadata.git_url)."""
    try:
        meta = json.loads(metadata)
    except Exception:
        meta = {}

    name = (meta.get("name") or "").strip()
    description = (meta.get("description") or "").strip() or None
    git_url = (meta.get("git_url") or "").strip()
    git_ref = (meta.get("git_ref") or "").strip() or None

    if not name:
        return error("name is required", 400)

    # Determine source
    zip_path: Path | None = None
    if file is not None and file.filename:
        # Archive upload — zip OR tar.gz. We detect by content (gzip
        # magic) rather than filename so a user who renames their
        # archive still gets the right extraction path.
        asset_id = uuid.uuid4().hex[:16]
        raw_path = _CODE_STORE_DIR / f"{asset_id}.bin"
        with open(raw_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        if _looks_like_tgz(raw_path):
            tgz_path = raw_path.with_suffix(".tgz")
            raw_path.rename(tgz_path)
            zip_path = _tgz_to_zip(tgz_path)
        else:
            zip_path = raw_path.with_suffix(".zip")
            raw_path.rename(zip_path)
        source_type = CodeAssetSource.ZIP
    elif git_url:
        ok, reason = _validate_git_url(git_url)
        if not ok:
            return error(f"git_url rejected: {reason}", 400)
        try:
            zip_path = await _clone_git(git_url, git_ref)
        except Exception as e:
            return error(f"git clone failed: {e}", 400)
        source_type = CodeAssetSource.GIT
    else:
        return error("provide either a zip file or a git_url", 400)

    # Create DB row before analysis so the UI can show "analyzing" state
    asset = CodeAsset(
        tenant_id=user.tenant_id,
        name=name,
        description=description,
        source_type=source_type,
        source_git_url=git_url or None,
        source_ref=git_ref,
        storage_uri=str(zip_path),
        file_size_bytes=zip_path.stat().st_size,
        status=CodeAssetStatus.ANALYZING,
        created_by=user.id,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    # Analyze — inline because analysis on typical repos takes <500ms.
    # For large repos (>20MB) we'd move this to a Celery task.
    try:
        analysis, size = await _extract_and_analyze(zip_path, str(asset.id))
        asset.detected_language = analysis.get("language") or None
        asset.detected_version = analysis.get("version") or None
        asset.detected_package_manager = analysis.get("package_manager") or None
        asset.detected_entrypoint = analysis.get("entrypoint") or None
        asset.suggested_image = analysis.get("suggested_image") or None
        asset.suggested_build_command = analysis.get("suggested_build_command") or None
        asset.suggested_run_command = analysis.get("suggested_run_command") or None
        asset.analysis_notes = analysis.get("notes") or []
        # Schema discovery — if the author provided abenix.yaml,
        # examples/*.json, or README fenced blocks, land the inferred
        # input/output schemas so the Builder can pre-fill pipeline
        # nodes and the LLM can see the tool shape accurately.
        if analysis.get("input_schema") and not asset.input_schema:
            asset.input_schema = analysis["input_schema"]
        if analysis.get("output_schema") and not asset.output_schema:
            asset.output_schema = analysis["output_schema"]
        example_input = analysis.get("example_input")
        if example_input and isinstance(asset.input_schema, dict):
            asset.input_schema = {**asset.input_schema, "x-example": example_input}
        # Is the analysis usable?
        has_error_note = any(
            (n.get("level") == "error") for n in (analysis.get("notes") or [])
        )
        if has_error_note or not asset.suggested_run_command:
            asset.status = CodeAssetStatus.FAILED
            asset.error = "Analysis completed with errors — see analysis_notes."
        else:
            asset.status = CodeAssetStatus.READY
    except Exception as e:
        logger.exception("code-asset analysis failed")
        asset.status = CodeAssetStatus.FAILED
        asset.error = str(e)[:1000]

    await db.commit()
    await db.refresh(asset)

    example_input_for_probe = None
    if asset.status == CodeAssetStatus.READY and not asset.output_schema:
        example_input_for_probe = (asset.input_schema or {}).get("x-example")
    if example_input_for_probe:
        import asyncio as _asyncio

        role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
        _asyncio.create_task(
            _smoke_test_probe_bg(
                str(asset.id),
                str(user.tenant_id),
                str(user.id),
                role_val,
                example_input_for_probe,
            )
        )

    return success(_serialize(asset), status_code=201)


@router.get("")
async def list_assets(
    scope: str = "all",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List code assets visible to the caller."""
    from app.core.permissions import (
        accessible_resource_ids,
        apply_resource_scope,
        is_admin,
    )

    if scope == "tenant" and not is_admin(user):
        return error("scope=tenant requires admin role", 403)

    accessible = await accessible_resource_ids(db, user, kind="code_asset")
    q = select(CodeAsset).where(CodeAsset.status != CodeAssetStatus.DELETED)
    q = apply_resource_scope(
        q,
        CodeAsset,
        user,
        kind="code_asset",
        scope=scope,
        accessible_ids=accessible,
    )
    q = q.order_by(CodeAsset.created_at.desc())
    result = await db.execute(q)
    return success([_serialize(a) for a in result.scalars().all()])


@router.get("/{asset_id}")
async def get_asset(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(CodeAsset).where(
            CodeAsset.id == asset_id,
            CodeAsset.tenant_id == user.tenant_id,
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        return error("not found", 404)
    # Per-user authorization — owner OR admin OR shared with this user.
    from app.core.permissions import (
        accessible_resource_ids,
        assert_can_access,
    )

    accessible = await accessible_resource_ids(db, user, kind="code_asset")
    if not assert_can_access(a, user, accessible_ids=accessible):
        return error("not found", 404)
    return success(_serialize(a))


@router.put("/{asset_id}")
async def update_asset(
    asset_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(CodeAsset).where(
            CodeAsset.id == asset_id,
            CodeAsset.tenant_id == user.tenant_id,
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        return error("not found", 404)
    for field in (
        "name",
        "description",
        "suggested_image",
        "suggested_build_command",
        "suggested_run_command",
        "detected_entrypoint",
    ):
        if field in body:
            setattr(a, field, body[field])
    for field in ("input_schema", "output_schema"):
        if field in body:
            setattr(a, field, body[field])
    await db.commit()
    await db.refresh(a)
    return success(_serialize(a))


async def _run_asset_sample(
    asset_id: str,
    tenant_id: str,
    user_id: str,
    role: str,
    sample_input: dict,
    timeout_seconds: int = 120,
) -> tuple[bool, dict | str]:
    """Run a code asset with a sample input and return (ok, payload)."""
    import sys

    runtime_path = Path("/app/apps/agent-runtime")
    if runtime_path.exists() and str(runtime_path) not in sys.path:
        sys.path.insert(0, str(runtime_path))
    from engine.tools.code_asset import CodeAssetTool  # noqa: E402

    from app.core.security import create_access_token

    fetch_token = create_access_token(uuid.UUID(user_id), uuid.UUID(tenant_id), role)
    os.environ["CODE_ASSET_DOWNLOAD_TOKEN"] = f"Bearer {fetch_token}"

    tool = CodeAssetTool(
        tenant_id=tenant_id,
        redis_url=os.environ.get("REDIS_URL", ""),
        db_url=os.environ.get("DATABASE_URL", ""),
    )
    res = await tool.execute(
        {
            "code_asset_id": asset_id,
            "input": sample_input or {},
            "timeout_seconds": timeout_seconds,
            "memory_mb": 1024,
            "allow_network": True,
        }
    )
    if res.is_error:
        return False, res.content
    try:
        return True, json.loads(res.content)
    except Exception:
        return True, {"raw": res.content}


async def _smoke_test_probe_bg(
    asset_id: str,
    tenant_id: str,
    user_id: str,
    role: str,
    example_input: dict,
) -> None:
    """Fire-and-forget: run the asset once with example_input, infer"""
    try:
        ok, payload = await _run_asset_sample(
            asset_id,
            tenant_id,
            user_id,
            role,
            example_input,
            timeout_seconds=180,
        )
    except Exception as e:
        logger.info("smoke-test probe raised for %s: %s", asset_id, e)
        return
    if not ok:
        logger.info(
            "smoke-test probe non-zero exit for %s: %s", asset_id, str(payload)[:200]
        )
        return

    # _run_asset_sample wraps parsed stdout as {"result": <parsed>,
    # "schema_ok": ..., "schema_error": ...}. Unwrap first, then skip
    # if the raw fallback path kicked in (asset didn't emit JSON).
    if not isinstance(payload, dict):
        return
    actual = payload.get("result", payload)
    if not isinstance(actual, dict) or "raw" in actual:
        return

    # Infer the JSON Schema from the observed output shape.
    try:
        import sys

        runtime_path = Path("/app/apps/agent-runtime")
        if runtime_path.exists() and str(runtime_path) not in sys.path:
            sys.path.insert(0, str(runtime_path))
        from engine.code_analyzer import _infer_schema_from_example  # noqa: E402
    except Exception:
        return
    inferred = _infer_schema_from_example(actual)
    if not inferred:
        return

    # Write back using a fresh DB session — the one tied to the
    # upload request is long-closed by now.
    try:
        from app.core.deps import async_session

        async with async_session() as db:
            a = await db.get(CodeAsset, uuid.UUID(asset_id))
            if a is None or a.output_schema:
                return  # someone else (or another probe) got there first
            a.output_schema = inferred
            # Leave a note so admins can see where it came from.
            notes = list(a.analysis_notes or [])
            notes.append(
                {
                    "level": "info",
                    "message": "output_schema populated by smoke-test probe.",
                    "suggestion": "The asset was run once with the example_input; "
                    "the stdout shape became the output_schema.",
                }
            )
            a.analysis_notes = notes
            await db.commit()
            logger.info("smoke-test probe populated output_schema for %s", asset_id)
    except Exception as e:
        logger.warning("smoke-test probe DB write failed for %s: %s", asset_id, e)


@router.post("/{asset_id}/test")
async def test_asset(
    asset_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run the asset with the provided sample input via the code_asset tool."""
    result = await db.execute(
        select(CodeAsset).where(
            CodeAsset.id == asset_id,
            CodeAsset.tenant_id == user.tenant_id,
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        return error("not found", 404)
    if a.status != CodeAssetStatus.READY:
        return error(f"asset status is {a.status} — wait for analysis to complete", 400)

    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    ok, payload = await _run_asset_sample(
        str(asset_id),
        str(user.tenant_id),
        str(user.id),
        role_val,
        body.get("input") or {},
        timeout_seconds=int(body.get("timeout_seconds", 120)),
    )
    if not ok:
        return error(str(payload), 500)
    # Persist last-test for dashboard visibility
    a.last_test_input = body.get("input") or {}
    a.last_test_output = payload
    a.last_test_ok = True
    from datetime import datetime as _dt, timezone as _tz

    a.last_test_at = _dt.now(_tz.utc)
    await db.commit()
    return success({"execution": payload, "metadata": {}})


@router.get("/{asset_id}/download")
async def download_asset(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Fetch the zip — called by sandbox pods via the short-lived JWT
    passed in MODEL_AUTH_HEADER (same pattern as ml_models/download)."""
    result = await db.execute(
        select(CodeAsset).where(
            CodeAsset.id == asset_id,
            CodeAsset.tenant_id == user.tenant_id,
        )
    )
    a = result.scalar_one_or_none()
    if not a or not a.storage_uri:
        return error("not found", 404)
    path = Path(a.storage_uri)
    if not path.exists():
        return error("stored file missing on disk", 404)
    return FileResponse(
        path=str(path),
        filename=f"{a.name}.zip",
        media_type="application/zip",
    )


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(CodeAsset).where(
            CodeAsset.id == asset_id,
            CodeAsset.tenant_id == user.tenant_id,
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        return error("not found", 404)
    # Delete is stricter than view/use/edit shares: ONLY the asset's
    # creator OR a tenant admin can delete. Edit-shares are revoked at
    # the resource boundary so a collaborator can't yank work out from
    # under the owner.
    from app.core.permissions import assert_can_delete

    if not assert_can_delete(a, user):
        return error(
            "Only the asset owner or a tenant admin can delete this asset", 403
        )
    a.status = CodeAssetStatus.DELETED
    await db.commit()
    return success({"deleted": True})
