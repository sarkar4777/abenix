"""ML model explain: exact linear attribution, Shapley sums for trees, baselines, access and input errors."""

from __future__ import annotations

import asyncio
import json
import sys
import types
import uuid
from types import SimpleNamespace

import joblib
import numpy as np
import pytest
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeRegressor

from app.core import ml_explain
from app.routers import ml_models as mm
from models.ml_model import MLModel, MLModelFramework, MLModelStatus
from models.ml_model_invocation import MLModelInvocation
from models.resource_share import SharePermission

TENANT = uuid.uuid4()
NAMES = ["a", "b", "c"]
RNG = np.random.default_rng(7)
X_TRAIN = RNG.normal(size=(200, 3)) * [1.0, 2.0, 3.0] + [5.0, -1.0, 2.0]


class Res:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)
        self.added: list = []

    async def execute(self, stmt, params=None):
        return Res(self.results.pop(0) if self.results else None)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.fixture(autouse=True)
def _no_shap(monkeypatch):
    # the real package may or may not be installed, tests pin the fallback paths
    monkeypatch.setitem(sys.modules, "shap", None)
    monkeypatch.setattr(mm, "_MODEL_CACHE", mm.OrderedDict())


@pytest.fixture
def local(monkeypatch):
    import app.core.artifact_store as art

    async def ensure_local(path):
        return None

    monkeypatch.setattr(art, "ensure_local", ensure_local)


def _user(owner=None):
    return SimpleNamespace(
        id=owner or uuid.uuid4(), tenant_id=TENANT, role=SimpleNamespace(value="user")
    )


def _save(tmp_path, est, name="m.joblib"):
    path = tmp_path / name
    joblib.dump(est, path)
    return str(path)


def _model(path, owner=None, **kw) -> MLModel:
    m = MLModel(
        tenant_id=TENANT,
        name="m",
        version="1.0.0",
        framework=MLModelFramework.SKLEARN,
        file_uri=path,
        status=kw.pop("status", MLModelStatus.READY),
        is_active=True,
        input_schema=kw.pop("input_schema", {"features": NAMES}),
        **kw,
    )
    m.id = uuid.uuid4()
    m.created_by = owner
    return m


def _body(resp) -> dict:
    return json.loads(resp.body)


def _linear():
    y = X_TRAIN @ np.array([2.0, -3.0, 0.5]) + 4.0
    return LinearRegression().fit(X_TRAIN, y)


def _tree():
    # interactions on purpose, one-at-a-time occlusion would not add up here
    y = X_TRAIN[:, 0] * X_TRAIN[:, 1] + np.where(X_TRAIN[:, 2] > 2, 3.0, -1.0)
    return DecisionTreeRegressor(max_depth=5, random_state=0).fit(X_TRAIN, y)


def _sync(path, input_data, baseline=None, schema=None, metrics=None, names=NAMES):
    return mm._explain_sync(
        path,
        MLModelFramework.SKLEARN,
        input_data,
        names,
        baseline,
        schema,
        metrics,
    )


def test_linear_attribution_is_exact(tmp_path):
    path = _save(tmp_path, _linear())
    out = _sync(path, {"a": 6.0, "b": 1.0, "c": 4.0}, baseline=[1.0, 2.0, 3.0])
    assert out["method"] == "linear"
    assert out["baseline_source"] == "request"
    got = {c["feature"]: c["contribution"] for c in out["contributions"]}
    assert got["a"] == pytest.approx(2.0 * 5.0)
    assert got["b"] == pytest.approx(-3.0 * -1.0)
    assert got["c"] == pytest.approx(0.5 * 1.0)
    assert out["prediction"] == pytest.approx(2 * 6 - 3 * 1 + 0.5 * 4 + 4)
    assert out["base_value"] == pytest.approx(2 * 1 - 3 * 2 + 0.5 * 3 + 4)


def test_scaled_linear_pipeline_is_exact_against_scaler_means(tmp_path):
    y = X_TRAIN @ np.array([2.0, -3.0, 0.5]) + 4.0
    pipe = Pipeline([("s", StandardScaler()), ("r", LinearRegression())]).fit(
        X_TRAIN, y
    )
    path = _save(tmp_path, pipe)
    out = _sync(path, [6.0, 1.0, 4.0])
    assert out["method"] == "linear"
    assert out["baseline_source"] == "training_means_from_model"
    means = X_TRAIN.mean(axis=0)
    got = [out["baseline"][n] for n in NAMES]
    assert got == pytest.approx(means.tolist())
    by = {c["feature"]: c["contribution"] for c in out["contributions"]}
    assert by["a"] == pytest.approx(2.0 * (6.0 - means[0]), rel=1e-6)


def test_tree_contributions_sum_to_prediction_minus_baseline(tmp_path):
    path = _save(tmp_path, _tree())
    model = _tree()
    x, b = [7.0, 1.5, 4.0], [5.0, -1.0, 1.0]
    out = _sync(path, x, baseline=b)
    assert out["method"] == "exact-shapley"
    fx, fb = model.predict(np.array([x, b]))
    total = sum(c["contribution"] for c in out["contributions"])
    assert out["prediction"] == pytest.approx(fx)
    assert out["base_value"] == pytest.approx(fb)
    assert total == pytest.approx(fx - fb, abs=1e-9)
    assert abs(out["additivity_gap"]) < 1e-9
    # the waterfall walks from the baseline value to the prediction
    steps = out["waterfall"]
    assert steps[0]["start"] == pytest.approx(fb)
    assert steps[-1]["end"] == pytest.approx(fx)
    for prev, nxt in zip(steps, steps[1:]):
        assert nxt["start"] == pytest.approx(prev["end"])


def test_sampled_shapley_adds_up_for_many_features():
    w = np.arange(1, 15, dtype=float)

    def f(Z):
        return Z @ w + Z[:, 0] * Z[:, 1]

    x, b = np.ones(14) * 2, np.zeros(14)
    phi, fx, fb, method = ml_explain.attribute(f, x, b)
    assert method == "sampled-shapley"
    assert phi.sum() == pytest.approx(fx - fb)


def test_exact_shapley_splits_an_interaction_evenly():
    def f(Z):
        return Z[:, 0] * Z[:, 1]

    phi = ml_explain.exact_shapley(f, np.array([2.0, 3.0]), np.zeros(2))
    assert phi.tolist() == pytest.approx([3.0, 3.0])


def test_classifier_explains_the_probability_of_its_class(tmp_path):
    y = (X_TRAIN[:, 0] > 5).astype(int)
    path = _save(tmp_path, LogisticRegression().fit(X_TRAIN, y))
    out = _sync(path, [8.0, 0.0, 0.0])
    assert out["target"] == "probability of 1"
    assert out["predicted_class"] == "1"
    assert out["method"] == "exact-shapley"
    total = sum(c["contribution"] for c in out["contributions"])
    assert total == pytest.approx(out["prediction"] - out["base_value"])


def test_outlier_model_explains_its_anomaly_score(tmp_path):
    path = _save(tmp_path, IsolationForest(random_state=0).fit(X_TRAIN))
    out = _sync(path, [20.0, 0.0, 0.0])
    assert out["target"].startswith("anomaly score")
    assert abs(out["additivity_gap"]) < 1e-9


def test_baseline_falls_back_to_stored_means_then_zeros(tmp_path):
    path = _save(tmp_path, _linear())
    stored = _sync(path, [1, 1, 1], metrics={"feature_means": {"a": 1, "b": 2, "c": 3}})
    assert stored["baseline_source"] == "training_means"
    assert stored["baseline"] == {"a": 1.0, "b": 2.0, "c": 3.0}
    zeros = _sync(path, [1, 1, 1])
    assert zeros["baseline_source"] == "zeros"
    partial = _sync(
        path,
        [1, 1, 1],
        baseline={"b": 9},
        schema={"features": NAMES, "x-feature-means": [1, 2, 3]},
    )
    assert partial["baseline"] == {"a": 1.0, "b": 9.0, "c": 3.0}
    assert partial["baseline_source"] == "request, rest from training_means"


@pytest.mark.parametrize(
    "input_data,baseline,needle",
    [
        ([[1, 2, 3], [4, 5, 6]], None, "one row at a time"),
        ([1, 2], None, "expects 3 features, you sent 2"),
        ({"a": 1, "b": 2}, None, "Missing c"),
        ([1, 2, 3], [1, 2], "baseline has 2 values"),
        ([1, 2, 3], {"zz": 1}, "unknown features: zz"),
        ([1, 2, 3], {"a": "high"}, "baseline value for a must be a number"),
        (["some clause text"], None, "needs numeric features"),
    ],
)
def test_bad_input_is_a_clear_error(tmp_path, input_data, baseline, needle):
    path = _save(tmp_path, _linear())
    with pytest.raises((mm.PredictInputError, ml_explain.ExplainInputError)) as e:
        _sync(path, input_data, baseline=baseline)
    assert needle in str(e.value)


def test_names_come_from_schema_properties_or_the_dict():
    m = SimpleNamespace(
        input_schema={"properties": {"x1": {}, "x2": {}}}, training_metrics=None
    )
    assert mm._explain_names(m, [1, 2]) == ["x1", "x2"]
    bare = SimpleNamespace(input_schema=None, training_metrics=None)
    assert mm._explain_names(bare, {"p": 1, "q": 2}) == ["p", "q"]
    assert mm._explain_names(bare, {"features": [1, 2]}) == []


def test_shap_is_used_when_installed_and_it_adds_up(tmp_path, monkeypatch):
    model = _tree()
    x, b = np.array([7.0, 1.5, 4.0]), np.array([5.0, -1.0, 1.0])
    exact = ml_explain.exact_shapley(lambda Z: model.predict(Z), x, b)

    class TreeExplainer:
        def __init__(self, est, data=None, feature_perturbation=None):
            pass

        def shap_values(self, X):
            return exact.reshape(1, -1)

    monkeypatch.setitem(
        sys.modules, "shap", types.SimpleNamespace(TreeExplainer=TreeExplainer)
    )
    phi, _, _, method = ml_explain.attribute(
        lambda Z: model.predict(Z), x, b, model=model, allow_shap=True
    )
    assert method == "tree-shap"

    class Wrong(TreeExplainer):
        def shap_values(self, X):
            return np.ones((1, 3)) * 1000

    monkeypatch.setitem(sys.modules, "shap", types.SimpleNamespace(TreeExplainer=Wrong))
    _, _, _, method = ml_explain.attribute(
        lambda Z: model.predict(Z), x, b, model=model, allow_shap=True
    )
    assert method == "exact-shapley"


# endpoint


def _call(model, user, body, db=None):
    db = db or FakeSession(model)
    return (
        asyncio.run(
            mm.explain(model.id if model else uuid.uuid4(), body, user=user, db=db)
        ),
        db,
    )


def test_endpoint_returns_the_explanation_and_logs_it(tmp_path, local, monkeypatch):
    from contextlib import asynccontextmanager

    from app.core import deps

    owner = uuid.uuid4()
    model = _model(_save(tmp_path, _linear()), owner=owner)
    db = FakeSession(model)

    @asynccontextmanager
    async def same():
        yield db

    monkeypatch.setattr(deps, "async_session", same)

    async def go():
        resp = await mm.explain(
            model.id,
            {"input_data": {"a": 6, "b": 1, "c": 4}, "baseline": [1, 2, 3]},
            user=_user(owner),
            db=db,
        )
        await asyncio.gather(*list(mm._BACKGROUND))
        return resp

    resp = asyncio.run(go())
    assert resp.status_code == 200
    data = _body(resp)["data"]
    assert data["method"] == "linear" and data["source"] == "local"
    assert data["model_name"] == "m"
    (inv,) = db.added
    assert isinstance(inv, MLModelInvocation)
    assert inv.operation == "explain" and inv.is_error is False


def test_other_tenant_or_missing_model_is_404():
    resp, _ = _call(None, _user(), {"input_data": [1, 2, 3]}, db=FakeSession(None))
    assert resp.status_code == 404


def _shares(monkeypatch, view=()):
    import app.core.permissions as perms

    async def ids(db, u, *, kind, minimum_permission=SharePermission.VIEW):
        return set(view)

    monkeypatch.setattr(perms, "accessible_resource_ids", ids)


def test_stranger_gets_404_and_a_view_share_can_explain(tmp_path, local, monkeypatch):
    model = _model(_save(tmp_path, _linear()), owner=uuid.uuid4())
    _shares(monkeypatch)
    resp, _ = _call(model, _user(), {"input_data": [1, 2, 3]})
    assert resp.status_code == 404

    _shares(monkeypatch, view={model.id})
    monkeypatch.setattr(mm, "_log_in_background", lambda *a, **k: None)
    resp, _ = _call(model, _user(), {"input_data": [1, 2, 3]})
    assert resp.status_code == 200


def test_predict_hides_a_model_the_caller_cannot_see(tmp_path, monkeypatch):
    model = _model(_save(tmp_path, _linear()), owner=uuid.uuid4())
    _shares(monkeypatch)
    resp = asyncio.run(
        mm.predict(
            model.id, {"input_data": [1, 2, 3]}, user=_user(), db=FakeSession(model)
        )
    )
    assert resp.status_code == 404


def test_model_not_ready_is_409(tmp_path):
    model = _model(
        _save(tmp_path, _linear()),
        status=MLModelStatus.ERROR,
        training_metrics={"validation_error": "bad file"},
    )
    resp, _ = _call(model, _user(), {"input_data": [1, 2, 3]})
    assert resp.status_code == 409


@pytest.mark.parametrize(
    "body,needle",
    [
        ({}, "input_data is required"),
        ({"input_data": [1, 2, 3], "baseline": "mean"}, "baseline must be"),
        ({"input_data": [1, 2]}, "expects 3 features"),
        ({"input_data": [1, 2, 3], "baseline": {"nope": 1}}, "unknown features"),
    ],
)
def test_bad_input_is_422(tmp_path, local, body, needle):
    model = _model(_save(tmp_path, _linear()))
    resp, db = _call(model, _user(), body)
    assert resp.status_code == 422
    assert needle in _body(resp)["error"]["message"]
    for inv in db.added:
        assert inv.operation == "explain" and inv.is_error
