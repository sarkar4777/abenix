"""The builder's runtime and scaling fields reach the columns the platform enforces."""

from types import SimpleNamespace


def _agent(**kw):
    base = dict(
        runtime_pool="default",
        min_replicas=1,
        max_replicas=5,
        concurrency_per_replica=3,
        rate_limit_qps=None,
        daily_budget_usd=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _user(role):
    return SimpleNamespace(role=SimpleNamespace(value=role))


def test_budget_and_rate_limit_apply_for_any_author():
    from app.routers.agents import _apply_scaling

    a = _agent()
    assert _apply_scaling(a, {"daily_budget_usd": 2.5, "rate_limit_qps": 4}, _user("creator")) is None
    assert a.daily_budget_usd == 2.5
    assert a.rate_limit_qps == 4


def test_null_clears_a_cap_and_a_missing_key_keeps_it():
    from app.routers.agents import _apply_scaling

    a = _agent(daily_budget_usd=3.0, rate_limit_qps=9)
    assert _apply_scaling(a, {"model": "x"}, _user("creator")) is None
    assert a.daily_budget_usd == 3.0 and a.rate_limit_qps == 9
    assert _apply_scaling(a, {"daily_budget_usd": None}, _user("creator")) is None
    assert a.daily_budget_usd is None
    assert a.rate_limit_qps == 9


def test_cost_knobs_need_an_admin():
    from app.routers.agents import _apply_scaling

    a = _agent()
    cfg = {"runtime_pool": "heavy-reasoning", "max_replicas": 40, "concurrency_per_replica": 10}
    assert _apply_scaling(a, cfg, _user("creator")) is None
    assert (a.runtime_pool, a.max_replicas, a.concurrency_per_replica) == ("default", 5, 3)
    assert _apply_scaling(a, cfg, _user("admin")) is None
    assert (a.runtime_pool, a.max_replicas, a.concurrency_per_replica) == ("heavy-reasoning", 40, 10)


def test_blank_replica_fields_keep_their_value():
    from app.routers.agents import _apply_scaling

    a = _agent()
    assert _apply_scaling(a, {"min_replicas": None, "concurrency_per_replica": None}, _user("admin")) is None
    assert a.min_replicas == 1 and a.concurrency_per_replica == 3


def test_bad_values_are_refused_with_the_admin_page_rules():
    from app.routers.agents import _apply_scaling

    assert "between 1 and 10000" in _apply_scaling(_agent(), {"rate_limit_qps": 0}, _user("creator"))
    assert "between 0 and 100000" in _apply_scaling(_agent(), {"daily_budget_usd": -1}, _user("creator"))
    assert "Invalid pool" in _apply_scaling(_agent(), {"runtime_pool": "turbo"}, _user("admin"))
    assert "cannot exceed" in _apply_scaling(_agent(), {"min_replicas": 9, "max_replicas": 2}, _user("admin"))


def test_editors_see_what_the_columns_enforce():
    from app.routers.agents import _scaling_view

    a = _agent(daily_budget_usd=1.5, rate_limit_qps=None)
    view = _scaling_view(a, {"model": "x", "daily_budget_usd": 99, "rate_limit_qps": 7})
    assert view["daily_budget_usd"] == 1.5
    assert "rate_limit_qps" not in view
    assert view["model"] == "x"
    assert view["runtime_pool"] == "default"
