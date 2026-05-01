"""Structured data extraction from documents - tables, key-value pairs, sections, clauses."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class DocumentExtractorTool(BaseTool):
    name = "document_extractor"
    description = (
        "Extract structured data from documents. Parses tables into rows/columns, "
        "extracts key-value pairs (dates, amounts, percentages, names), identifies "
        "document sections and clauses, and returns structured JSON output. "
        "Works with text content directly or reads from files."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text content to extract from (use this OR file_path)",
            },
            "file_path": {
                "type": "string",
                "description": "Path to a file to extract from (use this OR text)",
            },
            "extract_type": {
                "type": "string",
                "enum": ["tables", "key_values", "sections", "entities", "all"],
                "description": "What to extract: tables, key_values, sections, entities, or all",
                "default": "all",
            },
            "patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional custom regex patterns to search for",
            },
        },
        "required": [],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        text = arguments.get("text", "")
        file_path = arguments.get("file_path", "")
        extract_type = arguments.get("extract_type", "all")
        custom_patterns = arguments.get("patterns", [])

        if not text and not file_path:
            return ToolResult(
                content="Error: provide either 'text' or 'file_path'", is_error=True
            )

        if file_path and not text:
            text = self._read_file(file_path)
            if text.startswith("Error:"):
                return ToolResult(content=text, is_error=True)

        results: dict[str, Any] = {}

        if extract_type in ("tables", "all"):
            results["tables"] = self._extract_tables(text)
        if extract_type in ("key_values", "all"):
            results["key_values"] = self._extract_key_values(text)
        if extract_type in ("sections", "all"):
            results["sections"] = self._extract_sections(text)
        if extract_type in ("entities", "all"):
            results["entities"] = self._extract_entities(text)
        if custom_patterns:
            results["custom_matches"] = self._extract_custom(text, custom_patterns)

        output = json.dumps(results, indent=2, default=str)
        total_items = sum(
            len(v) if isinstance(v, (list, dict)) else 1 for v in results.values()
        )

        return ToolResult(
            content=output,
            metadata={"extract_type": extract_type, "total_items": total_items},
        )

    def _read_file(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path}"
        try:
            if path.suffix.lower() == ".pdf":
                from PyPDF2 import PdfReader
                reader = PdfReader(str(path))
                pages = []
                for page in reader.pages:
                    t = page.extract_text() or ""
                    if t.strip():
                        pages.append(t)
                return "\n\n".join(pages)
            elif path.suffix.lower() == ".docx":
                from docx import Document
                doc = Document(str(path))
                return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
            else:
                return path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"Error: Failed to read file: {e}"

    def _extract_tables(self, text: str) -> list[dict[str, Any]]:
        tables: list[dict[str, Any]] = []

        pipe_pattern = re.compile(
            r"((?:\|[^\n]+\|\n){2,})", re.MULTILINE
        )
        for match in pipe_pattern.finditer(text):
            rows = []
            for line in match.group(0).strip().split("\n"):
                if re.match(r"^\|[\s\-:|]+\|$", line):
                    continue
                cells = [c.strip() for c in line.strip("|").split("|")]
                rows.append(cells)
            if len(rows) >= 2:
                headers = rows[0]
                data = rows[1:]
                tables.append({"headers": headers, "rows": data, "row_count": len(data)})

        tab_pattern = re.compile(r"((?:[^\n]*\t[^\n]*\n){2,})", re.MULTILINE)
        for match in tab_pattern.finditer(text):
            rows = []
            for line in match.group(0).strip().split("\n"):
                cells = [c.strip() for c in line.split("\t")]
                rows.append(cells)
            if len(rows) >= 2:
                tables.append({
                    "headers": rows[0],
                    "rows": rows[1:],
                    "row_count": len(rows) - 1,
                })

        csv_like = re.compile(r"((?:[^\n]*,[^\n]*\n){3,})", re.MULTILINE)
        for match in csv_like.finditer(text):
            try:
                reader = csv.reader(io.StringIO(match.group(0).strip()))
                rows = list(reader)
                if len(rows) >= 2 and all(len(r) == len(rows[0]) for r in rows):
                    tables.append({
                        "headers": rows[0],
                        "rows": rows[1:],
                        "row_count": len(rows) - 1,
                    })
            except csv.Error:
                pass

        return tables

    def _extract_key_values(self, text: str) -> dict[str, list[dict[str, str]]]:
        results: dict[str, list[dict[str, str]]] = {
            "dates": [],
            "monetary_amounts": [],
            "percentages": [],
            "durations": [],
            "parties": [],
            "references": [],
        }

        date_patterns = [
            r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
            r"\b(\d{4}[/-]\d{1,2}[/-]\d{1,2})\b",
            r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})\b",
            r"\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b",
        ]
        for pattern in date_patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                context = self._get_context(text, m.start(), m.end())
                results["dates"].append({"value": m.group(1), "context": context})

        money_patterns = [
            r"\$\s?([\d,]+(?:\.\d{1,2})?)\s*(?:million|billion|thousand|M|B|K|mn|bn)?",
            r"([\d,]+(?:\.\d{1,2})?)\s*(?:USD|EUR|GBP|AUD|CAD)",
            r"(?:USD|EUR|GBP)\s?([\d,]+(?:\.\d{1,2})?)",
            r"\$([\d,]+(?:\.\d{1,2})?)\s*/\s*(?:MWh|kWh|MW|kW)",
        ]
        for pattern in money_patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                context = self._get_context(text, m.start(), m.end())
                results["monetary_amounts"].append({
                    "value": m.group(0).strip(),
                    "context": context,
                })

        pct_patterns = [
            r"([\d.]+)\s*%",
            r"([\d.]+)\s*(?:percent|per cent)",
        ]
        for pattern in pct_patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                context = self._get_context(text, m.start(), m.end())
                results["percentages"].append({
                    "value": m.group(0).strip(),
                    "context": context,
                })

        duration_patterns = [
            r"(\d+)\s*(?:year|yr)s?",
            r"(\d+)\s*(?:month)s?",
            r"(\d+)\s*(?:day)s?",
            r"(\d+)\s*(?:week)s?",
        ]
        for pattern in duration_patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                context = self._get_context(text, m.start(), m.end())
                results["durations"].append({"value": m.group(0), "context": context})

        ref_pattern = r"(?:Section|Article|Clause|Schedule|Appendix|Exhibit)\s+[\d.]+(?:\([a-z]\))?"
        for m in re.finditer(ref_pattern, text, re.IGNORECASE):
            context = self._get_context(text, m.start(), m.end())
            results["references"].append({"value": m.group(0), "context": context})

        return results

    def _extract_sections(self, text: str) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []

        heading_patterns = [
            r"^(#{1,6})\s+(.+)$",
            r"^(ARTICLE|SECTION|PART|CHAPTER)\s+(\d+[\d.]*)[:\s]*(.*)$",
            r"^(\d+\.(?:\d+\.)*)\s+([A-Z][^\n]{3,})$",
            r"^([A-Z][A-Z\s]{4,})$",
        ]

        lines = text.split("\n")
        current_section: dict[str, Any] | None = None

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            matched = False
            for pat in heading_patterns:
                m = re.match(pat, stripped, re.MULTILINE | re.IGNORECASE)
                if m:
                    if current_section:
                        sections.append(current_section)
                    current_section = {
                        "heading": stripped,
                        "line_number": i + 1,
                        "content_preview": "",
                    }
                    matched = True
                    break

            if not matched and current_section:
                if not current_section["content_preview"]:
                    preview = stripped[:200]
                    current_section["content_preview"] = preview

        if current_section:
            sections.append(current_section)

        return sections

    def _extract_entities(self, text: str) -> dict[str, list[str]]:
        entities: dict[str, list[str]] = {
            "organizations": [],
            "emails": [],
            "urls": [],
            "phone_numbers": [],
            "addresses": [],
        }

        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
        entities["emails"] = list(set(re.findall(email_pattern, text)))

        url_pattern = r"https?://[^\s<>\"')\]]+"
        entities["urls"] = list(set(re.findall(url_pattern, text)))

        phone_pattern = r"[\+]?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}"
        phones = re.findall(phone_pattern, text)
        entities["phone_numbers"] = list(set(p for p in phones if len(p) >= 10))

        org_patterns = [
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Inc|LLC|Ltd|Corp|Corporation|Company|Co|Group|Partners|LP|LLP|GmbH|AG|SA|NV|PLC|Pty)\.?)",
        ]
        for pattern in org_patterns:
            entities["organizations"].extend(
                list(set(re.findall(pattern, text)))
            )

        return entities

    def _extract_custom(self, text: str, patterns: list[str]) -> list[dict[str, Any]]:
        results = []
        for pattern in patterns:
            try:
                matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
                results.append({
                    "pattern": pattern,
                    "matches": matches[:50],
                    "count": len(matches),
                })
            except re.error as e:
                results.append({"pattern": pattern, "error": str(e)})
        return results

    def _get_context(self, text: str, start: int, end: int, window: int = 50) -> str:
        ctx_start = max(0, start - window)
        ctx_end = min(len(text), end + window)
        ctx = text[ctx_start:ctx_end].replace("\n", " ").strip()
        if ctx_start > 0:
            ctx = "..." + ctx
        if ctx_end < len(text):
            ctx = ctx + "..."
        return ctx
