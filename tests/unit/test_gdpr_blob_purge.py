"""GDPR purge blob step: deletes the user's real stored files and logs the true count."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import gdpr_purge
from app.services.gdpr_purge import Subject
from models.code_asset import CodeAssetStatus
from models.ml_model import MLModelStatus

TENANT = uuid.uuid4()
USER = uuid.uuid4()


def _subject() -> Subject:
    return Subject(tenant_id=TENANT, user_id=USER)


class _Rows:
    def __init__(self, rows=None, first=None):
        self.rows = rows or []
        self._first = first

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self._first


class _Db:
    def __init__(self, assets=(), models=(), voice=None):
        self.assets, self.models, self.voice = list(assets), list(models), voice
        self.sql: list[str] = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.sql.append(sql)
        if "FROM code_assets" in sql:
            return _Rows(self.assets)
        if "FROM ml_models" in sql:
            return _Rows(self.models)
        if "SELECT voice_id" in sql:
            return _Rows(first=self.voice)
        return _Rows()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


def _asset(tmp_path, name, versions=()):
    p = tmp_path / "code-assets" / name / "v2.zip"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"zip")
    history = []
    for v in versions:
        old = p.parent / v
        old.write_bytes(b"old")
        history.append({"version": v, "storage_uri": str(old)})
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        storage_uri=str(p),
        version_history=history or None,
        status=CodeAssetStatus.READY,
    )


def _model(tmp_path, name):
    p = tmp_path / "ml-models" / f"{name}.pkl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"pkl")
    return SimpleNamespace(id=uuid.uuid4(), file_uri=str(p), status=MLModelStatus.READY)


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_ROOT", str(tmp_path))
    return tmp_path


@pytest.mark.asyncio
async def test_owned_uploads_are_deleted_unless_in_use(local_storage, monkeypatch):
    tmp = local_storage
    free = _asset(tmp, "parser", versions=["v1.zip"])
    used = _asset(tmp, "pricer")
    model = _model(tmp, "churn")
    busy_model = _model(tmp, "risk")

    async def asset_in_use(db, s, a):
        return a is used

    async def model_in_use(db, s, m):
        return m is busy_model

    monkeypatch.setattr(gdpr_purge, "_code_asset_in_use", asset_in_use)
    monkeypatch.setattr(gdpr_purge, "_ml_model_in_use", model_in_use)
    db = _Db(assets=[free, used], models=[model, busy_model])
    free_paths = [free.storage_uri, free.version_history[0]["storage_uri"]]
    model_path = model.file_uri

    removed = await gdpr_purge._purge_owned_uploads(db, _subject())

    assert removed == 3
    assert not any(gdpr_purge.Path(p).exists() for p in free_paths + [model_path])
    assert gdpr_purge.Path(used.storage_uri).exists()
    assert gdpr_purge.Path(busy_model.file_uri).exists()
    assert free.status == CodeAssetStatus.DELETED and free.storage_uri is None
    assert used.status == CodeAssetStatus.READY
    assert model.status == MLModelStatus.DELETED
    assert busy_model.status == MLModelStatus.READY
    assert db.commits == 1
    owner_filters = [s for s in db.sql if "created_by" in s]
    assert len(owner_filters) == 2


@pytest.mark.asyncio
async def test_a_file_only_in_object_storage_still_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_ROOT", str(tmp_path))
    store = SimpleNamespace(
        exists=AsyncMock(return_value=True), delete=AsyncMock(return_value=True)
    )
    gone = str(tmp_path / "ml-models" / "lost.pkl")
    with patch("app.core.object_storage.get_object_storage", return_value=store), patch(
        "app.core.artifact_store.get_object_storage", return_value=store
    ):
        assert await gdpr_purge._remove_file(gone) is True
    store.delete.assert_awaited_once_with("artifacts/ml-models/lost.pkl")


@pytest.mark.asyncio
async def test_a_missing_file_does_not_count(local_storage):
    assert await gdpr_purge._remove_file(str(local_storage / "nope.zip")) is False


@pytest.mark.asyncio
async def test_user_namespace_files_are_deleted_through_storage(tmp_path, monkeypatch):
    from engine.storage import service

    monkeypatch.setattr(service, "STORAGE_LOCAL_DIR", str(tmp_path))
    mine = tmp_path / str(TENANT) / "users" / str(USER)
    (mine / "media").mkdir(parents=True)
    (mine / "avatar.png").write_bytes(b"png")
    (mine / "media" / "clip.wav").write_bytes(b"wav")
    other = tmp_path / str(TENANT) / "users" / str(uuid.uuid4())
    other.mkdir(parents=True)
    (other / "avatar.png").write_bytes(b"png")
    monkeypatch.setattr(service, "_instance", service.StorageService("local"))

    assert await gdpr_purge._purge_user_namespace(_subject()) == 2
    assert not any(p.is_file() for p in mine.rglob("*"))
    assert (other / "avatar.png").is_file()


@pytest.mark.asyncio
async def test_voice_clone_is_deleted_at_the_provider_and_unlinked():
    db = _Db(voice=("v-123", "ElevenLabs"))
    with patch(
        "engine.tools._voice_clone.elevenlabs_delete_voice",
        AsyncMock(return_value=True),
    ) as delete:
        assert await gdpr_purge._purge_voice_clone(db, _subject()) == 1
    delete.assert_awaited_once_with(voice_id="v-123")
    assert any("voice_id = NULL" in s for s in db.sql)
    assert db.commits == 1


@pytest.mark.asyncio
async def test_voice_clone_provider_failure_fails_the_step():
    db = _Db(voice=("v-123", "elevenlabs"))
    with patch(
        "engine.tools._voice_clone.elevenlabs_delete_voice",
        AsyncMock(return_value=False),
    ):
        with pytest.raises(RuntimeError, match="v-123"):
            await gdpr_purge._purge_voice_clone(db, _subject())
    assert not any("voice_id = NULL" in s for s in db.sql)


@pytest.mark.asyncio
async def test_no_voice_clone_is_zero():
    assert await gdpr_purge._purge_voice_clone(_Db(voice=None), _subject()) == 0
    assert await gdpr_purge._purge_voice_clone(_Db(voice=(None, None)), _subject()) == 0


@pytest.mark.asyncio
async def test_purge_user_logs_the_true_blob_count():
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    added = []
    db.add = added.append

    async def zero(db_, s):
        return 0

    purgers = {**gdpr_purge._PURGERS}
    for k in ("postgres", "pinecone", "neo4j", "trajectory"):
        purgers[k] = zero
    with patch.object(gdpr_purge, "_PURGERS", purgers), patch.object(
        gdpr_purge, "load_subject", AsyncMock(return_value=_subject())
    ), patch.object(
        gdpr_purge, "_purge_owned_uploads", AsyncMock(return_value=3)
    ), patch.object(
        gdpr_purge, "_purge_user_namespace", AsyncMock(return_value=2)
    ), patch.object(
        gdpr_purge, "_purge_voice_clone", AsyncMock(return_value=1)
    ):
        receipt = await gdpr_purge.purge_user(
            db, tenant_id=TENANT, subject_user_id=USER
        )
    assert receipt["blob"] == {"status": "completed", "affected": 6}
    done = [r for r in added if r.store == "blob" and r.status == "completed"]
    assert done[0].affected_count == 6


def test_blob_step_no_longer_imports_a_missing_module():
    import inspect

    assert "app.core.blob" not in inspect.getsource(gdpr_purge)


@pytest.mark.asyncio
async def test_in_use_checks_read_agents_deployments_and_shares():
    a = SimpleNamespace(id=uuid.uuid4(), name="parser")
    m = SimpleNamespace(id=uuid.uuid4())
    db = _Db()
    with patch(
        "app.services.dependents.code_asset_dependents",
        AsyncMock(return_value={"agents": [{"id": "x"}], "pipelines": []}),
    ):
        assert await gdpr_purge._code_asset_in_use(db, _subject(), a) is True
    with patch(
        "app.services.dependents.code_asset_dependents",
        AsyncMock(return_value={"agents": [], "pipelines": []}),
    ):
        assert await gdpr_purge._code_asset_in_use(db, _subject(), a) is False
    with patch(
        "app.services.dependents._agents_mentioning", AsyncMock(return_value=[])
    ) as mentions:
        assert await gdpr_purge._ml_model_in_use(db, _subject(), m) is False
    mentions.assert_awaited_once_with(db, TENANT, [str(m.id)], None)
    assert any("ml_deployments" in s or "deployment" in s for s in db.sql)
    assert any("resource_shares" in s for s in db.sql)
