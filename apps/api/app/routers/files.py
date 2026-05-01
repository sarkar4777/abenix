"""File Download API — serves uploaded documents and agent-generated exports."""

from __future__ import annotations

import base64
import mimetypes
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

ALLOWED_UPLOAD_TYPES = frozenset({
    "application/pdf", "text/plain", "text/csv", "text/markdown",
    "application/json", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "application/zip", "application/gzip",
})

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from models.user import User

router = APIRouter(prefix="/api/files", tags=["files"])


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

    # Verify file exists
    if not await storage.exists(uri):
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

    # Check storage backend
    export_dir = os.environ.get("EXPORT_DIR", "/tmp/abenix_exports")

    if storage and storage.backend != "local":
        # Cloud: check in exports bucket
        uri = f"s3://{os.environ.get('STORAGE_S3_BUCKET', 'abenix-exports')}/exports/{safe_name}"
        if await storage.exists(uri):
            download_url = await storage.get_download_url(uri, expires=3600)
            return RedirectResponse(url=download_url, status_code=302)
        return error("Export file not found", 404)

    # Local: serve from EXPORT_DIR
    filepath = Path(export_dir) / safe_name
    if not filepath.exists():
        return error("Export file not found", 404)

    # Security: ensure the file is within EXPORT_DIR
    try:
        filepath.resolve().relative_to(Path(export_dir).resolve())
    except ValueError:
        return error("Access denied", 403)

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
