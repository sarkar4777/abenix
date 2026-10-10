"""A predict loads the model file once, later calls reuse it until the file changes."""

from __future__ import annotations

import os
import time

from app.routers import ml_models


def test_model_file_is_loaded_once(tmp_path, monkeypatch):
    f = tmp_path / "m.bin"
    f.write_text("v1")
    loads = []

    def loader(path):
        loads.append(path)
        return object()

    monkeypatch.setattr(ml_models, "_MODEL_CACHE", ml_models.OrderedDict())
    a = ml_models._cached(str(f), loader)
    b = ml_models._cached(str(f), loader)
    assert a is b and len(loads) == 1


def test_a_replaced_file_is_loaded_again(tmp_path, monkeypatch):
    f = tmp_path / "m.bin"
    f.write_text("v1")
    monkeypatch.setattr(ml_models, "_MODEL_CACHE", ml_models.OrderedDict())
    first = ml_models._cached(str(f), lambda p: object())
    later = time.time() + 5
    os.utime(f, (later, later))
    second = ml_models._cached(str(f), lambda p: object())
    assert first is not second


def test_cache_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(ml_models, "_MODEL_CACHE", ml_models.OrderedDict())
    monkeypatch.setattr(ml_models, "_MODEL_CACHE_MAX", 2)
    for i in range(4):
        f = tmp_path / f"m{i}.bin"
        f.write_text("x")
        ml_models._cached(str(f), lambda p: object())
    assert len(ml_models._MODEL_CACHE) == 2
