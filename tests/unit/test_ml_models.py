"""ML model registry: load checks, versions, input errors, invocations, idempotent deploys, samples."""

from __future__ import annotations

import io
import json
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import UploadFile

from app.core import ml_samples
from app.routers import ml_models as mm
from models.ml_model import (
    DeploymentStatus,
    DeploymentType,
    MLModel,
    MLModelDeployment,
    MLModelFramework,
    MLModelStatus,
)
from models.ml_model_invocation import MLModelInvocation

TENANT = uuid.uuid4()
IRIS = ml_samples.sample_file("iris")
NAMES = ml_samples.IRIS_FEATURES


class Res:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self.value or []))


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)
        self.statements: list = []
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        self.statements.append(stmt)
        return Res(self.results.pop(0) if self.results else None)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1
        for o in self.added:
            if getattr(o, "id", None) is None:
                o.id = uuid.uuid4()

    async def refresh(self, obj):
        return None

    async def rollback(self):
        return None


def _user():
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=TENANT, role=SimpleNamespace(value="creator")
    )


def _body(resp) -> dict:
    return json.loads(resp.body)


def _model(tmp_path, status=MLModelStatus.READY, **kw) -> MLModel:
    path = tmp_path / "iris.joblib"
    if not path.exists():
        shutil.copy(IRIS, path)
    m = MLModel(
        tenant_id=TENANT,
        name="iris",
        version="1.0.0",
        framework=MLModelFramework.SKLEARN,
        file_uri=str(path),
        status=status,
        is_active=status == MLModelStatus.READY,
        input_schema=kw.pop("input_schema", {"features": NAMES}),
        **kw,
    )
    m.id = uuid.uuid4()
    return m


@pytest.fixture
def store(tmp_path, monkeypatch):
    async def mirror(path):
        return None

    import app.core.artifact_store as art

    monkeypatch.setattr(art, "mirror", mirror)
    monkeypatch.setattr(mm, "UPLOAD_DIR", tmp_path / "store")
    return tmp_path


def _upload(content: bytes, filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename)


@pytest.mark.asyncio
async def test_text_file_named_pkl_is_refused_with_the_reason(store):
    db = FakeSession([])
    resp = await mm.upload_model(
        file=_upload(b"this is plain text, not a pickle\n", "fake.pkl"),
        metadata=json.dumps({"name": "fake"}),
        user=_user(),
        db=db,
    )
    assert resp.status_code == 422
    err = _body(resp)["error"]
    assert err["error_code"] == "MODEL_LOAD_FAILED"
    assert "could not be loaded as a scikit-learn model" in err["message"]
    saved = err["details"]["model"]
    assert saved["status"] == "error"
    assert saved["is_active"] is False
    assert saved["status_message"] == err["message"]
    # the active version of the name is left alone
    assert len(db.statements) == 1
    (row,) = db.added
    assert row.training_metrics == {"validation_error": err["message"]}


@pytest.mark.asyncio
async def test_good_upload_is_ready_active_and_gets_next_version(store):
    db = FakeSession(["1.0.0"])
    resp = await mm.upload_model(
        file=_upload(IRIS.read_bytes(), "iris.joblib"),
        metadata=json.dumps({"name": "iris"}),
        user=_user(),
        db=db,
    )
    assert resp.status_code == 201
    data = _body(resp)["data"]
    assert data["status"] == "ready" and data["is_active"] is True
    assert data["version"] == "1.1.0"
    assert data["status_message"] is None
    assert data["input_schema"]["properties"]["input_data"]["items"]["minItems"] == 4


@pytest.mark.asyncio
async def test_duplicate_version_is_refused_with_the_next_one(store):
    db = FakeSession(["1.0.0"])
    resp = await mm.upload_model(
        file=_upload(IRIS.read_bytes(), "iris.joblib"),
        metadata=json.dumps({"name": "iris", "version": "1.0.0"}),
        user=_user(),
        db=db,
    )
    assert resp.status_code == 409
    err = _body(resp)["error"]
    assert err["error_code"] == "VERSION_EXISTS"
    assert err["details"]["next_version"] == "1.1.0"
    assert "version 1.1.0" in err["message"]
    assert not db.added


@pytest.mark.asyncio
async def test_tensorflow_upload_is_refused_up_front(store):
    resp = await mm.upload_model(
        file=_upload(b"x", "m.h5"), metadata="{}", user=_user(), db=FakeSession()
    )
    assert resp.status_code == 422
    assert "ONNX" in _body(resp)["error"]["message"]


def test_next_version():
    assert mm._next_version([]) == "1.0.0"
    assert mm._next_version(["1.0.0"]) == "1.1.0"
    assert mm._next_version(["1.0.0", "2.3.1", "beta"]) == "2.4.0"
    assert mm._next_version(["v1"]) == "1.1.0"


def test_feature_count_message_names_the_order():
    with pytest.raises(mm.PredictInputError) as e:
        mm._predict_sync(str(IRIS), MLModelFramework.SKLEARN, [5.1, 3.5], NAMES)
    assert str(e.value) == (
        "This model expects 4 features, you sent 2. Send them in this order: "
        "sepal_length, sepal_width, petal_length, petal_width."
    )


def test_named_features_are_put_in_order():
    out = mm._predict_sync(
        str(IRIS),
        MLModelFramework.SKLEARN,
        dict(zip(reversed(NAMES), [2.3, 5.2, 3.0, 6.7])),
        NAMES,
    )
    assert out["predicted_class"] == "virginica"


@pytest.mark.asyncio
async def test_wrong_feature_count_is_422_and_counted(tmp_path):
    model = _model(tmp_path)
    db = FakeSession(model, None)
    resp = await mm.predict(
        model.id, {"input_data": {"features": [5.1, 3.5]}}, user=_user(), db=db
    )
    assert resp.status_code == 422
    assert "expects 4 features, you sent 2" in _body(resp)["error"]["message"]
    (inv,) = db.added
    assert isinstance(inv, MLModelInvocation) and inv.is_error


@pytest.mark.asyncio
async def test_prediction_is_counted_as_an_invocation(tmp_path):
    model = _model(tmp_path)
    db = FakeSession(model, None)
    resp = await mm.predict(
        model.id,
        {"input_data": {"features": [5.1, 3.5, 1.4, 0.2]}},
        user=_user(),
        db=db,
    )
    assert resp.status_code == 200
    data = _body(resp)["data"]
    assert data["predicted_class"] == "setosa" and data["source"] == "local"
    (inv,) = db.added
    assert inv.is_error is False
    assert inv.predicted_class == "setosa"
    assert inv.confidence and inv.confidence > 0.9
    assert inv.ml_model_id == model.id


@pytest.mark.asyncio
async def test_error_model_cannot_predict_deploy_or_activate(tmp_path):
    model = _model(
        tmp_path,
        status=MLModelStatus.ERROR,
        training_metrics={"validation_error": "bad file"},
    )
    r1 = await mm.predict(
        model.id, {"input_data": [1]}, user=_user(), db=FakeSession(model)
    )
    r2 = await mm.deploy_model(model.id, {}, user=_user(), db=FakeSession(model))
    r3 = await mm.activate_version(model.id, user=_user(), db=FakeSession(model))
    for r in (r1, r2, r3):
        assert r.status_code == 409
        assert "bad file" in _body(r)["error"]["message"]


@pytest.mark.asyncio
async def test_second_local_deploy_returns_the_running_one(tmp_path):
    model = _model(tmp_path)
    running = MLModelDeployment(
        model_id=model.id,
        deployment_type=DeploymentType.LOCAL,
        status=DeploymentStatus.RUNNING,
        replicas=1,
    )
    running.id = uuid.uuid4()
    db = FakeSession(model, [running])
    resp = await mm.deploy_model(
        model.id, {"deployment_type": "local"}, user=_user(), db=db
    )
    data = _body(resp)["data"]
    assert resp.status_code == 200
    assert data["already_deployed"] is True
    assert data["deployment_id"] == str(running.id)
    assert not db.added


@pytest.mark.asyncio
async def test_first_local_deploy_creates_one(tmp_path):
    model = _model(tmp_path)
    db = FakeSession(model, [])
    resp = await mm.deploy_model(
        model.id, {"deployment_type": "local"}, user=_user(), db=db
    )
    assert resp.status_code == 200
    (dep,) = db.added
    assert dep.status == DeploymentStatus.RUNNING


@pytest.mark.asyncio
async def test_sample_registers_ready_with_a_usable_schema(store):
    db = FakeSession(None, [])
    resp = await mm.register_sample_model("iris", user=_user(), db=db)
    assert resp.status_code == 201
    data = _body(resp)["data"]
    assert data["name"] == "iris-sample" and data["status"] == "ready"
    schema = data["input_schema"]
    assert schema["features"] == NAMES and len(schema["example"]) == 4
    out = mm._predict_sync(
        db.added[0].file_uri,
        MLModelFramework.SKLEARN,
        {"features": schema["example"]},
        NAMES,
    )
    assert out["predicted_class"] == "setosa"


@pytest.mark.asyncio
async def test_sample_is_not_registered_twice(tmp_path):
    existing = _model(tmp_path)
    db = FakeSession(existing, [])
    resp = await mm.register_sample_model("iris", user=_user(), db=db)
    assert resp.status_code == 200
    assert _body(resp)["data"]["id"] == str(existing.id)
    assert not db.added


@pytest.mark.asyncio
async def test_unknown_sample_is_404():
    resp = await mm.register_sample_model("nope", user=_user(), db=FakeSession())
    assert resp.status_code == 404


def test_shipped_sample_file_exists():
    assert Path(IRIS).is_file()
