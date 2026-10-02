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

from fastapi import Request, APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from models.code_asset import CodeAsset, CodeAssetSource, CodeAssetStatus
from models.user import User
from models.resource_share import SharePermission
from app.core.permissions import is_admin as _is_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/code-assets", tags=["code-assets"])


_CODE_STORE_DIR = Path(os.environ.get("CODE_ASSET_STORE", "/data/code-assets"))
_CODE_STORE_DIR.mkdir(parents=True, exist_ok=True)


async def _owner_names(db: AsyncSession, ids: set[Any]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.full_name, User.email).where(User.id.in_(wanted))
        )
    ).all()
    return {r[0]: (r[1] or r[2]) for r in rows}


def _serialize(
    a: CodeAsset,
    user: User | None = None,
    names: dict[uuid.UUID, str] | None = None,
) -> dict[str, Any]:
    owner = a.created_by
    ownership = None
    if user is not None:
        if owner is None:
            ownership = "platform"
        else:
            ownership = "mine" if owner == user.id else "shared"
    return {
        "id": str(a.id),
        "owner_id": str(owner) if owner else None,
        "owner_name": (names or {}).get(owner) if owner else None,
        "ownership": ownership,
        # share and delete are owner or admin only
        "can_manage": bool(
            user is not None
            and ((owner is not None and owner == user.id) or _is_admin(user))
        ),
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
        "version": a.version or 1,
        # paths stay server side
        "version_history": [
            {k: v for k, v in h.items() if k != "storage_uri"}
            for h in (a.version_history or [])
        ],
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
    with (
        _tf.open(tgz_path, "r:gz") as tar,
        zipfile.ZipFile(
            zip_path,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as zf,
    ):
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
            from engine.tools.code_asset import single_root_prefix  # noqa: E402

            members = [m for m in members if not m.startswith("__MACOSX/")]
            prefix = single_root_prefix(members)
            has_real_subtree = bool(prefix)
            first = prefix[:-1]
            if has_real_subtree:
                tmp_root = tmp.resolve()
                for m in members:
                    if m == first or m == first + "/":
                        continue
                    rel = m[len(first) + 1 :]
                    if not rel:
                        continue
                    dest = (tmp / rel).resolve()
                    if (
                        not str(dest).startswith(str(tmp_root) + os.sep)
                        and dest != tmp_root
                    ):
                        raise ValueError(f"zip-slip blocked: {m!r}")
                    if m.endswith("/"):
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(m) as src, open(dest, "wb") as out:
                            shutil.copyfileobj(src, out)
            else:
                tmp_root = tmp.resolve()
                for m in members:
                    dest = (tmp / m).resolve()
                    if (
                        not str(dest).startswith(str(tmp_root) + os.sep)
                        and dest != tmp_root
                    ):
                        raise ValueError(f"zip-slip blocked: {m!r}")
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


async def _analyze_into(
    asset: CodeAsset, zip_path: Path, *, keep_schemas: bool = True
) -> None:
    """Run the analyzer on an archive and record the result on the asset."""
    try:
        analysis, _size = await _extract_and_analyze(zip_path, str(asset.id))
        asset.detected_language = analysis.get("language") or None
        asset.detected_version = analysis.get("version") or None
        asset.detected_package_manager = analysis.get("package_manager") or None
        asset.detected_entrypoint = analysis.get("entrypoint") or None
        asset.suggested_image = analysis.get("suggested_image") or None
        asset.suggested_build_command = analysis.get("suggested_build_command") or None
        asset.suggested_run_command = analysis.get("suggested_run_command") or None
        asset.analysis_notes = analysis.get("notes") or []
        # schemas from abenix.yaml, examples/*.json or the README
        if analysis.get("input_schema") and not (keep_schemas and asset.input_schema):
            asset.input_schema = analysis["input_schema"]
        if analysis.get("output_schema") and not (keep_schemas and asset.output_schema):
            asset.output_schema = analysis["output_schema"]
        example_input = analysis.get("example_input")
        if example_input and isinstance(asset.input_schema, dict):
            asset.input_schema = {**asset.input_schema, "x-example": example_input}
        has_error_note = any(
            (n.get("level") == "error") for n in (analysis.get("notes") or [])
        )
        if has_error_note or not asset.suggested_run_command:
            asset.status = CodeAssetStatus.FAILED
            asset.error = _analysis_error(analysis.get("notes") or [])
        else:
            asset.status = CodeAssetStatus.READY
            asset.error = None
    except Exception as e:
        logger.exception("code-asset analysis failed")
        asset.status = CodeAssetStatus.FAILED
        asset.error = str(e)[:1000]


def _analysis_error(notes: list[dict[str, Any]]) -> str:
    """The analyzer's own words, so the user knows what to change."""
    errs = [
        str(n.get("message") or n.get("text") or "")
        for n in notes
        if n.get("level") == "error"
    ]
    errs = [e for e in errs if e]
    if errs:
        return "; ".join(errs)[:1000]
    return (
        "No entrypoint or run command could be found. Add a main file "
        "or a README that says how to run it."
    )


async def _save_upload(file: UploadFile) -> Path:
    """Store an uploaded zip or tar.gz as a zip and return its path."""
    file_id = uuid.uuid4().hex[:16]
    raw_path = _CODE_STORE_DIR / f"{file_id}.bin"
    with open(raw_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    if _looks_like_tgz(raw_path):
        tgz_path = raw_path.with_suffix(".tgz")
        raw_path.rename(tgz_path)
        return _tgz_to_zip(tgz_path)
    zip_path = raw_path.with_suffix(".zip")
    raw_path.rename(zip_path)
    return zip_path


_MAX_VERSIONS = int(os.environ.get("CODE_ASSET_MAX_VERSIONS", "20"))


def _push_history(a: CodeAsset, snap: dict[str, Any]) -> list[str]:
    """Append to the bounded history, return archives no version uses any more."""
    hist = [*(a.version_history or []), snap]
    dropped, a.version_history = hist[:-_MAX_VERSIONS], hist[-_MAX_VERSIONS:]
    live = {h.get("storage_uri") for h in a.version_history} | {a.storage_uri}
    return [
        h["storage_uri"]
        for h in dropped
        if h.get("storage_uri") and h["storage_uri"] not in live
    ]


async def _prune(paths: list[str]) -> None:
    """Delete archives and their durable copies, only after the commit that dropped them."""
    from app.core.artifact_store import remove

    for uri in paths:
        await remove(uri)


async def _audit_version(
    db: AsyncSession, user: User, a: CodeAsset, action: str, detail: dict[str, Any]
) -> None:
    from app.core.audit import log_action

    await log_action(
        db,
        user.tenant_id,
        user.id,
        action,
        {"asset_id": str(a.id), "name": a.name, "version": a.version, **detail},
        resource_type="code_asset",
        resource_id=str(a.id),
    )


_RUN_FIELDS = (
    "storage_uri",
    "file_size_bytes",
    "source_type",
    "source_git_url",
    "source_ref",
    "detected_language",
    "detected_version",
    "detected_package_manager",
    "detected_entrypoint",
    "suggested_image",
    "suggested_build_command",
    "suggested_run_command",
    "analysis_notes",
)


_ANALYSIS_FIELDS = (
    "detected_language",
    "detected_version",
    "detected_package_manager",
    "detected_entrypoint",
    "suggested_image",
    "suggested_build_command",
    "suggested_run_command",
    "analysis_notes",
)


def _snapshot(a: CodeAsset, by: str) -> dict[str, Any]:
    from datetime import datetime as _dt, timezone as _tz

    snap: dict[str, Any] = {
        "version": a.version or 1,
        "replaced_at": _dt.now(_tz.utc).isoformat(),
        "replaced_by": by,
    }
    for f in _RUN_FIELDS:
        v = getattr(a, f)
        snap[f] = v.value if hasattr(v, "value") else v
    return snap


@router.post("/{asset_id}/versions")
async def upload_version(
    asset_id: uuid.UUID,
    file: UploadFile | None = File(None),
    metadata: str = Form("{}"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Replace the code behind an asset. Agents keep using the same asset.

    The new archive goes live only if it analyses cleanly, otherwise the
    current version stays and the reason comes back.
    """
    a = await _load_asset(db, user, asset_id, need="edit")
    if a is None:
        return error(
            "Only the owner, an admin or someone with edit access can upload a new version.",
            403,
        )
    try:
        meta = json.loads(metadata)
    except Exception:
        meta = {}
    git_url = (meta.get("git_url") or "").strip()
    git_ref = (meta.get("git_ref") or "").strip() or None
    if file is not None and file.filename:
        zip_path = await _save_upload(file)
        source_type, src_url, src_ref = CodeAssetSource.ZIP, None, None
    elif git_url:
        ok, reason = _validate_git_url(git_url)
        if not ok:
            return error(f"git_url rejected: {reason}", 400)
        try:
            zip_path = await _clone_git(git_url, git_ref)
        except Exception as e:
            return error(f"git clone failed: {e}", 400)
        source_type, src_url, src_ref = CodeAssetSource.GIT, git_url, git_ref
    else:
        return error("Choose a zip or tar.gz, or give a git URL.", 400)

    # analyse off to the side, without holding the row, so a slow upload blocks nobody
    from types import SimpleNamespace

    probe = SimpleNamespace(
        id=a.id, input_schema=None, output_schema=None, status=None, error=None
    )
    await _analyze_into(probe, zip_path, keep_schemas=False)  # type: ignore[arg-type]
    if probe.status != CodeAssetStatus.READY:
        Path(zip_path).unlink(missing_ok=True)
        return error(
            f"Version not applied, version {a.version or 1} is still live. "
            f"{probe.error or 'analysis failed'}",
            422,
        )
    from app.core.artifact_store import ArtifactStoreError, mirror

    try:
        await mirror(zip_path)
    except ArtifactStoreError as e:
        Path(zip_path).unlink(missing_ok=True)
        return error(
            f"Version not applied, version {a.version or 1} is still live. {e}", 503
        )

    # swap under the row lock so two uploads cannot interleave
    a = await _load_asset(db, user, asset_id, need="edit", lock=True)
    if a is None:
        Path(zip_path).unlink(missing_ok=True)
        return error("The asset is no longer available to you.", 404)
    snap = _snapshot(a, str(user.id))
    a.storage_uri = str(zip_path)
    a.file_size_bytes = zip_path.stat().st_size
    a.source_type, a.source_git_url, a.source_ref = source_type, src_url, src_ref
    for f in _ANALYSIS_FIELDS:
        setattr(a, f, getattr(probe, f, None))
    if probe.input_schema is not None:
        a.input_schema = probe.input_schema
    if probe.output_schema is not None:
        a.output_schema = probe.output_schema
    a.status = CodeAssetStatus.READY
    a.error = None
    prune = _push_history(a, snap)
    a.version = (a.version or 1) + 1
    a.last_test_ok = None
    await _audit_version(
        db, user, a, "code_asset.version_uploaded", {"previous": snap["version"]}
    )
    await db.commit()
    await _prune(prune)
    await db.refresh(a)
    return success(_serialize(a, user, await _owner_names(db, {a.created_by})))


@router.post("/{asset_id}/versions/{version}/restore")
async def restore_version(
    asset_id: uuid.UUID,
    version: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Make an earlier version live again, as a new version number."""
    a = await _load_asset(db, user, asset_id, need="edit", lock=True)
    if a is None:
        return error(
            "Only the owner, an admin or someone with edit access can restore a version.",
            403,
        )
    old = next(
        (h for h in (a.version_history or []) if h.get("version") == version), None
    )
    if old is None:
        return error(f"Version {version} is not in this asset's history.", 404)
    from app.core.artifact_store import ensure_local

    if not old.get("storage_uri") or not await ensure_local(old["storage_uri"]):
        return error(f"The archive for version {version} is no longer available.", 410)
    snap = _snapshot(a, str(user.id))
    for f in _RUN_FIELDS:
        v = old.get(f)
        if f == "source_type" and v is not None:
            v = CodeAssetSource(v)
        setattr(a, f, v)
    a.status = CodeAssetStatus.READY
    a.error = None
    prune = _push_history(a, snap)
    a.version = (a.version or 1) + 1
    a.last_test_ok = None
    await _audit_version(
        db, user, a, "code_asset.version_restored", {"restored": version}
    )
    await db.commit()
    await _prune(prune)
    await db.refresh(a)
    return success(_serialize(a, user, await _owner_names(db, {a.created_by})))


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
        zip_path = await _save_upload(file)
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

    from app.core.artifact_store import ArtifactStoreError, mirror

    try:
        await mirror(zip_path)
    except ArtifactStoreError as e:
        Path(zip_path).unlink(missing_ok=True)
        return error(str(e), 503)

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

    await _analyze_into(asset, zip_path)

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

    return success(
        _serialize(asset, user, {user.id: user.full_name or user.email}),
        status_code=201,
    )


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
    rows = result.scalars().all()
    names = await _owner_names(db, {a.created_by for a in rows})
    return success([_serialize(a, user, names) for a in rows])


async def _load_asset(
    db: AsyncSession,
    user: User,
    asset_id: uuid.UUID,
    need: str = "view",
    *,
    lock: bool = False,
) -> CodeAsset | None:
    """Tenant asset the caller may use at `need` (view or edit), else None."""
    from app.core.permissions import accessible_resource_ids, is_admin

    _q = select(CodeAsset).where(
        CodeAsset.id == asset_id,
        CodeAsset.tenant_id == user.tenant_id,
    )
    if lock:
        # re-read under the lock, whatever this session saw before is stale
        _q = _q.with_for_update().execution_options(populate_existing=True)
    a = (await db.execute(_q)).scalar_one_or_none()
    if a is None:
        return None
    if is_admin(user) or (a.created_by is not None and a.created_by == user.id):
        return a
    if need == "view" and a.created_by is None:
        return a  # platform assets are listed to everyone
    perm = SharePermission.EDIT if need == "edit" else SharePermission.VIEW
    shared = await accessible_resource_ids(
        db, user, kind="code_asset", minimum_permission=perm
    )
    return a if a.id in shared else None


@router.get("/{asset_id}")
async def get_asset(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    a = await _load_asset(db, user, asset_id)
    if not a:
        return error("not found", 404)
    return success(_serialize(a, user, await _owner_names(db, {a.created_by})))


@router.put("/{asset_id}")
async def update_asset(
    asset_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    a = await _load_asset(db, user, asset_id)
    if a is not None and not await _load_asset(db, user, asset_id, need="edit"):
        return error(
            "You can view this asset but not change it. Ask its owner for edit access.",
            403,
        )
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
    return success(_serialize(a, user, await _owner_names(db, {a.created_by})))


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
    a = await _load_asset(db, user, asset_id)
    if not a:
        return error("not found", 404)
    if a.status != CodeAssetStatus.READY:
        return error(f"asset status is {a.status} — wait for analysis to complete", 400)
    from app.core.artifact_store import ensure_local

    if not await ensure_local(a.storage_uri or ""):
        return error(
            "This asset's code is not available on this server. Upload it again.", 410
        )

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
        # the user's code failed, not the platform
        from datetime import datetime as _dt, timezone as _tz

        a.last_test_input = body.get("input") or {}
        a.last_test_output = {"error": str(payload)[:4000]}
        a.last_test_ok = False
        a.last_test_at = _dt.now(_tz.utc)
        await db.commit()
        return error(
            f"Your code failed: {str(payload)[:2000]}", 422, error_code="CODE_FAILED"
        )
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
    a = await _load_asset(db, user, asset_id)
    if not a or not a.storage_uri:
        return error("not found", 404)
    from app.core.artifact_store import ensure_local

    path = Path(a.storage_uri)
    if not await ensure_local(path):
        return error("stored file missing on disk", 404)
    return FileResponse(
        path=str(path),
        filename=f"{a.name}.zip",
        media_type="application/zip",
    )


@router.get("/{asset_id}/fetch")
async def fetch_asset_for_sandbox(
    asset_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Archive for a sandbox pod, authorised by a token scoped to this asset."""
    from app.core.security import verify_token

    auth = request.headers.get("authorization", "")
    claims = (
        verify_token(auth.removeprefix("Bearer ")) if auth.startswith("Bearer ") else {}
    )
    if claims.get("type") != "code_asset_fetch" or claims.get("sub") != str(asset_id):
        return error("not found", 404)
    a = (
        await db.execute(select(CodeAsset).where(CodeAsset.id == asset_id))
    ).scalar_one_or_none()
    if (
        a is None
        or not a.storage_uri
        or str(a.tenant_id) != str(claims.get("tenant_id"))
    ):
        return error("not found", 404)
    from app.core.artifact_store import ensure_local

    path = Path(a.storage_uri)
    if not await ensure_local(path):
        return error("stored file missing on disk", 404)
    return FileResponse(
        path=str(path), filename=f"{a.name}.zip", media_type="application/zip"
    )


@router.get("/{asset_id}/dependents")
async def get_asset_dependents(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Agents and pipelines that call this asset."""
    from app.services.dependents import code_asset_dependents

    a = await _load_asset(db, user, asset_id)
    if not a:
        return error("not found", 404)
    return success(await code_asset_dependents(db, user.tenant_id, a.id, a.name))


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: uuid.UUID,
    force: bool = False,
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
    from app.services.dependents import code_asset_dependents, count

    deps = await code_asset_dependents(db, user.tenant_id, a.id, a.name)
    if count(deps) and not force:
        return error(
            f"{a.name} is used by {count(deps)} agent(s) or pipeline(s). They fail if it is deleted.",
            409,
            error_code="IN_USE",
            details={"dependents": deps},
        )
    a.status = CodeAssetStatus.DELETED
    from app.core.audit import log_action

    await log_action(
        db,
        user.tenant_id,
        user.id,
        "code_asset.deleted",
        {"asset_id": str(a.id), "name": a.name, "dependents": deps},
        resource_type="code_asset",
        resource_id=str(a.id),
    )
    await db.commit()
    return success({"deleted": True})
