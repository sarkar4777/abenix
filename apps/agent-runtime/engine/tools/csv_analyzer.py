"""Advanced CSV/tabular data analysis tool with statistics, filtering, aggregation."""

from __future__ import annotations

import csv
import io
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class CsvAnalyzerTool(BaseTool):
    name = "csv_analyzer"
    description = (
        "Analyze CSV and tabular data with advanced operations: descriptive statistics, "
        "filtering, sorting, grouping/aggregation, pivot tables, correlation analysis, "
        "outlier detection, and data quality assessment. Can read CSV files or accept "
        "inline CSV text."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to CSV file to analyze",
            },
            "csv_text": {
                "type": "string",
                "description": "Inline CSV text to analyze (use this OR file_path)",
            },
            "operation": {
                "type": "string",
                "enum": [
                    "describe",
                    "filter",
                    "sort",
                    "group_by",
                    "correlate",
                    "outliers",
                    "quality",
                    "head",
                    "unique",
                    "frequency",
                ],
                "description": "Analysis operation to perform",
                "default": "describe",
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Columns to operate on (default: all numeric)",
            },
            "filter_expr": {
                "type": "string",
                "description": "Filter expression, e.g. 'price > 100' or 'status == active'",
            },
            "sort_by": {
                "type": "string",
                "description": "Column name to sort by",
            },
            "sort_desc": {
                "type": "boolean",
                "description": "Sort descending (default: false)",
                "default": False,
            },
            "group_column": {
                "type": "string",
                "description": "Column to group by for aggregation",
            },
            "agg_func": {
                "type": "string",
                "enum": ["sum", "mean", "count", "min", "max", "median"],
                "description": "Aggregation function for group_by",
                "default": "sum",
            },
            "limit": {
                "type": "integer",
                "description": "Max rows to return (default: 500)",
                "default": 500,
            },
        },
        "required": [],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        file_path = arguments.get("file_path", "")
        csv_text = arguments.get("csv_text", "")
        operation = arguments.get("operation", "describe")

        if not file_path and not csv_text:
            return ToolResult(
                content="Error: provide either 'file_path' or 'csv_text'",
                is_error=True,
            )

        try:
            if file_path:
                path = Path(file_path)
                if not path.exists():
                    return ToolResult(
                        content=f"File not found: {file_path}", is_error=True
                    )
                csv_text = path.read_text(encoding="utf-8", errors="replace")

            rows, headers = self._parse_csv(csv_text)
            if not rows:
                return ToolResult(content="No data rows found in CSV", is_error=True)

        except Exception as e:
            return ToolResult(content=f"Failed to parse CSV: {e}", is_error=True)

        try:
            if operation == "describe":
                result = self._describe(rows, headers, arguments.get("columns"))
            elif operation == "filter":
                result = self._filter(rows, headers, arguments)
            elif operation == "sort":
                result = self._sort(rows, headers, arguments)
            elif operation == "group_by":
                result = self._group_by(rows, headers, arguments)
            elif operation == "correlate":
                result = self._correlate(rows, headers, arguments.get("columns"))
            elif operation == "outliers":
                result = self._outliers(rows, headers, arguments.get("columns"))
            elif operation == "quality":
                result = self._quality(rows, headers)
            elif operation == "head":
                result = self._head(rows, headers, arguments.get("limit", 50))
            elif operation == "unique":
                result = self._unique(rows, headers, arguments.get("columns"))
            elif operation == "frequency":
                result = self._frequency(rows, headers, arguments.get("columns"))
            else:
                return ToolResult(
                    content=f"Unknown operation: {operation}", is_error=True
                )

            output = json.dumps(result, indent=2, default=str)
            return ToolResult(
                content=output,
                metadata={
                    "operation": operation,
                    "total_rows": len(rows),
                    "columns": headers,
                },
            )
        except Exception as e:
            return ToolResult(content=f"Analysis error: {e}", is_error=True)

    def _parse_csv(self, text: str) -> tuple[list[dict[str, str]], list[str]]:
        reader = csv.DictReader(io.StringIO(text.strip()))
        headers = reader.fieldnames or []
        rows = list(reader)
        return rows, list(headers)

    def _to_float(self, val: str) -> float | None:
        try:
            cleaned = val.replace(",", "").replace("$", "").replace("%", "").strip()
            if not cleaned or cleaned == "-":
                return None
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    def _get_numeric_columns(
        self, rows: list[dict[str, str]], headers: list[str]
    ) -> list[str]:
        numeric: list[str] = []
        for col in headers:
            values = [self._to_float(r.get(col, "")) for r in rows[:20]]
            nums = [v for v in values if v is not None]
            if len(nums) > len(values) * 0.5:
                numeric.append(col)
        return numeric

    def _describe(
        self, rows: list[dict[str, str]], headers: list[str], columns: list[str] | None
    ) -> dict[str, Any]:
        cols = columns or self._get_numeric_columns(rows, headers)
        result: dict[str, Any] = {
            "shape": {"rows": len(rows), "columns": len(headers)},
            "columns": headers,
            "numeric_summary": {},
        }

        for col in cols:
            values = [self._to_float(r.get(col, "")) for r in rows]
            nums = [v for v in values if v is not None]
            if not nums:
                continue
            nums_sorted = sorted(nums)
            n = len(nums_sorted)
            result["numeric_summary"][col] = {
                "count": n,
                "missing": len(values) - n,
                "mean": round(statistics.mean(nums), 4),
                "std": round(statistics.stdev(nums), 4) if n > 1 else 0,
                "min": nums_sorted[0],
                "25%": nums_sorted[n // 4],
                "50%": nums_sorted[n // 2],
                "75%": nums_sorted[3 * n // 4],
                "max": nums_sorted[-1],
                "sum": round(sum(nums), 4),
            }

        return result

    def _filter(
        self, rows: list[dict[str, str]], headers: list[str], args: dict[str, Any]
    ) -> dict[str, Any]:
        expr = args.get("filter_expr", "")
        limit = args.get("limit", 50)
        if not expr:
            return {"error": "filter_expr is required"}

        ops = {
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            "!=": lambda a, b: a != b,
            "==": lambda a, b: a == b,
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
            "contains": lambda a, b: b.lower() in str(a).lower(),
        }

        for op_str, op_fn in ops.items():
            if op_str in expr:
                parts = expr.split(op_str, 1)
                col = parts[0].strip()
                val = parts[1].strip().strip("'\"")
                break
        else:
            return {"error": f"Unsupported filter expression: {expr}"}

        filtered = []
        for row in rows:
            cell = row.get(col, "")
            num = self._to_float(cell)
            cmp_val = self._to_float(val)

            if num is not None and cmp_val is not None:
                if op_fn(num, cmp_val):
                    filtered.append(row)
            else:
                if op_fn(cell, val):
                    filtered.append(row)

        return {
            "filter": expr,
            "matched": len(filtered),
            "total": len(rows),
            "rows": filtered[:limit],
        }

    def _sort(
        self, rows: list[dict[str, str]], headers: list[str], args: dict[str, Any]
    ) -> dict[str, Any]:
        sort_by = args.get("sort_by", "")
        desc = args.get("sort_desc", False)
        limit = args.get("limit", 50)

        if not sort_by or sort_by not in headers:
            return {
                "error": f"sort_by column '{sort_by}' not found. Available: {headers}"
            }

        def sort_key(row: dict[str, str]) -> tuple[int, float | str]:
            val = row.get(sort_by, "")
            num = self._to_float(val)
            if num is not None:
                return (0, num)
            return (1, val.lower())

        sorted_rows = sorted(rows, key=sort_key, reverse=desc)
        return {
            "sort_by": sort_by,
            "descending": desc,
            "rows": sorted_rows[:limit],
        }

    def _group_by(
        self, rows: list[dict[str, str]], headers: list[str], args: dict[str, Any]
    ) -> dict[str, Any]:
        group_col = args.get("group_column", "")
        agg_func = args.get("agg_func", "sum")
        value_cols = args.get("columns") or self._get_numeric_columns(rows, headers)

        if not group_col or group_col not in headers:
            return {
                "error": f"group_column '{group_col}' not found. Available: {headers}"
            }

        groups: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            key = row.get(group_col, "(empty)")
            groups[key].append(row)

        agg_fns = {
            "sum": lambda vals: round(sum(vals), 4),
            "mean": lambda vals: round(statistics.mean(vals), 4),
            "count": lambda vals: len(vals),
            "min": lambda vals: min(vals),
            "max": lambda vals: max(vals),
            "median": lambda vals: round(statistics.median(vals), 4),
        }
        fn = agg_fns.get(agg_func, agg_fns["sum"])

        output_rows = []
        for key, group_rows in sorted(groups.items()):
            agg_row: dict[str, Any] = {group_col: key, "_count": len(group_rows)}
            for col in value_cols:
                vals = [self._to_float(r.get(col, "")) for r in group_rows]
                nums = [v for v in vals if v is not None]
                agg_row[col] = fn(nums) if nums else None
            output_rows.append(agg_row)

        return {
            "group_by": group_col,
            "aggregation": agg_func,
            "groups": len(output_rows),
            "rows": output_rows,
        }

    def _correlate(
        self, rows: list[dict[str, str]], headers: list[str], columns: list[str] | None
    ) -> dict[str, Any]:
        cols = columns or self._get_numeric_columns(rows, headers)
        if len(cols) < 2:
            return {"error": "Need at least 2 numeric columns for correlation"}

        data: dict[str, list[float]] = {}
        for col in cols:
            data[col] = []
            for row in rows:
                v = self._to_float(row.get(col, ""))
                data[col].append(v if v is not None else float("nan"))

        matrix: dict[str, dict[str, float]] = {}
        for c1 in cols:
            matrix[c1] = {}
            for c2 in cols:
                pairs = [
                    (a, b)
                    for a, b in zip(data[c1], data[c2])
                    if not (math.isnan(a) or math.isnan(b))
                ]
                if len(pairs) < 3:
                    matrix[c1][c2] = 0.0
                    continue
                xs, ys = zip(*pairs)
                matrix[c1][c2] = round(self._pearson(list(xs), list(ys)), 4)

        return {"correlation_matrix": matrix, "columns": cols}

    def _pearson(self, x: list[float], y: list[float]) -> float:
        n = len(x)
        if n < 2:
            return 0.0
        mx = sum(x) / n
        my = sum(y) / n
        num = sum((a - mx) * (b - my) for a, b in zip(x, y))
        dx = math.sqrt(sum((a - mx) ** 2 for a in x))
        dy = math.sqrt(sum((b - my) ** 2 for b in y))
        if dx == 0 or dy == 0:
            return 0.0
        return num / (dx * dy)

    def _outliers(
        self, rows: list[dict[str, str]], headers: list[str], columns: list[str] | None
    ) -> dict[str, Any]:
        cols = columns or self._get_numeric_columns(rows, headers)
        result: dict[str, list[dict[str, Any]]] = {}

        for col in cols:
            values = [(i, self._to_float(r.get(col, ""))) for i, r in enumerate(rows)]
            nums = [(i, v) for i, v in values if v is not None]
            if len(nums) < 4:
                continue
            vals = [v for _, v in nums]
            q1 = sorted(vals)[len(vals) // 4]
            q3 = sorted(vals)[3 * len(vals) // 4]
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr

            outliers = []
            for idx, val in nums:
                if val < lower or val > upper:
                    outliers.append(
                        {"row": idx, "value": val, "bounds": [lower, upper]}
                    )
            if outliers:
                result[col] = outliers

        return {"outliers_by_column": result, "method": "IQR (1.5x)"}

    def _quality(
        self, rows: list[dict[str, str]], headers: list[str]
    ) -> dict[str, Any]:
        total = len(rows)
        col_quality: dict[str, dict[str, Any]] = {}
        for col in headers:
            values = [r.get(col, "") for r in rows]
            missing = sum(1 for v in values if not v.strip())
            unique = len(set(values))
            col_quality[col] = {
                "missing": missing,
                "missing_pct": round(missing / total * 100, 1) if total else 0,
                "unique": unique,
                "unique_pct": round(unique / total * 100, 1) if total else 0,
                "sample_values": list(set(v for v in values if v.strip()))[:5],
            }

        duplicates = total - len(
            set(tuple(r.get(h, "") for h in headers) for r in rows)
        )

        return {
            "total_rows": total,
            "total_columns": len(headers),
            "duplicate_rows": duplicates,
            "column_quality": col_quality,
        }

    def _head(
        self, rows: list[dict[str, str]], headers: list[str], limit: int
    ) -> dict[str, Any]:
        return {
            "columns": headers,
            "total_rows": len(rows),
            "showing": min(limit, len(rows)),
            "rows": rows[:limit],
        }

    def _unique(
        self, rows: list[dict[str, str]], headers: list[str], columns: list[str] | None
    ) -> dict[str, Any]:
        cols = columns or headers[:5]
        result: dict[str, list[str]] = {}
        for col in cols:
            if col in headers:
                vals = sorted(
                    set(r.get(col, "") for r in rows if r.get(col, "").strip())
                )
                result[col] = vals[:100]
        return {"unique_values": result}

    def _frequency(
        self, rows: list[dict[str, str]], headers: list[str], columns: list[str] | None
    ) -> dict[str, Any]:
        cols = columns or headers[:3]
        result: dict[str, list[dict[str, Any]]] = {}
        for col in cols:
            if col not in headers:
                continue
            counter = Counter(r.get(col, "") for r in rows)
            items = [
                {"value": val, "count": cnt, "pct": round(cnt / len(rows) * 100, 1)}
                for val, cnt in counter.most_common(50)
            ]
            result[col] = items
        return {"frequency": result}
