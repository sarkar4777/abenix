"""File Download API — serves uploaded documents and agent-generated exports."""

from __future__ import annotations

import mimetypes
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

ALLOWED_UPLOAD_TYPES = frozenset(
    {
        "application/pdf",
        "text/plain",
        "text/csv",
        "text/markdown",
        "application/json",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "application/zip",
        "application/gzip",
    }
)

from app.core.deps import get_current_user, get_db
from app.core.platform_features import _platform_tenant_id
from app.core.responses import error, success
from models.user import User

router = APIRouter(prefix="/api/files", tags=["files"])


def _tenant_owns_uri(uri: str, tenant_id: Any) -> bool:
    from engine.storage import service as storage_service

    tenant = str(tenant_id)
    for scheme, bucket in (
        ("s3://", storage_service.STORAGE_S3_BUCKET),
        ("az://", storage_service.STORAGE_AZURE_CONTAINER),
    ):
        if uri.startswith(scheme):
            parts = uri[len(scheme) :].split("/")
            return (
                len(parts) > 2
                and parts[0] == bucket
                and parts[1] == tenant
                and ".." not in parts
            )
    path = uri[len("file://") :] if uri.startswith("file://") else uri
    if "://" in path:
        return False
    jail = (Path(storage_service.STORAGE_LOCAL_DIR).resolve() / tenant).resolve()
    return Path(path).resolve().is_relative_to(jail)


@router.get("/download")
async def download_file(
    uri: str = Query(..., description="File URI (file://, s3://, az://)"),
    user: User = Depends(get_current_user),
) -> Any:
    """Download a file by its storage URI."""
    try:
        from engine.storage import get_storage

        storage = get_storage()
    except ImportError:
        return error("Storage service not available", 500)

    # the same answer as a missing file, so this cannot probe what exists elsewhere
    if not _tenant_owns_uri(uri, user.tenant_id) or not await storage.exists(uri):
        return error("File not found", 404)

    # For cloud backends, redirect to presigned URL
    if uri.startswith("s3://") or uri.startswith("az://"):
        download_url = await storage.get_download_url(uri, expires=3600)
        return RedirectResponse(url=download_url, status_code=302)

    # For local backend, stream the file
    try:
        data = await storage.download(uri)
        path = uri.replace("file://", "") if uri.startswith("file://") else uri
        filename = Path(path).name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        return StreamingResponse(
            iter([data]),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(data)),
            },
        )
    except FileNotFoundError:
        return error("File not found", 404)
    except Exception as e:
        return error(f"Download failed: {e}", 500)


@router.get("/export/{filename}")
async def download_export(
    filename: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Download an agent-generated export file by filename."""
    # Sanitize filename — prevent path traversal
    safe_name = Path(filename).name
    if not safe_name or safe_name != filename:
        return error("Invalid filename", 400)

    try:
        from engine.storage import get_storage

        storage = get_storage()
    except ImportError:
        storage = None

    tenant = str(user.tenant_id)
    if storage and storage.backend != "local":
        from engine.storage import service as storage_service

        scheme, bucket = (
            ("s3", storage_service.STORAGE_S3_BUCKET)
            if storage.backend == "s3"
            else ("az", storage_service.STORAGE_AZURE_CONTAINER)
        )
        uri = f"{scheme}://{bucket}/{tenant}/exports/{safe_name}"
        if await storage.exists(uri):
            download_url = await storage.get_download_url(uri, expires=3600)
            return RedirectResponse(url=download_url, status_code=302)
        return error("Export file not found", 404)

    export_dir = Path(os.environ.get("EXPORT_DIR", "/tmp/abenix_exports")).resolve()
    filepath = export_dir / tenant / safe_name
    # files written before exports were per tenant have no owner, so only the platform tenant reads them
    if not filepath.is_file():
        platform = await _platform_tenant_id(db)
        legacy = export_dir / safe_name
        if platform is None or str(platform) != tenant or not legacy.is_file():
            return error("Export file not found", 404)
        filepath = legacy
    if not filepath.resolve().is_relative_to(export_dir):
        return error("Export file not found", 404)

    data = filepath.read_bytes()
    content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"

    return StreamingResponse(
        iter([data]),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Content-Length": str(len(data)),
        },
    )


@router.get("/list")
async def list_files(
    prefix: str = Query("", description="Path prefix filter"),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """List files for the current tenant."""
    try:
        from engine.storage import get_storage

        storage = get_storage()
        files = await storage.list_files(str(user.tenant_id), prefix)
        return success(files)
    except Exception as e:
        return error(f"Failed to list files: {e}", 500)
