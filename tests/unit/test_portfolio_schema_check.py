"""Portfolio schema validation: structure, safe identifiers and the table check."""

from __future__ import annotations

import copy
import json
import uuid
from types import SimpleNamespace

import pytest

from app.core import portfolio_schema_check as psc
from app.routers import portfolio_schemas as router


def _good() -> dict:
    return {
        "domain": {
            "name": "whatever",
            "label": "Deals",
            "record_noun": "deal",
            "record_noun_plural": "deals",
        },
        "main_table": {
            "name": "deals",
            "user_scope_column": "owner_id",
            "title_column": "title",
            "list_columns": ["id", "title"],
            "columns": {"id": {"type": "uuid"}, "title": {"type": "string"}},
            "search_columns": ["title"],
            "summary_aggregations": {
                "total": {"sql": "count(*)", "label": "Total"},
                "value": {"sql": "sum(amount)", "label": "Value"},
            },
        },
        "related_tables": [
            {
                "name": "deal_notes",
                "label": "Notes",
                "foreign_key": "deal_id",
                "columns": {"body": {"type": "text"}},
                "order_by": "noted_at DESC",
            }
        ],
    }


DB_COLUMNS = {
    "deals": {"id", "owner_id", "title", "amount", "created_at"},
    "deal_notes": {"deal_id", "body", "noted_at"},
}


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class FakeDB:
    """Answers the information_schema query from a dict, everything else from a queue."""

    def __init__(self, columns=None, queue=None, fail=False):
        self.columns = columns if columns is not None else DB_COLUMNS
        self.queue = list(queue or [])
        self.fail = fail
        self.info_calls = 0
        self.added: list = []
        self.deleted: list = []
        self.committed = False

    async def execute(self, stmt, params=None):
        if "information_schema" in str(stmt):
            self.info_calls += 1
            if self.fail:
                raise RuntimeError("boom")
            names = set(params["names"])
            return FakeResult(
                [(t, c) for t, cols in self.columns.items() if t in names for c in sorted(cols)]
            )
        return self.queue.pop(0) if self.queue else FakeResult([])

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        return None


def _problems(schema, domain="deals"):
    _, problems, _ = psc.check_structure(schema, domain)
    return problems


def test_good_schema_has_no_structure_problems():
    schema, problems, refs = psc.check_structure(_good(), "deals")
    assert problems == []
    assert schema["domain"]["name"] == "deals"
    assert refs["deals"] >= {"id", "owner_id", "title", "amount", "created_at"}
    assert refs["deal_notes"] == {"deal_id", "body", "noted_at"}


def test_input_is_not_mutated():
    original = _good()
    before = copy.deepcopy(original)
    psc.check_structure(original, "deals")
    assert original == before


def test_empty_object_lists_every_missing_piece():
    problems = _problems({})
    joined = " | ".join(problems)
    assert "domain.label" in joined
    assert "domain.record_noun" in joined
    assert "main_table is required" in joined


def test_domain_filled_from_request_fields():
    schema = _good()
    del schema["domain"]
    out, problems, _ = psc.check_structure(
        schema, "deals", label="Deals", record_noun="deal", record_noun_plural="deals"
    )
    assert problems == []
    assert out["domain"] == {
        "name": "deals",
        "label": "Deals",
        "record_noun": "deal",
        "record_noun_plural": "deals",
    }


def test_not_an_object():
    assert _problems([1, 2]) == ["Schema JSON must be an object"]


@pytest.mark.parametrize(
    "path,value",
    [
        (("main_table", "name"), "deals; DROP TABLE users"),
        (("main_table", "name"), "Deals"),
        (("main_table", "user_scope_column"), "owner_id--"),
        (("main_table", "title_column"), "1title"),
    ],
)
def test_unsafe_identifiers_rejected(path, value):
    schema = _good()
    schema[path[0]][path[1]] = value
    problems = _problems(schema)
    assert any(path[1] in p and json.dumps(value) in p for p in problems), problems


def test_unsafe_column_keys_and_lists_rejected():
    schema = _good()
    schema["main_table"]["columns"]["x y"] = {"type": "string"}
    schema["main_table"]["list_columns"].append("id) OR 1=1")
    schema["related_tables"][0]["foreign_key"] = "deal_id;"
    problems = _problems(schema)
    assert len(problems) == 3


def test_list_columns_and_columns_required():
    schema = _good()
    schema["main_table"]["list_columns"] = []
    schema["main_table"]["columns"] = {}
    problems = _problems(schema)
    assert any("list_columns" in p for p in problems)
    assert any("main_table.columns" in p for p in problems)


def test_aggregation_sql_whitelist():
    schema = _good()
    schema["main_table"]["summary_aggregations"]["bad"] = {
        "sql": "(select password from users limit 1)",
        "label": "x",
    }
    problems = _problems(schema)
    assert len(problems) == 1 and "summary_aggregations.bad.sql" in problems[0]


def test_aggregation_column_is_referenced():
    _, _, refs = psc.check_structure(_good(), "deals")
    assert "amount" in refs["deals"]


def test_order_by_direction_and_shape():
    schema = _good()
    schema["related_tables"][0]["order_by"] = "noted_at DESC, 1"
    problems = _problems(schema)
    assert any("order_by" in p for p in problems)
    schema["related_tables"][0]["order_by"] = "noted_at sideways"
    assert any("ASC or DESC" in p for p in _problems(schema))


def test_related_needs_label_fk_and_unique_labels():
    schema = _good()
    schema["related_tables"].append(dict(schema["related_tables"][0]))
    schema["related_tables"].append({"name": "x", "columns": {"a": {}}})
    problems = _problems(schema)
    assert any("used twice" in p for p in problems)
    assert any("related_tables[2].label" in p for p in problems)
    assert any("related_tables[2].foreign_key" in p for p in problems)


def test_kv_store_requires_key_and_value_columns():
    schema = _good()
    schema["related_tables"][0]["is_kv_store"] = True
    problems = _problems(schema)
    assert any("key_column" in p for p in problems)
    assert any("value_column" in p for p in problems)


@pytest.mark.asyncio
async def test_table_check_passes_when_everything_exists():
    db = FakeDB()
    schema, problems = await psc.validate_portfolio_schema(db, _good(), "deals")
    assert problems == []
    assert db.info_calls == 1


@pytest.mark.asyncio
async def test_table_check_reports_missing_table_and_columns():
    db = FakeDB(columns={"deals": {"id", "owner_id"}})
    _, problems = await psc.validate_portfolio_schema(db, _good(), "deals")
    assert "Table deal_notes does not exist in the platform database" in problems
    missing = next(p for p in problems if p.startswith("Table deals has no column"))
    assert "title" in missing and "amount" in missing and "created_at" in missing


@pytest.mark.asyncio
async def test_table_check_skipped_without_valid_tables():
    db = FakeDB()
    _, problems = await psc.validate_portfolio_schema(db, {}, "deals")
    assert problems
    assert db.info_calls == 0


@pytest.mark.asyncio
async def test_table_check_failure_is_a_problem_not_a_crash():
    db = FakeDB(fail=True)
    _, problems = await psc.validate_portfolio_schema(db, _good(), "deals")
    assert any("Could not check the tables" in p for p in problems)


def test_shipped_template_is_structurally_valid():
    tpl = psc.load_template("energy_contracts")
    _, problems, refs = psc.check_structure(tpl["schema_json"], "energy_contracts")
    assert problems == []
    assert "contractiq_contracts" in refs


def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_create_returns_422_with_problem_list():
    db = FakeDB(columns={}, queue=[FakeResult([])])
    body = router.CreateSchemaRequest(domain_name="deals", label="Deals", schema_json=_good())
    res = await router.create_schema(body=body, user=_user(), db=db)
    assert res.status_code == 422
    payload = json.loads(res.body)["error"]
    assert payload["error_code"] == "INVALID_PORTFOLIO_SCHEMA"
    assert any("does not exist" in p for p in payload["details"]["problems"])
    assert db.added == []


@pytest.mark.asyncio
async def test_create_saves_with_domain_name_forced():
    db = FakeDB(queue=[FakeResult([])])
    schema = _good()
    schema["domain"]["name"] = "something_else"
    body = router.CreateSchemaRequest(domain_name="deals", label="  Deals  ", schema_json=schema)
    res = await router.create_schema(body=body, user=_user(), db=db)
    assert res.status_code == 201
    saved = db.added[0]
    assert saved.schema_json["domain"]["name"] == "deals"
    assert saved.label == "Deals"


@pytest.mark.asyncio
async def test_update_validates_schema_json():
    row = SimpleNamespace(
        id=uuid.uuid4(), domain_name="deals", label="Deals", description=None,
        record_noun="deal", record_noun_plural="deals", schema_json=_good(),
        is_active=True, created_at=None, updated_at=None,
    )
    db = FakeDB(queue=[FakeResult([row])])
    body = router.UpdateSchemaRequest(schema_json={"main_table": {"name": "x;"}})
    res = await router.update_schema(schema_id=row.id, body=body, user=_user(), db=db)
    assert res.status_code == 422
    assert not db.committed


@pytest.mark.asyncio
async def test_delete_refuses_when_agents_use_the_tool():
    row = SimpleNamespace(id=uuid.uuid4(), domain_name="deals")
    agent = SimpleNamespace(id=uuid.uuid4(), name="Deal Bot", slug="deal-bot")
    db = FakeDB(queue=[FakeResult([row]), FakeResult([agent])])
    res = await router.delete_schema(schema_id=row.id, force=False, user=_user(), db=db)
    assert res.status_code == 409
    payload = json.loads(res.body)["error"]
    assert payload["details"]["agents"][0]["name"] == "Deal Bot"
    assert "portfolio_deals" in payload["message"]
    assert db.deleted == []


@pytest.mark.asyncio
async def test_delete_with_force_skips_the_agent_check():
    row = SimpleNamespace(id=uuid.uuid4(), domain_name="deals")
    db = FakeDB(queue=[FakeResult([row])])
    res = await router.delete_schema(schema_id=row.id, force=True, user=_user(), db=db)
    assert res.status_code == 200
    assert db.deleted == [row]


@pytest.mark.asyncio
async def test_templates_say_they_need_own_tables():
    res = await router.list_templates()
    data = json.loads(res.body)["data"]
    ids = {t["id"] for t in data}
    assert {"real_estate", "ma_documents", "energy_contracts"} <= ids
    for t in data:
        assert t["requires_own_tables"] is True
        assert "before saving" in t["description"] or "contractiq_" in t["description"]
