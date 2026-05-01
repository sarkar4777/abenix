from __future__ import annotations


from prometheus_client import REGISTRY

from engine.metrics import (
    agent_active_streams,
    agent_execution_duration_seconds,
    llm_errors_total,
    llm_request_duration_seconds,
    llm_tokens_total,
    tool_execution_duration_seconds,
)


def _sample_value(metric_name: str, labels: dict[str, str] | None = None) -> float:
    for metric in REGISTRY.collect():
        if metric.name == metric_name or metric.name == metric_name.removesuffix(
            "_total"
        ):
            for sample in metric.samples:
                if labels is None:
                    return sample.value
                if all(sample.labels.get(k) == v for k, v in labels.items()):
                    return sample.value
    return 0.0


def test_llm_tokens_counter_increments():
    before = _sample_value(
        "abenix_llm_tokens", {"model": "test-model", "direction": "input"}
    )
    llm_tokens_total.labels(model="test-model", direction="input").inc(100)
    after = _sample_value(
        "abenix_llm_tokens", {"model": "test-model", "direction": "input"}
    )
    assert after - before == 100


def test_llm_request_duration_observes():
    llm_request_duration_seconds.labels(model="test-model", provider="test").observe(
        0.5
    )
    found = False
    for metric in REGISTRY.collect():
        if metric.name == "abenix_llm_request_duration_seconds":
            for sample in metric.samples:
                if (
                    sample.labels.get("model") == "test-model"
                    and "_count" in sample.name
                ):
                    assert sample.value >= 1
                    found = True
    assert found


def test_llm_errors_counter():
    before = _sample_value(
        "abenix_llm_errors", {"model": "test-model", "error_type": "TimeoutError"}
    )
    llm_errors_total.labels(model="test-model", error_type="TimeoutError").inc()
    after = _sample_value(
        "abenix_llm_errors", {"model": "test-model", "error_type": "TimeoutError"}
    )
    assert after - before == 1


def test_agent_execution_duration_observes():
    agent_execution_duration_seconds.observe(1.5)
    found = False
    for metric in REGISTRY.collect():
        if metric.name == "abenix_agent_execution_duration_seconds":
            for sample in metric.samples:
                if "_count" in sample.name:
                    assert sample.value >= 1
                    found = True
    assert found


def test_agent_active_streams_gauge():
    before = _sample_value("abenix_agent_active_streams")
    agent_active_streams.inc()
    after = _sample_value("abenix_agent_active_streams")
    assert after - before == 1
    agent_active_streams.dec()
    final = _sample_value("abenix_agent_active_streams")
    assert final == before


def test_tool_execution_duration():
    tool_execution_duration_seconds.labels(tool_name="calculator").observe(0.1)
    found = False
    for metric in REGISTRY.collect():
        if metric.name == "abenix_tool_execution_duration_seconds":
            for sample in metric.samples:
                if (
                    sample.labels.get("tool_name") == "calculator"
                    and "_count" in sample.name
                ):
                    assert sample.value >= 1
                    found = True
    assert found


def test_cache_hits_reexported():
    from engine.metrics import cache_hits, cache_misses

    cache_hits.labels(layer="test").inc()
    cache_misses.inc()
    assert _sample_value("abenix_cache_hits", {"layer": "test"}) >= 1
    assert _sample_value("abenix_cache_misses") >= 1
