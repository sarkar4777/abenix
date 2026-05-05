"""Unit tests for the connector framework.

These tests cover the pure-Python pieces — preset loader and template
substitution — without hitting Postgres or any HTTP endpoint.
"""

from __future__ import annotations

import pytest


def test_presets_load_all_yaml_files() -> None:
    from app.core.connector_presets import load_presets, reset_cache

    reset_cache()
    presets = load_presets()
    expected_keys = {
        "cmms_sap_pm",
        "cmms_servicenow",
        "cmms_maximo",
        "hris_workday",
        "telematics_sensitech",
        "telematics_carrier_lynx",
        "weather_dtn",
        "cost_data_bnef",
    }
    assert expected_keys.issubset(presets.keys()), (
        f"missing presets: {expected_keys - presets.keys()}"
    )


def test_sap_preset_has_four_required_operations() -> None:
    from app.core.connector_presets import get_preset

    preset = get_preset("cmms_sap_pm")
    assert preset is not None
    ops = preset.get("operations") or {}
    assert {"create_work_order", "update_status", "attach_photo", "query_wos"}.issubset(
        ops.keys()
    )
    cwo = ops["create_work_order"]
    assert cwo["method"] == "POST"
    assert "MaintenanceOrderType" in cwo["args"]


def test_workday_get_certifications_has_path_param() -> None:
    from app.core.connector_presets import get_preset

    preset = get_preset("hris_workday")
    assert preset is not None
    op = preset["operations"]["get_certifications"]
    assert "{worker_id}" in op["path"]


def test_dtn_get_forecast_args_shape() -> None:
    from app.core.connector_presets import get_preset

    preset = get_preset("weather_dtn")
    op = preset["operations"]["get_forecast"]
    for required_arg in ("lat", "lon", "hours"):
        assert required_arg in op["args"]


def test_template_substitution_recursive_dict() -> None:
    from engine.tools.connector_call import _format_template

    template = {
        "MaintenanceOrderType": "{order_type}",
        "MaintenanceOrderDesc": "{description}",
        "Empty": "{not_provided}",
    }
    rendered = _format_template(
        template,
        {"order_type": "PM01", "description": "Repair pump"},
    )
    assert rendered == {
        "MaintenanceOrderType": "PM01",
        "MaintenanceOrderDesc": "Repair pump",
    }


def test_template_substitution_path_string() -> None:
    from engine.tools.connector_call import _format_template

    rendered = _format_template(
        "/MaintenanceOrder('{order_id}')/SetStatus",
        {"order_id": "WO-1234"},
    )
    assert rendered == "/MaintenanceOrder('WO-1234')/SetStatus"


def test_connector_kind_enum_accepts_all_preset_kinds() -> None:
    from app.core.connector_presets import load_presets, reset_cache
    from models.connector import ConnectorKind

    reset_cache()
    for preset in load_presets().values():
        kind = preset.get("kind")
        # Every preset kind must round-trip through the enum
        assert ConnectorKind(kind), f"preset {preset.get('key')} has unknown kind {kind}"


def test_list_presets_summary_contains_operation_lists() -> None:
    from app.core.connector_presets import list_presets_summary, reset_cache

    reset_cache()
    summary = list_presets_summary()
    sap = next(s for s in summary if s["key"] == "cmms_sap_pm")
    assert "create_work_order" in sap["operations"]
    assert sap["kind"] == "cmms"
    assert sap["auth_type"] == "oauth2"


def test_idempotency_model_table_name() -> None:
    from models.idempotency import ExecutionIdempotency

    assert ExecutionIdempotency.__tablename__ == "execution_idempotency"


def test_dead_letter_model_has_replay_count_default() -> None:
    from models.dead_letter import DeadLetterExecution

    # SQLAlchemy column default
    col = DeadLetterExecution.__table__.c.replay_count
    assert col.default.arg == 0


@pytest.mark.parametrize(
    "key,expected_op",
    [
        ("cmms_servicenow", "create_work_order"),
        ("cmms_maximo", "query_wos"),
        ("telematics_sensitech", "list_loggers"),
        ("telematics_carrier_lynx", "get_temperature_log"),
        ("cost_data_bnef", "get_offshore_wind_capex_per_mw"),
    ],
)
def test_each_preset_exposes_its_signature_operation(key: str, expected_op: str) -> None:
    from app.core.connector_presets import get_preset

    preset = get_preset(key)
    assert preset is not None, f"missing preset {key}"
    assert expected_op in (preset.get("operations") or {})
