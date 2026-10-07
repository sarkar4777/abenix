"""Spreadsheet import for portfolio schemas: naming, types, schema generation and the endpoints."""

from __future__ import annotations

import io
import json
import re
import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from starlette.datastructures import UploadFile

from app.core import portfolio_import as pi
from app.core import portfolio_schema_check as psc
from app.routers import portfolio_schemas as router

TENANT = uuid.UUID("1234abcd-0000-0000-0000-000000000000")


# naming


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Volume (MWh)", "volume_mwh"),
        ("Price (EUR/MWh)", "price_eur_mwh"),
        ("  Trade Date ", "trade_date"),
        ("tradeDate", "trade_date"),
        ("2024 Sales", "c_2024_sales"),
        ("Prix €/MWh", "prix_mwh"),
        ("Société", "societe"),
        ("---", "column"),
        ("", "column"),
    ],
)
def test_snake_case(raw, expected):
    assert pi.snake_case(raw) == expected


def test_safe_column_name_avoids_system_reserved_and_duplicates():
    taken: set[str] = set()
    assert pi.safe_column_name("id", taken) == "source_id"
    assert pi.safe_column_name("Owner ID", taken) == "source_owner_id"
    assert pi.safe_column_name("created_at", taken) == "source_created_at"
    assert pi.safe_column_name("Order", taken) == "order_value"
    assert pi.safe_column_name("user", taken) == "user_value"
    assert pi.safe_column_name("Hub", taken) == "hub"
    assert pi.safe_column_name("hub", taken) == "hub_2"
    assert pi.safe_column_name("HUB!", taken) == "hub_3"


def test_safe_column_name_is_bounded_and_safe():
    name = pi.safe_column_name("x" * 200, set())
    assert len(name) <= pi.MAX_NAME
    assert pi.IDENT.match(name)
    taken = {name}
    second = pi.safe_column_name("x" * 200, taken)
    assert second != name and len(second) <= pi.MAX_NAME


def test_table_name_shape():
    t = pi.table_name_for(TENANT, "energy_trading_book")
    assert t == "pf_1234abcd_energy_trading_book"
    assert pi.TABLE_RE.match(t)
    assert pi.is_import_table(t, TENANT, "energy_trading_book")
    assert not pi.is_import_table(t, uuid.uuid4(), "energy_trading_book")
    assert not pi.is_import_table("contractiq_contracts", TENANT, "energy_trading_book")


def test_long_domains_are_truncated_with_a_hash():
    a = pi.table_name_for(TENANT, "a" * 80)
    b = pi.table_name_for(TENANT, "a" * 79 + "b")
    assert len(a) <= 63 and len(b) <= 63
    assert a != b
    assert pi.TABLE_RE.match(a)
    assert pi.table_name_for(TENANT, "a" * 80) == a


# types


@pytest.mark.parametrize(
    "values,expected",
    [
        (["1", "2.5", "-3", "1e3", ""], "number"),
        (["1,250", "12,000.50", "7"], "number"),
        (["007", "012"], "text"),
        (["0.5", "0"], "number"),
        (["yes", "No", "TRUE"], "boolean"),
        (["1", "0"], "number"),
        (["2026-03-31", "2026/04/01"], "date"),
        (["2026-03-31T10:00:00", "2026-03-31 11:30"], "date"),
        (["31/03/2026", "01/04/2026"], "date"),
        (["03/31/2026", "04/01/2026"], "date"),
        (["31/03/2026", "03/31/2026"], "text"),
        (["2026-02-30"], "text"),
        (["2026-11", "2026-12"], "text"),
        (["Power", "12"], "text"),
        (["", " "], "text"),
    ],
)
def test_infer_column(values, expected):
    assert pi.infer_column(values)["type"] == expected


def test_infer_date_details():
    assert pi.infer_column(["31/03/2026"])["date_order"] == "dmy"
    assert pi.infer_column(["03/31/2026"])["date_order"] == "mdy"
    assert pi.infer_column(["2026-03-31"])["date_order"] == "iso"
    assert pi.infer_column(["2026-03-31T10:00:00Z"])["has_time"] is True
    assert pi.infer_column(["2026-03-31"])["has_time"] is False


def test_convert_values_and_reasons():
    assert pi.convert("1,250.5", {"type": "number"}) == 1250.5
    assert pi.convert("", {"type": "number"}) is None
    assert pi.convert("Yes", {"type": "boolean"}) is True
    assert pi.convert("0", {"type": "boolean"}) is False
    assert pi.convert("31/03/2026", {"type": "date", "date_order": "dmy"}) == date(2026, 3, 31)
    assert pi.convert("2026-03-31T10:00:00", {"type": "date", "date_order": "iso"}) == date(2026, 3, 31)
    dt = pi.convert("2026-03-31", {"type": "date", "has_time": True})
    assert isinstance(dt, datetime) and dt.tzinfo is not None
    assert pi.convert("  hi ", {"type": "text"}) == "hi"
    with pytest.raises(ValueError, match="not a number"):
        pi.convert("abc", {"type": "number"})
    with pytest.raises(ValueError, match="yes/no"):
        pi.convert("maybe", {"type": "boolean"})
    with pytest.raises(ValueError, match="not a date"):
        pi.convert("soon", {"type": "date"})


def test_sql_types():
    assert pi.sql_type({"type": "number"}) == "double precision"
    assert pi.sql_type({"type": "date"}) == "date"
    assert pi.sql_type({"type": "date", "has_time": True}) == "timestamptz"
    assert pi.sql_type({"type": "boolean"}) == "boolean"
    assert pi.sql_type({"type": "text"}) == "text"
    assert pi.type_from_pg("timestamp with time zone") == ("date", True)
    assert pi.type_from_pg("integer") == ("number", False)
    assert pi.type_from_pg("character varying") == ("text", False)


# reading


def test_read_csv_semicolon_bom_blank_and_ragged_rows():
    data = "﻿Name;Amount\nA;1\n\n;;\nB;2;extra\nC\n".encode("utf-8")
    sheet = pi.read_sheet("x.csv", data)
    assert sheet.headers == ["Name", "Amount"]
    assert [cells for _, cells in sheet.rows] == [["A", "1"], ["C", ""]]
    assert sheet.skipped and "3 values" in sheet.skipped[0][1]
    assert sheet.skipped[0][0] == 5


def test_read_csv_cp1252():
    sheet = pi.read_sheet("x.csv", "Name,City\nZoë,Köln\n".encode("cp1252"))
    assert sheet.rows[0][1] == ["Zoë", "Köln"]


@pytest.mark.parametrize(
    "data,msg",
    [
        (b"", "empty"),
        (b"   \n", "empty"),
        (b"a,b\n", "no rows"),
        (b",,\n1,2,3\n", "column names"),
    ],
)
def test_read_csv_errors(data, msg):
    with pytest.raises(pi.SpreadsheetError, match=msg):
        pi.read_sheet("x.csv", data)


def test_size_and_row_limits(monkeypatch):
    with pytest.raises(pi.SpreadsheetError) as e:
        pi.read_sheet("x.csv", b"a\n" + b"1\n" * (pi.MAX_BYTES // 2 + 1))
    assert e.value.status == 413 and "20.0 MB" in e.value.message
    monkeypatch.setattr(pi, "MAX_ROWS", 5)
    with pytest.raises(pi.SpreadsheetError) as e:
        pi.read_sheet("x.csv", b"a\n" + b"1\n" * 6)
    assert e.value.status == 413 and "more than 5 rows" in e.value.message
    assert len(pi.read_sheet("x.csv", b"a\n" + b"1\n" * 5).rows) == 5


def test_too_many_columns():
    header = ",".join(f"c{i}" for i in range(pi.MAX_COLUMNS + 1))
    with pytest.raises(pi.SpreadsheetError, match="columns"):
        pi.read_sheet("x.csv", (header + "\n" + header + "\n").encode())


def test_unsupported_formats(monkeypatch):
    with pytest.raises(pi.SpreadsheetError, match="not supported"):
        pi.read_sheet("x.xls", b"abc")
    with pytest.raises(pi.SpreadsheetError, match="Upload a .csv"):
        pi.read_sheet("x.pdf", b"abc")
    monkeypatch.setattr(pi, "xlsx_supported", lambda: False)
    with pytest.raises(pi.SpreadsheetError, match="Save As") as e:
        pi.read_sheet("x.xlsx", b"PK...")
    assert e.value.status == 415
    assert pi.accepted_formats() == ["csv"]


def test_xlsx_when_openpyxl_is_present():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Day", "Qty", "Ok"])
    ws.append(["A", datetime(2026, 3, 31), 5, True])
    ws.append(["B", datetime(2026, 4, 1, 9, 30), 2.5, False])
    wb.create_sheet("Other")
    buf = io.BytesIO()
    wb.save(buf)
    sheet = pi.read_sheet("book.xlsx", buf.getvalue())
    assert sheet.rows[0][1] == ["A", "2026-03-31", "5", "true"]
    assert any("first sheet" in w for w in sheet.warnings)
    cols = {c["name"]: c["type"] for c in pi.preview(sheet)["columns"]}
    assert cols == {"name": "text", "day": "date", "qty": "number", "ok": "boolean"}


def test_preview_shape():
    sheet = pi.read_sheet("x.csv", b"Name,Amount,id\nA,1,7\nB,2,8\n")
    pv = pi.preview(sheet)
    assert [c["name"] for c in pv["columns"]] == ["name", "amount", "source_id"]
    assert pv["columns"][1]["type"] == "number"
    assert pv["columns"][0]["samples"] == ["A", "B"]
    assert pv["total_rows"] == 2
    assert pv["suggested_title_column"] == "name"


# plan and schema


def _sheet():
    return pi.read_sheet("x.csv", b"Deal,Amount,Closed,Note\nA,1,2026-01-02,x\nB,oops,2026-01-03,y\nC,3,,z\n")


def _plan_cols(sheet, **over):
    cols = [
        {"index": c["index"], "source": c["source"], "name": c["name"], "label": c["label"], "type": c["type"], "include": True}
        for c in pi.preview(sheet)["columns"]
    ]
    for c in cols:
        c.update(over.get(c["name"], {}))
    return cols


def test_resolve_plan_rename_untick_and_title():
    sheet = _sheet()
    cols = _plan_cols(sheet, note={"include": False}, deal={"name": "Deal Name"})
    final, title = pi.resolve_plan(sheet, cols, "Deal Name")
    assert [c["name"] for c in final] == ["deal_name", "amount", "closed"]
    assert title == "deal_name"
    assert final[1]["type"] == "text"  # "oops" makes it text in preview


def test_resolve_plan_rejects_mismatch_and_bad_types():
    sheet = _sheet()
    cols = _plan_cols(sheet)
    cols[0]["source"] = "Something else"
    with pytest.raises(pi.SpreadsheetError, match="Preview the file again"):
        pi.resolve_plan(sheet, cols, None)
    cols = _plan_cols(sheet)
    cols[0]["type"] = "money"
    with pytest.raises(pi.SpreadsheetError, match="Use one of"):
        pi.resolve_plan(sheet, cols, None)
    with pytest.raises(pi.SpreadsheetError, match="at least one"):
        pi.resolve_plan(sheet, [dict(c, include=False) for c in _plan_cols(sheet)], None)


def test_build_rows_skips_with_reasons():
    sheet = _sheet()
    final, _ = pi.resolve_plan(sheet, _plan_cols(sheet, amount={"type": "number"}), "deal")
    rows, skipped = pi.build_rows(sheet, final)
    assert len(rows) == 2
    assert skipped == [(3, '"oops" in Amount is not a number')]
    assert rows[1][2] is None


def test_generated_schema_passes_the_validator():
    sheet = pi.read_sheet(pi.SAMPLE_PATH.name, pi.sample_bytes())
    plan = router.sample_plan(sheet, "create")
    cols, title = pi.resolve_plan(sheet, plan.columns, plan.title_column)
    table = pi.table_name_for(TENANT, "energy_trading_book")
    sj = pi.build_schema_json(
        domain="energy_trading_book", label="Energy trading book", description="d",
        record_noun="trade", record_noun_plural="trades", table=table, columns=cols, title_column=title,
    )
    out, problems, refs = psc.check_structure(sj, "energy_trading_book")
    assert problems == []
    main = sj["main_table"]
    assert main["user_scope_column"] == "owner_id"
    assert main["title_column"] == "trade_ref"
    assert main["list_columns"][:2] == ["id", "trade_ref"]
    assert set(main["search_columns"]) == {"trade_ref", "commodity", "hub", "direction", "counterparty", "delivery_month", "status"}
    assert main["summary_aggregations"]["record_count"]["sql"] == "count(*)"
    assert main["summary_aggregations"]["total_volume_mwh"]["sql"] == "sum(volume_mwh)"
    assert main["summary_aggregations"]["avg_price_eur_mwh"]["sql"] == "avg(price_eur_mwh)"
    assert main["columns"]["trade_date"]["type"] == "date"
    assert main["columns"]["volume_mwh"]["label"] == "Volume (MWh)"
    assert refs[table] >= {"id", "owner_id", "created_at", "volume_mwh"}
    assert pi.schema_source_table(sj) == table


def test_merge_new_columns_is_additive():
    sj = {"main_table": {"columns": {"a": {"type": "string", "label": "Mine"}}, "list_columns": ["id", "a"]}}
    pi.merge_new_columns(sj, [{"name": "a", "label": "A", "type": "text"}, {"name": "qty", "label": "Qty", "type": "number"}])
    main = sj["main_table"]
    assert main["columns"]["a"]["label"] == "Mine"
    assert main["list_columns"] == ["id", "a", "qty"]
    assert "total_qty" in main["summary_aggregations"]


def test_validator_rejects_reserved_words():
    sj = {
        "domain": {"label": "x", "record_noun": "r", "record_noun_plural": "rs"},
        "main_table": {
            "name": "deals", "user_scope_column": "user", "title_column": "title",
            "list_columns": ["id", "order"], "columns": {"id": {}},
        },
    }
    _, problems, _ = psc.check_structure(sj, "deals")
    assert any('"user" is a reserved SQL word' in p for p in problems)
    assert any('"order" is a reserved SQL word' in p for p in problems)


def test_sample_file_is_realistic():
    sheet = pi.read_sheet(pi.SAMPLE_PATH.name, pi.sample_bytes())
    assert 30 <= len(sheet.rows) <= 60
    names = [c["name"] for c in pi.preview(sheet)["columns"]]
    assert names == [
        "trade_ref", "trade_date", "commodity", "hub", "direction", "volume_mwh",
        "price_eur_mwh", "counterparty", "delivery_month", "status",
    ]
    hubs = {cells[3] for _, cells in sheet.rows}
    assert {"TTF", "EEX DE"} <= hubs
    ttf_buy = sum(float(c[5]) for _, c in sheet.rows if c[3] == "TTF" and c[4] == "Buy")
    assert ttf_buy == 11200


# endpoints against a fake database


class Res:
    def __init__(self, rows=None, rowcount=0, scalar=None):
        self.rows = rows or []
        self.rowcount = rowcount
        self._scalar = scalar

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self.rows))


PG = {"double precision": "double precision", "date": "date", "timestamptz": "timestamp with time zone", "boolean": "boolean", "text": "text"}


class FakeDB:
    """Enough of Postgres to watch the import: tables, columns, comments, rows and schema rows."""

    def __init__(self):
        self.tables: dict[str, dict] = {}
        self.schemas: list = []
        self.sql: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.deleted: list = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.sql.append(sql)
        if "FROM portfolio_schemas" in sql:
            if "portfolio_schemas.domain_name" in sql and "portfolio_schemas.record_noun" in sql:
                return Res([s for s in self.schemas if s not in self.deleted][:1])
            return Res([(s.id, s.label, s.schema_json) for s in self.schemas if s not in self.deleted])
        if "to_regclass" in sql:
            t = self.tables.get(params["t"])
            return Res([(t is not None, t["note"] if t else None)])
        if "information_schema" in sql and "names" in (params or {}):
            names = set(params["names"])
            return Res([(n, c) for n, t in self.tables.items() if n in names for c in ["id", "owner_id", "created_at", *t["cols"]]])
        if "information_schema" in sql:
            t = self.tables[params["t"]]
            base = [("id", "uuid"), ("owner_id", "uuid"), ("created_at", "timestamp with time zone")]
            return Res(base + [(c, PG[ty]) for c, ty in t["cols"].items()])
        if "pg_class" in sql:
            return Res([(n,) for n in params["names"] if n in self.tables])
        m = re.match(r"CREATE TABLE (\w+) \((.*)\)$", sql, re.S)
        if m:
            assert m.group(1) not in self.tables
            cols = {}
            for line in m.group(2).split(",\n"):
                name, _, typ = line.strip().partition(" ")
                if name not in ("id", "owner_id", "created_at"):
                    cols[name] = typ
            self.tables[m.group(1)] = {"cols": cols, "note": None, "rows": []}
            return Res()
        if sql.startswith("CREATE INDEX"):
            return Res()
        m = re.match(r"COMMENT ON TABLE (\w+) IS '(.*)'", sql)
        if m:
            self.tables[m.group(1)]["note"] = m.group(2)
            return Res()
        m = re.match(r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+) (.+)", sql)
        if m:
            self.tables[m.group(1)]["cols"].setdefault(m.group(2), m.group(3))
            return Res()
        m = re.match(r"DELETE FROM (\w+) WHERE owner_id", sql)
        if m:
            t = self.tables[m.group(1)]
            before = len(t["rows"])
            t["rows"] = [r for r in t["rows"] if r["owner"] != params["owner"]]
            return Res(rowcount=before - len(t["rows"]))
        m = re.match(r"INSERT INTO (\w+) \(owner_id, (.*?)\) VALUES", sql)
        if m:
            names = m.group(2).split(", ")
            for p in params:
                self.tables[m.group(1)]["rows"].append(
                    {"owner": p["owner"]} | {n: p[f"c{i}"] for i, n in enumerate(names)}
                )
            return Res()
        m = re.match(r"SELECT count\(\*\) FROM (\w+) WHERE owner_id", sql)
        if m:
            return Res(scalar=sum(1 for r in self.tables[m.group(1)]["rows"] if r["owner"] == params["owner"]))
        m = re.match(r"SELECT (.*?) FROM (\w+) WHERE owner_id = :owner ORDER BY", sql)
        if m:
            names = m.group(1).split(", ")
            rows = [r for r in self.tables[m.group(2)]["rows"] if r["owner"] == params["owner"]]
            return Res([tuple(r.get(n) for n in names) for r in rows[: params["limit"]]])
        m = re.match(r"DROP TABLE IF EXISTS (\w+)", sql)
        if m:
            self.tables.pop(m.group(1), None)
            return Res()
        raise AssertionError(f"unexpected SQL: {sql[:200]}")

    def add(self, obj):
        self.schemas.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, obj):
        return None


def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT)


def _upload(data: bytes, name="deals.csv"):
    return UploadFile(file=io.BytesIO(data), filename=name)


DEALS = b"Deal,Amount,Closed\nAlpha,100,2026-01-02\nBeta,oops,2026-01-03\nGamma,300,2026-01-04\n"


def _plan(mode="create", **over):
    sheet = pi.read_sheet("x.csv", DEALS)
    cols = _plan_cols(sheet, amount={"type": "number"})
    plan = {
        "domain_name": "deals", "label": "Deals", "record_noun": "deal", "record_noun_plural": "deals",
        "title_column": "deal", "columns": cols, "mode": mode,
    } | over
    return json.dumps(plan)


def _body(res):
    return json.loads(res.body)


@pytest.mark.asyncio
async def test_import_creates_table_rows_and_schema():
    db, user = FakeDB(), _user()
    res = await router.import_spreadsheet(file=_upload(DEALS), plan=_plan(), user=user, db=db)
    assert res.status_code == 201, res.body
    data = _body(res)["data"]
    table = "pf_1234abcd_deals"
    assert data["table"] == table
    assert data["rows_imported"] == 2
    assert data["rows_skipped"] == 1
    assert data["skipped"] == [{"row": 3, "reason": '"oops" in Amount is not a number'}]
    t = db.tables[table]
    assert t["note"] == f"abenix:portfolio-import:{TENANT}"
    assert t["cols"] == {"deal": "text", "amount": "double precision", "closed": "date"}
    assert all(r["owner"] == user.id for r in t["rows"])
    assert t["rows"][0]["closed"] == date(2026, 1, 2)
    saved = db.schemas[0]
    assert saved.domain_name == "deals" and saved.created_by == user.id
    assert saved.schema_json["main_table"]["name"] == table
    assert saved.schema_json["source"] == {"kind": "spreadsheet", "table": table}
    assert data["schema"]["source"] == "spreadsheet"
    assert data["schema"]["tool_name"] == "portfolio_deals"
    assert db.commits == 1
    create = next(s for s in db.sql if s.startswith("CREATE TABLE"))
    assert "id uuid PRIMARY KEY DEFAULT gen_random_uuid()" in create
    assert "owner_id uuid NOT NULL" in create
    insert = next(s for s in db.sql if s.startswith("INSERT"))
    assert ":owner" in insert and "Alpha" not in insert


@pytest.mark.asyncio
async def test_import_create_twice_is_a_clear_conflict():
    db, user = FakeDB(), _user()
    await router.import_spreadsheet(file=_upload(DEALS), plan=_plan(), user=user, db=db)
    res = await router.import_spreadsheet(file=_upload(DEALS), plan=_plan(), user=user, db=db)
    assert res.status_code == 409
    assert "already a schema called deals" in _body(res)["error"]["message"]


@pytest.mark.asyncio
async def test_replace_only_touches_my_rows_and_append_adds_columns():
    db, me, other = FakeDB(), _user(), _user()
    await router.import_spreadsheet(file=_upload(DEALS), plan=_plan(), user=me, db=db)
    await router.import_spreadsheet(file=_upload(DEALS), plan=_plan("append"), user=other, db=db)
    rows = db.tables["pf_1234abcd_deals"]["rows"]
    assert len(rows) == 4

    res = await router.import_spreadsheet(file=_upload(b"Deal,Amount\nDelta,5\n"), plan=json.dumps({
        "domain_name": "deals", "label": "Deals", "mode": "replace", "title_column": "deal",
        "columns": [{"index": 0, "source": "Deal", "name": "deal", "type": "text"}, {"index": 1, "source": "Amount", "name": "amount", "type": "text"}],
    }), user=me, db=db)
    assert res.status_code == 200, res.body
    data = _body(res)["data"]
    assert data["rows_replaced"] == 2 and data["rows_imported"] == 1
    assert any("stored as number" in n for n in data["notes"])
    rows = db.tables["pf_1234abcd_deals"]["rows"]
    assert sum(r["owner"] == me.id for r in rows) == 1
    assert sum(r["owner"] == other.id for r in rows) == 2
    assert [r["amount"] for r in rows if r["owner"] == me.id] == [5.0]

    res = await router.import_spreadsheet(file=_upload(b"Deal,Region\nEcho,North\n"), plan=json.dumps({
        "domain_name": "deals", "label": "Deals", "mode": "append",
        "columns": [{"index": 0, "name": "deal", "type": "text"}, {"index": 1, "name": "region", "type": "text"}],
    }), user=me, db=db)
    assert res.status_code == 200, res.body
    assert "region" in db.tables["pf_1234abcd_deals"]["cols"]
    sj = db.schemas[0].schema_json["main_table"]
    assert "region" in sj["columns"] and "region" in sj["search_columns"]


@pytest.mark.asyncio
async def test_nothing_importable_changes_nothing():
    db, user = FakeDB(), _user()
    plan = json.loads(_plan())
    for c in plan["columns"]:
        if c["name"] == "deal":
            c["type"] = "number"
    res = await router.import_spreadsheet(file=_upload(DEALS), plan=json.dumps(plan), user=user, db=db)
    assert res.status_code == 422
    err = _body(res)["error"]
    assert "None of the 3 rows" in err["message"]
    assert err["details"]["rows_skipped"] == 3
    assert db.tables == {} and db.schemas == []


@pytest.mark.asyncio
async def test_foreign_table_with_the_same_name_is_refused():
    db, user = FakeDB(), _user()
    db.tables["pf_1234abcd_deals"] = {"cols": {}, "note": None, "rows": []}
    res = await router.import_spreadsheet(file=_upload(DEALS), plan=_plan(), user=user, db=db)
    assert res.status_code == 409
    assert "not made by a spreadsheet import" in _body(res)["error"]["message"]


@pytest.mark.asyncio
async def test_append_to_a_hand_written_schema_is_refused():
    db, user = FakeDB(), _user()
    db.schemas.append(SimpleNamespace(id=uuid.uuid4(), label="Deals", domain_name="deals", schema_json={"main_table": {"name": "deals"}}))
    res = await router.import_spreadsheet(file=_upload(DEALS), plan=_plan("append"), user=user, db=db)
    assert res.status_code == 409
    assert "not created from a spreadsheet" in _body(res)["error"]["message"]


@pytest.mark.asyncio
async def test_bad_plan_gives_plain_messages():
    db, user = FakeDB(), _user()
    res = await router.import_spreadsheet(file=_upload(DEALS), plan=_plan(domain_name="Bad Name", label=""), user=user, db=db)
    assert res.status_code == 422
    msg = _body(res)["error"]["message"]
    assert "Domain name must start with a letter" in msg and "Give the schema a name" in msg
    res = await router.import_spreadsheet(file=_upload(DEALS), plan="{not json", user=user, db=db)
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_failed_sql_rolls_back_and_says_so():
    db, user = FakeDB(), _user()
    real = db.execute

    async def boom(stmt, params=None):
        if str(stmt).startswith("INSERT"):
            raise RuntimeError("disk full\nmore detail")
        return await real(stmt, params)

    db.execute = boom
    res = await router.import_spreadsheet(file=_upload(DEALS), plan=_plan(), user=user, db=db)
    assert res.status_code == 500
    assert "nothing was saved" in _body(res)["error"]["message"]
    assert "disk full" in _body(res)["error"]["message"]
    assert db.rollbacks == 1 and db.commits == 0


@pytest.mark.asyncio
async def test_preview_endpoint_and_existing_columns():
    db, user = FakeDB(), _user()
    res = await router.import_preview(file=_upload(DEALS), domain_name=None, user=user, db=db)
    data = _body(res)["data"]
    assert [c["type"] for c in data["columns"]] == ["text", "text", "date"]
    assert data["existing_columns"] is None
    await router.import_spreadsheet(file=_upload(DEALS), plan=_plan(), user=user, db=db)
    res = await router.import_preview(file=_upload(DEALS), domain_name="deals", user=user, db=db)
    data = _body(res)["data"]
    assert {c["name"] for c in data["existing_columns"]} == {"deal", "amount", "closed"}
    assert data["columns"][1]["type"] == "number"
    res = await router.import_preview(file=_upload(b"", "x.csv"), domain_name=None, user=user, db=db)
    assert res.status_code == 422 and "empty" in _body(res)["error"]["message"]


@pytest.mark.asyncio
async def test_sample_creates_then_refreshes_my_rows():
    db, user = FakeDB(), _user()
    res = await router.import_sample(user=user, db=db)
    assert res.status_code == 201, res.body
    data = _body(res)["data"]
    assert data["rows_imported"] == 40 and data["rows_skipped"] == 0 and data["sample"] is True
    table = "pf_1234abcd_energy_trading_book"
    rows = db.tables[table]["rows"]
    assert sum(r["volume_mwh"] for r in rows if r["hub"] == "TTF" and r["direction"] == "Buy") == 11200
    assert data["schema"]["tool_name"] == "portfolio_energy_trading_book"
    assert data["schema"]["label"] == "Energy trading book"

    res = await router.import_sample(user=user, db=db)
    assert res.status_code == 200
    data = _body(res)["data"]
    assert data["mode"] == "replace" and data["rows_replaced"] == 40
    assert len(db.tables[table]["rows"]) == 40


@pytest.mark.asyncio
async def test_list_counts_and_rows_endpoint():
    db, user = FakeDB(), _user()
    await router.import_sample(user=user, db=db)
    schema = db.schemas[0]
    schema.is_active = True
    schema.description = None
    schema.created_at = schema.updated_at = None
    res = await router.list_my_rows(schema_id=schema.id, user=user, db=db, limit=3)
    data = _body(res)["data"]
    assert data["total"] == 40 and len(data["rows"]) == 3
    assert data["columns"][0] == {"name": "created_at", "label": "Created at"}
    assert {"name": "volume_mwh", "label": "Volume (MWh)"} in data["columns"]
    counts = await router._my_row_counts(db, user, [schema])
    assert counts == {schema.id: 40}
    assert await router._my_row_counts(db, _user(), [schema]) == {schema.id: 0}


@pytest.mark.asyncio
async def test_delete_can_drop_the_import_table():
    db, user = FakeDB(), _user()
    await router.import_sample(user=user, db=db)
    schema = db.schemas[0]
    res = await router.delete_schema(schema_id=schema.id, force=True, user=user, db=db, drop_table=True)
    assert res.status_code == 200
    assert _body(res)["data"] == {"deleted": True, "dropped_table": "pf_1234abcd_energy_trading_book"}
    assert db.tables == {}


@pytest.mark.asyncio
async def test_delete_keeps_the_table_unless_asked():
    db, user = FakeDB(), _user()
    await router.import_sample(user=user, db=db)
    res = await router.delete_schema(schema_id=db.schemas[0].id, force=True, user=user, db=db)
    assert _body(res)["data"]["dropped_table"] is None
    assert "pf_1234abcd_energy_trading_book" in db.tables


@pytest.mark.asyncio
async def test_delete_never_drops_a_table_it_did_not_make():
    db, user = FakeDB(), _user()
    db.tables["pf_1234abcd_deals"] = {"cols": {}, "note": "someone else", "rows": []}
    sj = {"main_table": {"name": "pf_1234abcd_deals"}, "source": {"kind": "spreadsheet", "table": "pf_1234abcd_deals"}}
    db.schemas.append(SimpleNamespace(id=uuid.uuid4(), label="Deals", domain_name="deals", schema_json=sj))
    res = await router.delete_schema(schema_id=db.schemas[0].id, force=True, user=user, db=db, drop_table=True)
    assert res.status_code == 400
    assert "pf_1234abcd_deals" in db.tables and db.deleted == []

    sj2 = {"main_table": {"name": "users"}, "source": {"kind": "spreadsheet", "table": "users"}}
    db.schemas[0] = SimpleNamespace(id=uuid.uuid4(), label="Users", domain_name="users", schema_json=sj2)
    res = await router.delete_schema(schema_id=db.schemas[0].id, force=True, user=user, db=db, drop_table=True)
    assert res.status_code == 400
    assert not any(s.startswith("DROP") for s in db.sql)


@pytest.mark.asyncio
async def test_delete_refuses_to_drop_a_table_another_schema_reads():
    db, user = FakeDB(), _user()
    await router.import_sample(user=user, db=db)
    table = "pf_1234abcd_energy_trading_book"
    db.schemas.append(SimpleNamespace(id=uuid.uuid4(), label="Copy", domain_name="copy", schema_json={"main_table": {"name": table}}))
    res = await router.delete_schema(schema_id=db.schemas[0].id, force=True, user=user, db=db, drop_table=True)
    assert res.status_code == 409
    assert "Copy" in _body(res)["error"]["message"]
    assert table in db.tables


@pytest.mark.asyncio
async def test_capabilities_reflect_openpyxl(monkeypatch):
    monkeypatch.setattr(pi, "xlsx_supported", lambda: False)
    res = await router.import_capabilities(user=_user())
    data = _body(res)["data"]
    assert data["formats"] == ["csv"]
    assert data["max_rows"] == pi.MAX_ROWS and data["max_bytes"] == pi.MAX_BYTES


@pytest.mark.asyncio
async def test_a_table_marked_for_another_tenant_is_not_ours():
    db, user = FakeDB(), _user()
    db.tables["pf_1234abcd_deals"] = {"cols": {}, "note": f"abenix:portfolio-import:{uuid.uuid4()}", "rows": []}
    res = await router.import_spreadsheet(file=_upload(DEALS), plan=_plan(), user=user, db=db)
    assert res.status_code == 409
    assert db.tables["pf_1234abcd_deals"]["rows"] == []
