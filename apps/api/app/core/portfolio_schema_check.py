"""Checks a portfolio schema before it is saved, so the runtime tool never sees a broken one."""

from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.portfolio_import import SQL_RESERVED

logger = logging.getLogger(__name__)

IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
# summary_aggregations sql is spliced into SELECT, so only plain aggregates pass
AGG_SQL = re.compile(
    r"^\s*(count|sum|avg|min|max)\s*\(\s*(\*|(?:distinct\s+)?([a-z_][a-z0-9_]*))\s*\)\s*$",
    re.IGNORECASE,
)
ORDER_DIRECTIONS = {"asc", "desc"}

TEMPLATES_DIR = Path(__file__).resolve().parent / "portfolio_templates"


def load_template(template_id: str) -> dict:
    path = TEMPLATES_DIR / f"{template_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _ident(value: Any) -> bool:
    return isinstance(value, str) and bool(IDENT.match(value))


def _bad_ident(where: str, value: Any) -> str:
    return (
        f"{where} must be a lowercase identifier (letters, digits, underscores, "
        f"not starting with a digit), got {json.dumps(value)}"
    )


def _check_ident(problems: list[str], where: str, value: Any) -> bool:
    if not _ident(value):
        problems.append(_bad_ident(where, value))
        return False
    if value in SQL_RESERVED:
        problems.append(
            f"{where} {json.dumps(value)} is a reserved SQL word, rename the column or table"
        )
        return False
    return True


def _check_ident_list(
    problems: list[str], where: str, value: Any, *, required: bool
) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or (required and not value):
        problems.append(f"{where} must be a non-empty list of column names")
        return []
    good = []
    for i, item in enumerate(value):
        if _check_ident(problems, f"{where}[{i}]", item):
            good.append(item)
    return good


def _check_columns(problems: list[str], where: str, value: Any) -> list[str]:
    if not isinstance(value, dict) or not value:
        problems.append(
            f"{where} must be a non-empty object of column name to settings"
        )
        return []
    good = []
    for name, cfg in value.items():
        if not _check_ident(problems, f"{where} key", name):
            continue
        if not isinstance(cfg, dict):
            problems.append(
                f'{where}.{name} must be an object like {{"type": "string", "label": "..."}}'
            )
            continue
        good.append(name)
    return good


def _order_column(order_by: str) -> tuple[str, str | None]:
    parts = order_by.split()
    if not parts:
        return "", None
    if len(parts) > 2 or (len(parts) == 2 and parts[1].lower() not in ORDER_DIRECTIONS):
        return parts[0], "must be a column name optionally followed by ASC or DESC"
    return parts[0], None


def check_structure(
    schema_json: Any,
    domain_name: str,
    *,
    label: str | None = None,
    record_noun: str | None = None,
    record_noun_plural: str | None = None,
) -> tuple[dict, list[str], dict[str, set[str]]]:
    """Return (normalised schema, problems, {table: columns the tool will query})."""
    problems: list[str] = []
    refs: dict[str, set[str]] = {}

    if not isinstance(schema_json, dict):
        return {}, ["Schema JSON must be an object"], refs
    schema = copy.deepcopy(schema_json)

    domain = schema.get("domain")
    if domain is None:
        domain = {}
        schema["domain"] = domain
    if not isinstance(domain, dict):
        problems.append("domain must be an object")
    else:
        domain["name"] = domain_name
        for key, fallback in (
            ("label", label),
            ("record_noun", record_noun),
            ("record_noun_plural", record_noun_plural),
        ):
            if not domain.get(key) and fallback:
                domain[key] = fallback
            val = domain.get(key)
            if not isinstance(val, str) or not val.strip():
                problems.append(f"domain.{key} is required and must be text")

    main = schema.get("main_table")
    if not isinstance(main, dict):
        problems.append("main_table is required and must be an object")
    else:
        mt = "main_table"
        table = main.get("name")
        table_ok = _check_ident(problems, f"{mt}.name", table)
        cols: set[str] = {"id"}
        for key in ("user_scope_column", "title_column"):
            if key not in main:
                problems.append(f"{mt}.{key} is required")
            elif _check_ident(problems, f"{mt}.{key}", main[key]):
                cols.add(main[key])
        for key in ("created_at_column", "type_column"):
            if main.get(key) not in (None, ""):
                if _check_ident(problems, f"{mt}.{key}", main[key]):
                    cols.add(main[key])
        cols.update(
            _check_ident_list(
                problems, f"{mt}.list_columns", main.get("list_columns"), required=True
            )
        )
        cols.update(_check_columns(problems, f"{mt}.columns", main.get("columns")))
        cols.update(
            _check_ident_list(
                problems,
                f"{mt}.search_columns",
                main.get("search_columns"),
                required=False,
            )
        )
        if main.get("created_at_column") in (None, ""):
            cols.add("created_at")

        aggs = main.get("summary_aggregations")
        if aggs is not None:
            if not isinstance(aggs, dict):
                problems.append(f"{mt}.summary_aggregations must be an object")
            else:
                for key, cfg in aggs.items():
                    where = f"{mt}.summary_aggregations.{key}"
                    _check_ident(problems, f"{mt}.summary_aggregations key", key)
                    if not isinstance(cfg, dict):
                        problems.append(f"{where} must be an object with sql and label")
                        continue
                    if (
                        not isinstance(cfg.get("label"), str)
                        or not cfg["label"].strip()
                    ):
                        problems.append(f"{where}.label is required")
                    m = (
                        AGG_SQL.match(cfg.get("sql") or "")
                        if isinstance(cfg.get("sql"), str)
                        else None
                    )
                    if not m:
                        problems.append(
                            f"{where}.sql must be a single count/sum/avg/min/max over one column "
                            f"or count(*), got {json.dumps(cfg.get('sql'))}"
                        )
                    elif m.group(3):
                        cols.add(m.group(3).lower())
        if table_ok:
            refs.setdefault(table, set()).update(cols)

    related = schema.get("related_tables", [])
    if related is None:
        schema["related_tables"] = related = []
    if not isinstance(related, list):
        problems.append("related_tables must be a list")
    else:
        labels: set[str] = set()
        for i, rel in enumerate(related):
            rt = f"related_tables[{i}]"
            if not isinstance(rel, dict):
                problems.append(f"{rt} must be an object")
                continue
            table = rel.get("name")
            table_ok = _check_ident(problems, f"{rt}.name", table)
            cols = set()
            lbl = rel.get("label")
            if not isinstance(lbl, str) or not lbl.strip():
                problems.append(f"{rt}.label is required")
            elif lbl in labels:
                problems.append(
                    f"{rt}.label {json.dumps(lbl)} is used twice, labels must be unique"
                )
            else:
                labels.add(lbl)
            if "foreign_key" not in rel:
                problems.append(f"{rt}.foreign_key is required")
            elif _check_ident(problems, f"{rt}.foreign_key", rel["foreign_key"]):
                cols.add(rel["foreign_key"])
            cols.update(_check_columns(problems, f"{rt}.columns", rel.get("columns")))
            cols.update(
                _check_ident_list(
                    problems,
                    f"{rt}.searchable_columns",
                    rel.get("searchable_columns"),
                    required=False,
                )
            )
            order_by = rel.get("order_by")
            if order_by not in (None, ""):
                if not isinstance(order_by, str):
                    problems.append(
                        f'{rt}.order_by must be text like "col" or "col DESC"'
                    )
                else:
                    col, why = _order_column(order_by)
                    if why:
                        problems.append(
                            f"{rt}.order_by {why}, got {json.dumps(order_by)}"
                        )
                    elif _check_ident(problems, f"{rt}.order_by column", col):
                        cols.add(col)
            if rel.get("type_column") not in (None, ""):
                if _check_ident(problems, f"{rt}.type_column", rel["type_column"]):
                    cols.add(rel["type_column"])
            if rel.get("is_kv_store"):
                for key in ("key_column", "value_column"):
                    if key not in rel:
                        problems.append(
                            f"{rt}.{key} is required when is_kv_store is true"
                        )
                    elif _check_ident(problems, f"{rt}.{key}", rel[key]):
                        cols.add(rel[key])
                section = rel.get("section_column") or "section"
                if _check_ident(problems, f"{rt}.section_column", section):
                    cols.add(section)
                if rel.get("confidence_column") not in (None, ""):
                    if _check_ident(
                        problems, f"{rt}.confidence_column", rel["confidence_column"]
                    ):
                        cols.add(rel["confidence_column"])
            if table_ok:
                refs.setdefault(table, set()).update(cols)

    return schema, problems, refs


async def check_tables(db: Any, refs: dict[str, set[str]]) -> list[str]:
    """Confirm every referenced table and column exists in the platform database."""
    if not refs:
        return []
    try:
        result = await db.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = ANY(current_schemas(false)) "
                "AND table_name = ANY(:names)"
            ),
            {"names": sorted(refs)},
        )
        rows = result.all()
    except Exception as e:
        logger.warning("portfolio schema table check failed: %s", e)
        return [f"Could not check the tables in the database: {e}"]

    found: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        found.setdefault(table_name, set()).add(column_name)

    problems = []
    for table in sorted(refs):
        if table not in found:
            problems.append(f"Table {table} does not exist in the platform database")
            continue
        missing = sorted(refs[table] - found[table])
        if missing:
            problems.append(f"Table {table} has no column(s): {', '.join(missing)}")
    return problems


async def validate_portfolio_schema(
    db: Any,
    schema_json: Any,
    domain_name: str,
    **fallbacks: str | None,
) -> tuple[dict, list[str]]:
    schema, problems, refs = check_structure(schema_json, domain_name, **fallbacks)
    problems.extend(await check_tables(db, refs))
    return schema, problems
