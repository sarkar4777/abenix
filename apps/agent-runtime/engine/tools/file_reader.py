from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from engine.tools.base import BaseTool, ToolResult

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".csv", ".md", ".json"}
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB


class FileReaderTool(BaseTool):
    name = "file_reader"
    description = (
        "Read and extract text content from a file. Pass either `file_path` "
        "(an on-disk file the agent has access to) OR `text` (inline content "
        "that the tool will save to a temp file first). Supports PDF, DOCX, "
        "TXT, CSV, MD, and JSON formats."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to read.",
            },
            "text": {
                "type": "string",
                "description": (
                    "Inline content to read. Use this when the document is "
                    "provided in the chat directly rather than as an upload. "
                    "The tool writes it to a temp file before parsing."
                ),
            },
            "format": {
                "type": "string",
                "description": "Format hint when supplying `text` (pdf, docx, txt, csv, md, json). Auto-detected from file_path otherwise.",
                "enum": ["pdf", "docx", "txt", "csv", "md", "json"],
            },
        },
        "required": [],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from engine.tools._inline_file import materialise_path

        file_path = arguments.get("file_path") or arguments.get("path")
        # materialise_path handles BOTH inline `text` and on-disk paths.
        # Pass the existing arg dict but with a unified `path` key.
        norm_args = dict(arguments)
        if file_path and not norm_args.get("path"):
            norm_args["path"] = file_path
        resolved, err = materialise_path(norm_args, default_ext="txt")
        if err:
            return ToolResult(content=err, is_error=True)
        path = Path(resolved)
        if not path.exists():
            return ToolResult(content=f"File not found: {resolved}", is_error=True)

        if path.stat().st_size > MAX_FILE_SIZE:
            return ToolResult(content="File exceeds 50MB size limit", is_error=True)

        ext = path.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return ToolResult(
                content=f"Unsupported file type: {ext}. Supported: {', '.join(ALLOWED_EXTENSIONS)}",
                is_error=True,
            )

        try:
            if ext == ".pdf":
                content = self._read_pdf(path)
            elif ext == ".docx":
                content = self._read_docx(path)
            elif ext == ".csv":
                content = self._read_csv(path)
            else:
                content = path.read_text(encoding="utf-8", errors="replace")

            char_count = len(content)
            if char_count > 100_000:
                content = (
                    content[:100_000]
                    + f"\n\n[Truncated at 100,000 characters. Total: {char_count}]"
                )

            return ToolResult(
                content=content,
                metadata={
                    "file": str(path),
                    "extension": ext,
                    "size_bytes": path.stat().st_size,
                },
            )
        except Exception as e:
            return ToolResult(content=f"Failed to read file: {str(e)}", is_error=True)

    def _read_pdf(self, path: Path) -> str:
        from PyPDF2 import PdfReader

        reader = PdfReader(str(path))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"--- Page {i + 1} ---\n{text}")
        return "\n\n".join(pages) if pages else "No text content found in PDF."

    def _read_docx(self, path: Path) -> str:
        from docx import Document

        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return (
            "\n\n".join(paragraphs)
            if paragraphs
            else "No text content found in document."
        )

    def _read_csv(self, path: Path) -> str:
        text = path.read_text(encoding="utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return "Empty CSV file."

        lines = []
        header = rows[0]
        lines.append(" | ".join(header))
        lines.append("-" * len(lines[0]))
        for row in rows[1:51]:
            lines.append(" | ".join(row))
        if len(rows) > 51:
            lines.append(f"\n[Showing 50 of {len(rows) - 1} rows]")
        return "\n".join(lines)
