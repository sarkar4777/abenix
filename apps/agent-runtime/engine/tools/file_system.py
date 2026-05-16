"""File System Tool — recursive directory traversal, glob patterns, file reading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class FileSystemTool(BaseTool):
    name = "file_system"
    description = (
        "Traverse directories, list files recursively, read file contents, "
        "and match glob patterns. Works with local filesystem, mounted NFS/SMB shares, "
        "and Docker volumes."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["list_recursive", "read_file", "glob", "stat"],
                "description": "Filesystem operation to perform",
            },
            "path": {
                "type": "string",
                "description": "Directory or file path",
            },
            "pattern": {
                "type": "string",
                "description": "Glob pattern for 'glob' operation (e.g., '**/*.py', 'src/**/*.java')",
            },
            "max_files": {
                "type": "integer",
                "description": "Max files to return (default: 500)",
                "default": 500,
            },
            "max_size_kb": {
                "type": "integer",
                "description": "Max file size to read in KB (default: 500)",
                "default": 500,
            },
        },
        "required": ["operation", "path"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        operation = arguments.get("operation", "")
        path_str = arguments.get("path", "")
        max_files = min(arguments.get("max_files", 500), 5000)
        max_size_kb = min(arguments.get("max_size_kb", 500), 2000)

        if not path_str:
            return ToolResult(content="Error: path is required", is_error=True)

        path = Path(path_str)

        if operation == "list_recursive":
            return await self._list_recursive(path, max_files)
        elif operation == "read_file":
            return await self._read_file(path, max_size_kb)
        elif operation == "glob":
            pattern = arguments.get("pattern", "**/*")
            return await self._glob(path, pattern, max_files)
        elif operation == "stat":
            return await self._stat(path)
        else:
            return ToolResult(
                content=f"Error: Unknown operation: {operation}", is_error=True
            )

    async def _list_recursive(self, path: Path, max_files: int) -> ToolResult:
        if not path.is_dir():
            return ToolResult(
                content=f"Error: {path} is not a directory", is_error=True
            )

        files = []
        try:
            for item in sorted(path.rglob("*")):
                if len(files) >= max_files:
                    break
                if item.is_file():
                    try:
                        stat = item.stat()
                        files.append(
                            {
                                "path": str(item.relative_to(path)),
                                "size_bytes": stat.st_size,
                                "extension": item.suffix,
                                "name": item.name,
                            }
                        )
                    except (PermissionError, OSError):
                        continue
        except PermissionError:
            return ToolResult(
                content=f"Error: Permission denied for {path}", is_error=True
            )

        # Categorize by extension
        extensions = {}
        for f in files:
            ext = f["extension"] or "(none)"
            extensions[ext] = extensions.get(ext, 0) + 1

        return ToolResult(
            content=json.dumps(
                {
                    "status": "success",
                    "directory": str(path),
                    "total_files": len(files),
                    "truncated": len(files) >= max_files,
                    "by_extension": dict(
                        sorted(extensions.items(), key=lambda x: -x[1])
                    ),
                    "files": files,
                }
            )
        )

    async def _read_file(self, path: Path, max_size_kb: int) -> ToolResult:
        if not path.is_file():
            return ToolResult(
                content=f"Error: {path} not found or not a file", is_error=True
            )

        size = path.stat().st_size
        if size > max_size_kb * 1024:
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "truncated",
                        "path": str(path),
                        "size_bytes": size,
                        "message": f"File exceeds {max_size_kb}KB limit. Reading first {max_size_kb}KB.",
                        "content": path.read_bytes()[: max_size_kb * 1024].decode(
                            "utf-8", errors="replace"
                        ),
                    }
                )
            )

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = path.read_bytes().decode("utf-8", errors="replace")

        return ToolResult(
            content=json.dumps(
                {
                    "status": "success",
                    "path": str(path),
                    "size_bytes": size,
                    "extension": path.suffix,
                    "content": content,
                }
            )
        )

    async def _glob(self, path: Path, pattern: str, max_files: int) -> ToolResult:
        if not path.is_dir():
            return ToolResult(
                content=f"Error: {path} is not a directory", is_error=True
            )

        matches = []
        for item in sorted(path.glob(pattern)):
            if len(matches) >= max_files:
                break
            if item.is_file():
                try:
                    matches.append(
                        {
                            "path": str(item.relative_to(path)),
                            "size_bytes": item.stat().st_size,
                            "extension": item.suffix,
                        }
                    )
                except (PermissionError, OSError):
                    continue

        return ToolResult(
            content=json.dumps(
                {
                    "status": "success",
                    "directory": str(path),
                    "pattern": pattern,
                    "matches": len(matches),
                    "files": matches,
                }
            )
        )

    async def _stat(self, path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult(content=f"Error: {path} does not exist", is_error=True)

        stat = path.stat()
        from datetime import datetime

        return ToolResult(
            content=json.dumps(
                {
                    "status": "success",
                    "path": str(path),
                    "type": "directory" if path.is_dir() else "file",
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "is_symlink": path.is_symlink(),
                }
            )
        )
