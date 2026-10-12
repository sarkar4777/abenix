"""Collector types by name. The platform's catalog names the same types."""

from __future__ import annotations

from typing import Any

from abenix_edge.collectors.base import Collector


def types() -> dict[str, type[Collector]]:
    from abenix_edge.collectors.can_bus import CanCollector
    from abenix_edge.collectors.file_tail import FileTailCollector
    from abenix_edge.collectors.modbus import ModbusCollector
    from abenix_edge.collectors.mqtt_bridge import MqttBridgeCollector
    from abenix_edge.collectors.nmea import NmeaCollector
    from abenix_edge.collectors.opcua import OpcuaCollector

    return {
        c.type: c
        for c in (
            CanCollector,
            ModbusCollector,
            OpcuaCollector,
            NmeaCollector,
            MqttBridgeCollector,
            FileTailCollector,
        )
    }


def build(spec: dict[str, Any], sink: Any, gateway_id: str) -> Collector:
    t = types().get(str(spec.get("type") or ""))
    if t is None:
        raise ValueError(
            f"This version of Abenix Edge has no collector of type {spec.get('type')!r}. Update the gateway."
        )
    return t(spec, sink, gateway_id)
