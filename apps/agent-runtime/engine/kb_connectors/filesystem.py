"""A mounted filesystem or NFS share, limited to folders an operator allowed."""

from __future__ import annotations

import asyncio
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from engine.kb_connectors.base import (
    ConfigError,
    Connector,
    ConnectorError,
    Field,
    Page,
    RemoteItem,
    TooLarge,
)

PAGE = 500


def allowed_roots() -> list[Path]:
    raw = os.environ.get("KB_CONNECTOR_FS_ROOTS", "")
    return [Path(p).resolve() for p in raw.split(os.pathsep) if p.strip()]


class FilesystemConnector(Connector):
    kind = "filesystem"
    label = "Filesystem or NFS mount"
    verified_live = True
    needs_admin = True
    fields = [
        Field(
            "path",
            "Folder",
            required=True,
            help="Must sit under a folder in KB_CONNECTOR_FS_ROOTS on the worker.",
        ),
        Field("capture_acl", "Capture owner and mode", kind="bool", default=True),
    ]

    def _root(self) -> Path:
        roots = allowed_roots()
        if not roots:
            raise ConfigError(
                "This server allows no folders. An operator sets KB_CONNECTOR_FS_ROOTS "
                "on the worker to turn this on."
            )
        path = Path(self.cfg("path", "")).resolve()
        if not any(path == r or r in path.parents for r in roots):
            raise ConfigError(
                f"{self.cfg('path')} is outside the allowed folders "
                f"({', '.join(str(r) for r in roots)})."
            )
        return path

    async def validate(self) -> None:
        self._root()

    def _inside(self, path: Path) -> bool:
        """A link pointing out of the folder must not bring its target in."""
        root = self._root()
        try:
            resolved = path.resolve()
        except OSError:
            return False
        return resolved == root or root in resolved.parents

    def _walk(self, after: str) -> tuple[list[RemoteItem], str | None]:
        root = self._root()
        if not root.is_dir():
            raise ConnectorError(f"{root} is not a folder or is not mounted here.")
        found: list[str] = []
        for folder, dirs, files in os.walk(root, followlinks=False):
            dirs.sort()
            for name in files:
                rel = (Path(folder) / name).relative_to(root).as_posix()
                if rel > after:
                    found.append(rel)
        found.sort()
        items = []
        for rel in found[:PAGE]:
            path = root / rel
            try:
                st = path.lstat()
                if stat.S_ISLNK(st.st_mode):
                    if not self._inside(path):
                        continue
                    st = path.stat()
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            acl = None
            if self.cfg("capture_acl", True):
                acl = {
                    "public": None,
                    "principals": [],
                    "posix": {
                        "uid": st.st_uid,
                        "gid": st.st_gid,
                        "mode": oct(stat.S_IMODE(st.st_mode)),
                    },
                }
            items.append(
                RemoteItem(
                    external_id=rel,
                    name=Path(rel).name,
                    version=f"{st.st_mtime_ns}-{st.st_size}",
                    size=st.st_size,
                    modified_at=datetime.fromtimestamp(st.st_mtime, timezone.utc),
                    acl=acl,
                )
            )
        last = found[PAGE - 1] if len(found) > PAGE else None
        return items, last

    async def list_page(self, page_cursor, sync_cursor) -> Page:
        after = (page_cursor or {}).get("after") or ""
        items, last = await asyncio.to_thread(self._walk, after)
        if last:
            return Page(items=items, next_cursor={"after": last})
        return Page(items=items, finished=True)

    async def fetch(self, item: RemoteItem, max_bytes: int) -> bytes:
        path = self._root() / item.external_id
        if not self._inside(path):
            raise ConnectorError("This file now points outside the allowed folder.")

        def read() -> bytes:
            with open(path, "rb") as fh:
                data = fh.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise TooLarge(f"It is larger than the limit of {max_bytes} bytes.")
            return data

        return await asyncio.to_thread(read)
