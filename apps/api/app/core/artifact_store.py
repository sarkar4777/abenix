"""Durable copies of uploaded code assets and ML models.

Files are written to the local data volume first, which is all a single-node
install needs. When STORAGE_BACKEND is s3 or azure the same file is mirrored
to object storage under a key derived from its path, so any API replica or
pod that lacks the file, after a restart, a reschedule or on a volume it does
not share, can restore it before serving it. With the local backend every
call here is a cheap no-op.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from app.core.object_storage import ObjectNotFound, get_object_storage

logger = logging.getLogger(__name__)


class ArtifactStoreError(RuntimeError):
    """The durable copy could not be written."""


def _data_root() -> Path:
    return Path(os.environ.get("OBJECT_STORAGE_LOCAL_ROOT", "/data"))


def remote_enabled() -> bool:
    return os.environ.get("STORAGE_BACKEND", "local").lower() in ("s3", "azure")


def key_for(path: str | Path) -> str:
    """Stable object key for a file, its path under the data root."""
    p = Path(path)
    try:
        rel = p.resolve().relative_to(_data_root().resolve())
        return "artifacts/" + rel.as_posix()
    except (ValueError, OSError):
        return "artifacts/misc/" + p.name


async def mirror(path: str | Path) -> None:
    """Copy a freshly written file to object storage. Raises if that fails."""
    if not remote_enabled():
        return
    p = Path(path)
    try:
        with open(p, "rb") as fh:
            await get_object_storage().put(key_for(p), fh)
    except Exception as e:  # noqa: BLE001
        raise ArtifactStoreError(f"could not store {p.name} durably: {e}") from e


async def ensure_local(path: str | Path) -> bool:
    """True when the file is on this pod, restoring it from object storage if needed."""
    p = Path(path)
    if p.is_file():
        return True
    if not remote_enabled():
        return False
    store = get_object_storage()
    tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex[:8]}.part")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as fh:
            async for chunk in store.get_stream(key_for(p)):
                fh.write(chunk)
        if tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            return False
        os.replace(tmp, p)
        logger.info("restored %s from object storage", p)
        return True
    except ObjectNotFound:
        tmp.unlink(missing_ok=True)
        return False
    except Exception as e:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        logger.warning("could not restore %s from object storage: %s", p, e)
        return False


async def remove(path: str | Path) -> None:
    """Delete the local file and its durable copy."""
    p = Path(path)
    try:
        p.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("could not delete %s: %s", p, e)
    if remote_enabled():
        try:
            await get_object_storage().delete(key_for(p))
        except Exception as e:  # noqa: BLE001
            logger.warning("could not delete durable copy of %s: %s", p, e)
