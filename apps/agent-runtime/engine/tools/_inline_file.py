"""Helper: accept either a file path OR inline text in a tool argument.

Many file-oriented tools (file_reader, csv_analyzer, document_parser,
spreadsheet_analyzer, presentation_analyzer) historically required a
`path` to an existing file on disk. End users invoking the tool from
chat have no way to supply a path — they paste content inline.

`materialise_path()` lets a tool accept either:
  * `path: "/absolute/path"` — used as-is (legacy behaviour preserved).
  * `text: "<inline content>"` — written to a NamedTemporaryFile in
    EXPORT_DIR (or system tempdir if EXPORT_DIR is missing/unwritable),
    and the path returned. The caller is responsible for nothing — the
    file lives until process exit, which is fine for the duration of
    a single tool invocation.

The returned path is suitable for any library that takes a path.
Returns (path, error_message). If error_message is non-empty, the
caller should return ToolResult(content=error_message, is_error=True).
"""

from __future__ import annotations

import os
import tempfile
from typing import Any


def materialise_path(
    args: dict[str, Any], *, default_ext: str = "txt"
) -> tuple[str, str]:
    """Resolve a path-like argument to a real on-disk path.

    Args:
      args: tool's argument dict.
      default_ext: extension to use if the inline payload doesn't hint
                   at a format (used to name the temp file).

    Returns:
      (path, error). If `error` is empty the path is usable.
    """
    path = (args.get("path") or "").strip()
    if path:
        if not os.path.exists(path):
            return "", f"File not found: {path}"
        return path, ""

    text = args.get("text") or args.get("content") or args.get("inline")
    if isinstance(text, (list, dict)):
        # Best-effort serialise — JSON/list inputs land as readable text.
        import json as _json

        try:
            text = _json.dumps(text, indent=2, default=str)
        except (TypeError, ValueError):
            text = str(text)
    if not text:
        return "", (
            "Either `path` (filesystem path) or `text` (inline content) "
            "must be supplied. Pass the document content as `text` if you "
            "have it inline; pass `path` if it's already on disk."
        )

    # Pick a writable directory. Prefer EXPORT_DIR (set by helm + dev-local.sh),
    # fall back to the system tempdir.
    export = os.environ.get("EXPORT_DIR")
    base = export if export and os.access(export, os.W_OK) else tempfile.gettempdir()
    os.makedirs(base, exist_ok=True)

    # If the caller specified a format hint, prefer it for the file
    # extension so downstream parsers detect the right type.
    ext = (args.get("format") or args.get("ext") or default_ext).lstrip(".")
    fd, tmp_path = tempfile.mkstemp(suffix=f".{ext}", dir=base)
    try:
        if isinstance(text, bytes):
            os.write(fd, text)
        else:
            os.write(fd, str(text).encode("utf-8"))
    finally:
        os.close(fd)
    return tmp_path, ""
