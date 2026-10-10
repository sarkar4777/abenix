"""The retired SHAP code asset is never seeded again, seeded models gain their training means."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from seeds import seed_code_assets, seed_ml_models

ROOT = Path(__file__).resolve().parents[2]


def test_retired_asset_is_skipped_even_if_its_folder_comes_back(tmp_path, monkeypatch):
    for name in ("shap_explainer", "risk_quant"):
        d = tmp_path / name
        d.mkdir()
        (d / "agentforge.yaml").write_text(f"name: {name}\n")
        (d / "main.py").write_text("print(1)\n")
    monkeypatch.setattr(seed_code_assets, "DISCOVERY_ROOTS", [tmp_path])
    names = [m["name"] for _, m in seed_code_assets._discover_assets()]
    assert names == ["risk_quant"]


def test_shap_explainer_folder_is_gone():
    assert not (ROOT / "contractiq" / "code-assets" / "shap_explainer").exists()


def test_workbench_tree_models_ship_training_means():
    for name in ("offtake_storage_cycling", "offtake_industrial"):
        meta = json.loads(
            (ROOT / "contractiq" / "aimodels" / f"{name}.meta.json").read_text()
        )
        means = meta["training_metrics"]["feature_means"]
        assert list(means) == meta["input_schema"]["required"]


class _Res:
    def __init__(self, v):
        self.v = v

    def scalar_one_or_none(self):
        return self.v


class _Db:
    def __init__(self, row):
        self.row = row

    async def execute(self, stmt):
        return _Res(self.row)

    async def commit(self):
        return None


def _existing(tmp_path, tags, metrics):
    f = tmp_path / "m.pkl"
    f.write_bytes(b"x")
    return SimpleNamespace(file_uri=str(f), tags=tags, training_metrics=metrics)


def _run(tmp_path, monkeypatch, row):
    monkeypatch.setattr(seed_ml_models, "UPLOAD_DIR", tmp_path / "store")
    meta = {"name": "m", "training_metrics": {"feature_means": {"a": 1.5}}}
    tenant = SimpleNamespace(id="t1", slug="t1")
    asyncio.run(
        seed_ml_models._ensure_for_tenant(
            _Db(row), tenant, [(tmp_path / "m.pkl", meta)]
        )
    )


def test_seeded_row_gains_training_means(tmp_path, monkeypatch):
    row = _existing(tmp_path, ["oob", "sample"], {"mae": 1.0})
    _run(tmp_path, monkeypatch, row)
    assert row.training_metrics == {"mae": 1.0, "feature_means": {"a": 1.5}}


def test_user_row_with_the_same_name_is_left_alone(tmp_path, monkeypatch):
    row = _existing(tmp_path, ["mine"], {"mae": 1.0})
    _run(tmp_path, monkeypatch, row)
    assert row.training_metrics == {"mae": 1.0}
