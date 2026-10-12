"""Raw CAN frames as JSON, kept in a ring per asset, and decoded into signals when a DBC is given.

    [{"t": 1791720000123, "id": 217056256, "data": "F0FF7D401B0000FF", "dlc": 8}]

The group and asset come from the first two subject levels (groundwork/ipc-ex1/can/raw)
unless the mapping says otherwise. With a DBC, J1939 frames are matched on their
PGN, so one message definition covers every source address.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.telemetry import mapping as M
from app.telemetry.connectors.base import ConfigField, Envelope
from app.telemetry.decoders.base import (
    DecodeError,
    Decoder,
    DecoderState,
    Metric,
    Record,
)

MAX_FRAMES_PER_MESSAGE = 500
ERR_FLAG = 0x20000000
EFF_FLAG = 0x80000000


def clean_frame(it: Any, now_ms: int) -> dict[str, Any] | None:
    """{t, id, data, dlc} with t in epoch ms, id an int and data a hex string."""
    if not isinstance(it, dict):
        return None
    raw_id = it.get("id")
    try:
        can_id = int(raw_id, 16) if isinstance(raw_id, str) else int(raw_id)
    except (TypeError, ValueError):
        return None
    data = it.get("data", "")
    if isinstance(data, list):
        try:
            data = bytes(int(x) & 0xFF for x in data).hex()
        except (TypeError, ValueError):
            return None
    data = str(data).replace(" ", "").lower()
    try:
        bytes.fromhex(data)
    except ValueError:
        return None
    t = it.get("t")
    try:
        t = float(t)
        # seconds are read as seconds, anything bigger is already ms
        t = int(t * 1000) if t < 1e11 else int(t)
    except (TypeError, ValueError):
        t = now_ms
    dlc = it.get("dlc")
    try:
        dlc = int(dlc) if dlc is not None else len(data) // 2
    except (TypeError, ValueError):
        dlc = len(data) // 2
    return {"t": t, "id": can_id, "data": data, "dlc": dlc}


def pgn_of(can_id: int) -> int:
    pgn = (can_id >> 8) & 0x3FFFF
    if ((pgn >> 8) & 0xFF) < 240:
        pgn &= 0x3FF00
    return pgn


class _Dbc:
    def __init__(self, text: str, j1939: bool) -> None:
        try:
            import cantools
        except ImportError:  # pragma: no cover
            raise DecodeError(
                "DBC decoding needs the cantools package on the ingest"
            ) from None
        try:
            self.db = cantools.database.load_string(text, database_format="dbc")
        except Exception as exc:  # noqa: BLE001
            raise DecodeError(f"The DBC file did not load: {exc}") from None
        self.by_id = {m.frame_id: m for m in self.db.messages}
        self.by_pgn = {pgn_of(m.frame_id): m for m in self.db.messages} if j1939 else {}

    def message(self, can_id: int) -> Any:
        cid = can_id & 0x1FFFFFFF
        return self.by_id.get(cid) or self.by_pgn.get(pgn_of(cid))


class CanFramesDecoder(Decoder):
    name = "can_frames"
    label = "CAN frames"
    description = (
        "Raw CAN frames as JSON, one or a list of {t, id, data, dlc}. The last 2,000 per asset "
        "are kept for the trace. Add a DBC to also turn them into named signals."
    )
    config_fields = (
        ConfigField(
            key="dbc",
            label="DBC file",
            kind="string",
            required=False,
            description="Paste or upload a DBC. Without one frames are only kept raw.",
        ),
        ConfigField(
            key="j1939",
            label="Match J1939 by PGN",
            kind="bool",
            required=False,
            description="Match on the parameter group so any source address decodes.",
            default="true",
        ),
        ConfigField(
            key="device",
            label="Part for decoded signals",
            kind="string",
            required=False,
            description="Where decoded signals are kept under the asset.",
            default="can",
        ),
    )
    stateful = False

    def _dbc(self, state: DecoderState) -> _Dbc | None:
        text = state.config.get("dbc")
        if not text:
            return None
        cached = state.data.get("dbc")
        if cached is None or cached[0] != text:
            j1939 = str(state.config.get("j1939", "true")).lower() not in (
                "false",
                "0",
                "no",
            )
            state.data["dbc"] = (text, _Dbc(text, j1939))
        return state.data["dbc"][1]

    def decode(
        self, envelope: Envelope, state: DecoderState, mapping: dict[str, Any] | None
    ) -> list[Record]:
        m = mapping or {}
        sep = m.get("subject_separator")
        segs = M._segments(envelope.subject, sep)
        if m.get("group") or m.get("node"):
            g = M.render(
                m.get("group"), {}, envelope.subject, envelope.headers, sep
            ) or (segs[0] if segs else "")
            n = M.render(
                m.get("node"), {}, envelope.subject, envelope.headers, sep
            ) or (segs[1] if len(segs) > 1 else "")
        else:
            if len(segs) < 2:
                raise DecodeError(
                    f"The subject {envelope.subject} does not name a group and an asset, such as site/machine/can/raw"
                )
            g, n = segs[0], segs[1]
        try:
            doc = json.loads(envelope.payload)
        except (TypeError, ValueError):
            raise DecodeError(
                "CAN frames must be JSON, one {t, id, data, dlc} or a list of them"
            ) from None
        items = doc if isinstance(doc, list) else [doc]
        now_ms = int(envelope.t_recv * 1000) or int(time.time() * 1000)
        frames, bad = [], 0
        for it in items[:MAX_FRAMES_PER_MESSAGE]:
            f = clean_frame(it, now_ms)
            if f is None:
                bad += 1
                continue
            frames.append(f)
        if bad:
            state.stats["bad_frames"] = state.stats.get("bad_frames", 0) + bad
        if not frames:
            raise DecodeError("None of the CAN frames had an id and hex data")
        out = [Record(group=g, node=n, kind="frame", frames=frames, ts=frames[-1]["t"])]
        dbc = self._dbc(state)
        if dbc is not None:
            latest: dict[str, Metric] = {}
            for f in frames:
                if f["id"] & ERR_FLAG:
                    continue
                msg = dbc.message(f["id"])
                if msg is None:
                    continue
                try:
                    vals = msg.decode(
                        bytes.fromhex(f["data"]), decode_choices=False, scaling=True
                    )
                except Exception:  # noqa: BLE001
                    state.stats["undecodable_frames"] = (
                        state.stats.get("undecodable_frames", 0) + 1
                    )
                    continue
                for sig in msg.signals:
                    if sig.name not in vals:
                        continue
                    v = vals[sig.name]
                    name = f"{msg.name}/{sig.name}"
                    latest[name] = Metric(
                        name=name,
                        value=float(v) if isinstance(v, (int, float)) else str(v),
                        type="number" if isinstance(v, (int, float)) else "string",
                        unit=sig.unit or None,
                        ts=f["t"],
                    )
            if latest:
                out.append(
                    Record(
                        group=g,
                        node=n,
                        device=str(state.config.get("device") or "can"),
                        kind="data",
                        metrics=list(latest.values()),
                        ts=frames[-1]["t"],
                    )
                )
        return out
