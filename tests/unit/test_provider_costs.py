from __future__ import annotations

from types import SimpleNamespace

from models.execution import provider_cost_values, provider_of, set_provider_costs


def test_provider_of_reads_common_model_ids():
    assert provider_of("claude-sonnet-4-5") == "anthropic"
    assert provider_of("us.anthropic.claude-3-haiku") == "anthropic"
    assert provider_of("openai/gpt-4o") == "openai"
    assert provider_of("o3-mini") == "openai"
    assert provider_of("gemini-2.5-pro") == "google"
    assert provider_of("llama3") == "other"
    assert provider_of(None) == "other"


def test_exact_split_wins():
    v = provider_cost_values({"anthropic": 0.2, "openai": 0.1}, 0.3, "gemini-pro")
    assert v == {
        "anthropic_cost": 0.2,
        "openai_cost": 0.1,
        "google_cost": 0.0,
        "other_cost": 0.0,
    }


def test_total_goes_to_the_model_that_ran_without_a_split():
    v = provider_cost_values(None, 0.05, "gemini-2.5-flash")
    assert v["google_cost"] == 0.05
    assert sum(v.values()) == 0.05


def test_zero_cost_writes_zeros():
    assert set(provider_cost_values({}, 0, "claude").values()) == {0.0}


def test_set_provider_costs_on_a_row():
    row = SimpleNamespace(
        cost=0.4,
        model_used="claude-haiku-4-5",
        anthropic_cost=0,
        openai_cost=0,
        google_cost=0,
        other_cost=0,
    )
    set_provider_costs(row)
    assert row.anthropic_cost == 0.4
