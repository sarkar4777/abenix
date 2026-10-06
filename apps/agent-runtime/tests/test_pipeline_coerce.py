from engine.pipeline import _coerce_to_schema

SCHEMA = {
    "properties": {
        "prices": {"type": "array", "items": {"type": "number"}},
        "spot": {"type": "number"},
        "tenor_months": {"type": "integer"},
        "flag": {"type": "boolean"},
        "params": {"type": "object"},
        "label": {"type": "string"},
    }
}


def test_text_from_templates_takes_the_declared_types():
    out = _coerce_to_schema(
        {
            "prices": "33.8, 34.6, 35",
            "spot": "36",
            "tenor_months": "6",
            "flag": "true",
            "params": '{"a": 1}',
            "label": "42",
        },
        SCHEMA,
    )
    assert out["prices"] == [33.8, 34.6, 35.0]
    assert out["spot"] == 36.0
    assert out["tenor_months"] == 6 and isinstance(out["tenor_months"], int)
    assert out["flag"] is True
    assert out["params"] == {"a": 1}
    assert out["label"] == "42"


def test_json_list_text_and_typed_values_pass():
    out = _coerce_to_schema({"prices": "[1, 2.5]", "spot": 3.0}, SCHEMA)
    assert out["prices"] == [1, 2.5]
    assert out["spot"] == 3.0


def test_text_that_does_not_convert_is_left_for_the_tool():
    out = _coerce_to_schema(
        {
            "spot": "front month",
            "tenor_months": "6.5",
            "prices": "{{x.y}}",
            "extra": "1",
        },
        SCHEMA,
    )
    assert out["spot"] == "front month"
    assert out["tenor_months"] == "6.5"
    assert out["prices"] == "{{x.y}}"
    assert out["extra"] == "1"
