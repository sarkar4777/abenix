"""OPC UA: subscribes to (or polls) chosen nodes on a PLC or OPC UA server.

Nodes are one a line: node id[, signal name[, unit]]
    ns=3;s=SlowDouble1, Boiler/Temp_C, C
    ns=2;i=10853
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from abenix_edge.buffer import now_ms
from abenix_edge.collectors.base import Collector, retry_sleep

logging.getLogger("asyncua").setLevel(logging.WARNING)

POLICIES = ("None", "Basic256Sha256", "Aes128_Sha256_RsaOaep", "Aes256_Sha256_RsaPss")
MODES = ("None", "Sign", "SignAndEncrypt")


def parse_nodes(text: Any) -> list[tuple[str, str, str | None]]:
    out = []
    seen = set()
    rows = text if isinstance(text, list) else str(text or "").splitlines()
    for n, line in enumerate(rows, 1):
        if isinstance(line, dict):
            parts = [
                str(line.get("node_id") or ""),
                str(line.get("name") or ""),
                str(line.get("unit") or ""),
            ]
        else:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            # node ids hold ; and = but never a comma
            parts = [p.strip() for p in line.split(",")]
        nid = parts[0].strip()
        if not nid.startswith(("ns=", "i=", "s=", "g=", "b=")):
            raise ValueError(
                f"Line {n}: {nid!r} is not an OPC UA node id, such as ns=3;s=Temperature"
            )
        name = (parts[1] if len(parts) > 1 else "").strip() or nid.split(";")[-1].split(
            "=", 1
        )[-1]
        if name in seen:
            raise ValueError(
                f"Two nodes are called {name}, give one a different signal name"
            )
        seen.add(name)
        unit = (parts[2] if len(parts) > 2 else "").strip() or None
        out.append((nid, name, unit))
    if not out:
        raise ValueError(
            "Add at least one node, such as ns=3;s=SlowDouble1, Boiler/Temp_C, C"
        )
    return out


def quality(status: Any) -> str:
    try:
        if status.is_good():
            return "good"
        if status.is_uncertain():
            return "uncertain"
        return "bad"
    except Exception:  # noqa: BLE001
        return "good"


def plain_error(endpoint: str, exc: Exception) -> str:
    s = f"{type(exc).__name__}: {exc}"
    low = s.lower()
    if (
        "badidentitytokenrejected" in low
        or "baduseraccessdenied" in low
        or "badidentitytokeninvalid" in low
    ):
        return f"The OPC UA server at {endpoint} refused the user name or password."
    if (
        "badsecuritypolicyrejected" in low
        or "badsecuritymoderejected" in low
        or "certificate" in low
    ):
        return (
            f"The OPC UA server at {endpoint} refused the security settings. Pick the policy and mode the "
            "server offers, and trust this gateway's certificate on the server."
        )
    if "badnodeidunknown" in low:
        return f"A node id is not on the server at {endpoint}. Browse the server for the right ids."
    if (
        isinstance(exc, (OSError, asyncio.TimeoutError, ConnectionError))
        or "timeout" in low
    ):
        return f"Could not reach the OPC UA server at {endpoint}. Check the address and that port is open from this box."
    return f"OPC UA at {endpoint}: {s}"


class OpcuaCollector(Collector):
    type = "opcua"
    label = "OPC UA"

    def __init__(self, spec: dict[str, Any], sink: Any, gateway_id: str) -> None:
        super().__init__(spec, sink, gateway_id)
        self.endpoint = str(spec.get("endpoint") or "").strip()
        self.nodes = parse_nodes(spec.get("nodes"))
        self.mode = spec.get("read_mode") or "subscribe"
        self.policy = spec.get("security_policy") or "None"
        self.sec_mode = spec.get("security_mode") or "None"
        self.data_dir = Path(
            spec.get("_data_dir")
            or os.environ.get("ABENIX_EDGE_DATA", "/var/lib/abenix-edge")
        )

    async def _security(self, client: Any) -> None:
        if self.policy == "None" or self.sec_mode == "None":
            return
        from asyncua.crypto.cert_gen import setup_self_signed_certificate
        from asyncua.crypto.security_policies import SecurityPolicyBasic256Sha256
        from asyncua import ua
        from cryptography.x509.oid import ExtendedKeyUsageOID

        d = self.data_dir / "opcua"
        d.mkdir(parents=True, exist_ok=True)
        cert, key = d / "client-cert.der", d / "client-key.pem"
        uri = f"urn:abenix-edge:{self.node}"
        await setup_self_signed_certificate(
            key,
            cert,
            uri,
            "abenix-edge",
            [ExtendedKeyUsageOID.CLIENT_AUTH],
            {"commonName": f"abenix-edge {self.node}"},
        )
        client.application_uri = uri
        mode = getattr(ua.MessageSecurityMode, self.sec_mode)
        await client.set_security(
            SecurityPolicyBasic256Sha256, str(cert), str(key), mode=mode
        )

    async def run(self, stop: asyncio.Event) -> None:
        from asyncua import Client, ua

        attempt = 0
        while not stop.is_set():
            client = Client(url=self.endpoint, timeout=5)
            if self.spec.get("username"):
                client.set_user(self.spec["username"])
                client.set_password(self.spec.get("password") or "")
            try:
                await self._security(client)
                await client.connect()
            except Exception as exc:  # noqa: BLE001
                self.fail(plain_error(self.endpoint, exc))
                attempt += 1
                await retry_sleep(stop, attempt)
                continue
            attempt = 0
            nodes = [client.get_node(nid) for nid, _, _ in self.nodes]
            names = {
                n.nodeid: (name, unit) for n, (_, name, unit) in zip(nodes, self.nodes)
            }
            try:
                if self.mode == "subscribe":
                    me = self

                    class Handler:
                        def datachange_notification(
                            self, node: Any, val: Any, data: Any
                        ) -> None:
                            name, unit = names.get(
                                node.nodeid, (node.nodeid.to_string(), None)
                            )
                            dv = data.monitored_item.Value
                            ts = dv.SourceTimestamp or dv.ServerTimestamp
                            t = int(ts.timestamp() * 1000) if ts else now_ms()
                            v = (
                                val
                                if isinstance(val, (int, float, str, bool))
                                or val is None
                                else str(val)
                            )
                            me.emit(
                                name, v, ts=t, unit=unit, quality=quality(dv.StatusCode)
                            )

                    sub = await client.create_subscription(
                        int(self.interval * 1000), Handler()
                    )
                    await sub.subscribe_data_change(nodes, queuesize=10)
                    self.ok()
                    while not stop.is_set():
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=5)
                        except asyncio.TimeoutError:
                            await client.check_connection()
                else:
                    self.ok()
                    while not stop.is_set():
                        dvs = await client.read_attributes(nodes, ua.AttributeIds.Value)
                        rows = []
                        for (nid, name, unit), dv in zip(self.nodes, dvs):
                            v = dv.Value.Value if dv.Value is not None else None
                            if v is not None and not isinstance(
                                v, (int, float, str, bool)
                            ):
                                v = str(v)
                            rows.append((name, v, unit, quality(dv.StatusCode)))
                        self.emit_many(rows)
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=self.interval)
                        except asyncio.TimeoutError:
                            pass
            except Exception as exc:  # noqa: BLE001
                self.fail(plain_error(self.endpoint, exc) + " Reconnecting.")
            finally:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            if not stop.is_set():
                attempt += 1
                await retry_sleep(stop, attempt)
