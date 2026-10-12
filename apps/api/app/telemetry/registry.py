"""Finds every connector and decoder module by walking their packages. Nobody keeps a list."""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Any

from app.telemetry.connectors.base import SourceConnector
from app.telemetry.decoders.base import Decoder, DocumentDecoder

logger = logging.getLogger(__name__)

_connectors: dict[str, type[SourceConnector]] | None = None
_decoders: dict[str, type[Decoder]] | None = None
# modules that would not import, such as a transport whose client library is missing
broken: dict[str, str] = {}


def _scan(package: str, base: type, key: str) -> dict[str, type]:
    pkg = importlib.import_module(package)
    found: dict[str, type] = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name.startswith("_") or info.name == "base":
            continue
        mod_name = f"{package}.{info.name}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001
            broken[mod_name] = f"{type(exc).__name__}: {exc}"
            logger.warning("telemetry plugin %s did not load: %s", mod_name, exc)
            continue
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(obj, base)
                and obj is not base
                and obj is not DocumentDecoder
                and obj.__module__ == mod.__name__
                and getattr(obj, key, "")
            ):
                found[getattr(obj, key)] = obj
    return found


def connectors() -> dict[str, type[SourceConnector]]:
    global _connectors
    if _connectors is None:
        _connectors = _scan("app.telemetry.connectors", SourceConnector, "transport")
    return _connectors


def decoders() -> dict[str, type[Decoder]]:
    global _decoders
    if _decoders is None:
        _decoders = _scan("app.telemetry.decoders", Decoder, "name")
    return _decoders


def connector(transport: str) -> SourceConnector:
    cls = connectors().get(transport)
    if cls is None:
        raise KeyError(
            f"There is no {transport} transport. Pick one of {', '.join(sorted(connectors()))}"
        )
    return cls()


def decoder(name: str) -> Decoder:
    cls = decoders().get(name)
    if cls is None:
        raise KeyError(
            f"There is no {name} decoder. Pick one of {', '.join(sorted(decoders()))}"
        )
    return cls()


def catalogue() -> dict[str, Any]:
    return {
        "transports": [c.describe() for _, c in sorted(connectors().items())],
        "decoders": [d.describe() for _, d in sorted(decoders().items())],
        "unavailable": dict(broken),
    }


def reset() -> None:
    global _connectors, _decoders
    _connectors = _decoders = None
    broken.clear()
