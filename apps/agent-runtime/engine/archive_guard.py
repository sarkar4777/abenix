"""Limits for zip containers, checked before anything inflates them.

DOCX, XLSX and PPTX are zip files, so a small upload can expand to many gigabytes
inside a parser that reads every part into memory. The central directory lists
what each entry would become, and Python never reads past those declared sizes.
"""

from __future__ import annotations

import os
import stat
import tarfile
import zipfile
from pathlib import PurePosixPath
from typing import IO, Iterable


class UnsafeArchive(ValueError):
    pass


def _limit(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def max_entries() -> int:
    return _limit("ARCHIVE_MAX_ENTRIES", 20_000)


def max_total_bytes() -> int:
    return _limit("ARCHIVE_MAX_TOTAL_BYTES", 2 * 1024**3)


def max_ratio() -> int:
    return _limit("ARCHIVE_MAX_RATIO", 200)


# small parts compress well for honest reasons, only big ones can do damage
_RATIO_FLOOR = 10 * 1024 * 1024


def unsafe_name(name: str) -> bool:
    cleaned = name.replace("\\", "/")
    if cleaned.startswith("/") or (len(cleaned) > 1 and cleaned[1] == ":"):
        return True
    return ".." in PurePosixPath(cleaned).parts


def check_zip(source: str | IO[bytes], what: str = "This archive") -> None:
    """Raises UnsafeArchive, a file that is not a zip at all is left to its parser."""
    try:
        with zipfile.ZipFile(source) as z:
            infos = z.infolist()
    except zipfile.BadZipFile:
        return
    _check_entries(
        ((i.filename, i.file_size, i.compress_size) for i in infos), len(infos), what
    )


def _check_entries(
    entries: Iterable[tuple[str, int, int]], count: int, what: str
) -> None:
    if count > max_entries():
        raise UnsafeArchive(
            f"{what} holds {count:,} files and the limit is {max_entries():,}."
        )
    total = 0
    for name, size, packed in entries:
        if unsafe_name(name):
            raise UnsafeArchive(f"{what} has a path that leaves its folder: {name!r}.")
        total += size
        if total > max_total_bytes():
            raise UnsafeArchive(
                f"{what} would expand past the limit of {max_total_bytes():,} bytes."
            )
        if size > _RATIO_FLOOR and size > max(packed, 1) * max_ratio():
            raise UnsafeArchive(
                f"{what} would expand {name!r} more than {max_ratio()} times, "
                "which is how a zip bomb looks."
            )


def check_tar(tar: tarfile.TarFile, what: str = "This archive") -> None:
    """Sizes are stored per member, links are refused because they can point anywhere."""
    members = tar.getmembers()
    for m in members:
        if m.issym() or m.islnk() or stat.S_ISFIFO(m.mode) or m.ischr() or m.isblk():
            raise UnsafeArchive(f"{what} has a link or device: {m.name!r}.")
    _check_entries(((m.name, m.size, m.size) for m in members), len(members), what)
