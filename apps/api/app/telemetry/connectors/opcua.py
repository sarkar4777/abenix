"""OPC UA: subscriptions on chosen nodes of a PLC or SCADA server, with status codes kept as quality."""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

from asyncua import Client, ua
from asyncua.common.subscription import DataChangeEvent, StatusChangeEvent
from asyncua.crypto import security_policies as SP
from asyncua.crypto.uacrypto import CertProperties

from app.telemetry.connectors import _plain as P
from app.telemetry.connectors.base import (
    ConfigField,
    ConnectorError,
    Envelope,
    RunContext,
    SourceConnector,
)

logger = logging.getLogger(__name__)
# asyncua logs every publish with its whole content at info
logging.getLogger("asyncua").setLevel(logging.WARNING)

POLICIES = {
    "None": None,
    "Basic256Sha256": SP.SecurityPolicyBasic256Sha256,
    "Aes128_Sha256_RsaOaep": SP.SecurityPolicyAes128Sha256RsaOaep,
    "Aes256_Sha256_RsaPss": SP.SecurityPolicyAes256Sha256RsaPss,
}
MODES = {
    "None": ua.MessageSecurityMode.None_,
    "Sign": ua.MessageSecurityMode.Sign,
    "SignAndEncrypt": ua.MessageSecurityMode.SignAndEncrypt,
}
APP_URI = "urn:abenix:telemetry:opcua"
CONTENT_TYPE = "application/vnd.abenix.values+json"
MAX_NODES = 500
MIN_INTERVAL_MS = 100
MAX_QUEUE = 100
MAX_TEXT = 4096
MAX_ITEMS = 256
NAME_LINE = re.compile(r"^(.*?)\s+(?:=|->)\s+(.+)$")

AUTH_CODES = {
    "BadUserAccessDenied",
    "BadIdentityTokenInvalid",
    "BadIdentityTokenRejected",
    "BadUserSignatureInvalid",
    "BadIdentityChangeNotSupported",
}
DENIED_WRITE = {
    "BadUserAccessDenied",
    "BadNotWritable",
    "BadWriteNotSupported",
    "BadUserAccessDeniedForWrite",
}
CERT_CODES = {
    "BadCertificateUntrusted",
    "BadCertificateInvalid",
    "BadSecurityChecksFailed",
    "BadCertificateUriInvalid",
    "BadCertificateTimeInvalid",
    "BadCertificateHostNameInvalid",
    "BadCertificateUseNotAllowed",
    "BadCertificateRevoked",
    "BadCertificateIssuerRevoked",
}


def endpoint_of(cfg: dict[str, Any]) -> str:
    url = (cfg.get("endpoint") or "").strip()
    if not url.startswith("opc.tcp://"):
        raise ConnectorError(
            "The endpoint must start with opc.tcp://, for example opc.tcp://opc-plc.abenix-testbed.svc.cluster.local:50000"
        )
    return url


def where_of(cfg: dict[str, Any]) -> str:
    u = urlparse((cfg.get("endpoint") or "").strip().replace("opc.tcp://", "tcp://", 1))
    return f"{u.hostname or 'the server'}:{u.port or 4840}"


def asset_of(cfg: dict[str, Any]) -> str:
    if (cfg.get("asset") or "").strip():
        return cfg["asset"].strip()
    host = (
        urlparse(
            (cfg.get("endpoint") or "").replace("opc.tcp://", "tcp://", 1)
        ).hostname
        or "server"
    )
    host = (
        host.replace(".", "-")
        if host.replace(".", "").isdigit()
        else host.split(".")[0]
    )
    return f"opcua/{host}"


def node_list(cfg: dict[str, Any]) -> list[tuple[str, str | None]]:
    """(node id, signal name or None) from the Nodes field and the picked subjects."""
    out: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    raw = cfg.get("nodes") or ""
    lines = (raw if isinstance(raw, list) else str(raw).splitlines()) + P.subjects_of(
        cfg
    )
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = NAME_LINE.match(line)
        nid, name = (m.group(1).strip(), m.group(2).strip()) if m else (line, None)
        try:
            ua.NodeId.from_string(nid)
        except Exception:  # noqa: BLE001
            raise ConnectorError(
                f"{nid} is not a node id. Node ids look like ns=3;s=Temperature or ns=2;i=1001"
            ) from None
        if nid not in seen:
            seen.add(nid)
            out.append((nid, name))
    return out


def self_signed() -> tuple[bytes, bytes]:
    """A throwaway application certificate for servers that want a signed channel."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Abenix telemetry"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Abenix"),
        ]
    )
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.UniformResourceIdentifier(APP_URI)]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=True,
                data_encipherment=True,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


async def make_client(
    cfg: dict[str, Any], secrets: dict[str, Any], *, timeout: float = 10.0
) -> Client:
    client = Client(endpoint_of(cfg), timeout=timeout)
    client.application_uri = APP_URI
    client.name = "Abenix telemetry"
    client.description = "Abenix telemetry"
    user = (cfg.get("username") or "").strip()
    if user:
        client.set_user(user)
        client.set_password(secrets.get("password") or "")
    policy_name = (cfg.get("security_policy") or "None").strip()
    mode_name = (cfg.get("security_mode") or "None").strip()
    if policy_name not in POLICIES or mode_name not in MODES:
        raise ConnectorError("Pick a security policy and mode from the list")
    policy = POLICIES[policy_name]
    if (policy is None) != (mode_name == "None"):
        raise ConnectorError(
            "Security policy None goes with mode None, and any other policy needs Sign or SignAndEncrypt"
        )
    cert_pem = (cfg.get("client_cert") or "").strip().encode()
    key_pem = (secrets.get("client_key") or "").strip().encode()
    if bool(cert_pem) != bool(key_pem):
        raise ConnectorError(
            "For a client certificate, give both the certificate and its private key"
        )
    if policy is not None:
        if not cert_pem:
            cert_pem, key_pem = self_signed()
        await asyncio.wait_for(
            client.set_security(
                policy,
                CertProperties(cert_pem, extension="pem"),
                CertProperties(key_pem, extension="pem"),
                mode=MODES[mode_name],
            ),
            timeout,
        )
    if cert_pem and P.as_bool(cfg, "cert_sign_in", False):
        from asyncua.crypto import uacrypto

        client.user_certificate = await uacrypto.load_certificate(cert_pem, "pem")
        client.user_private_key = await uacrypto.load_private_key(key_pem, None, "pem")
    return client


def status_name(code: Any) -> str:
    try:
        return (
            ua.StatusCode(code).name
            if not isinstance(code, ua.StatusCode)
            else code.name
        )
    except Exception:  # noqa: BLE001
        return str(code)


def words(exc: BaseException, cfg: dict[str, Any]) -> str:
    where = where_of(cfg)
    for e in P.walk(exc):
        if isinstance(e, ConnectorError):
            return str(e)
        if isinstance(e, ua.UaStatusCodeError):
            name = status_name(e.code)
            if name in AUTH_CODES:
                return (
                    f"The OPC UA server at {where} refused the sign-in ({name}). "
                    "Check the user name and password, or whether it allows anonymous clients."
                )
            if name in CERT_CODES:
                return (
                    f"The OPC UA server at {where} does not trust Abenix's certificate ({name}). "
                    "Trust it on the server, or give a certificate the server already trusts."
                )
            if name in ("BadSecurityPolicyRejected", "BadSecurityModeRejected"):
                return f"The server at {where} does not offer that security policy and mode. Pick one it lists."
            if name in (
                "BadNodeIdUnknown",
                "BadNodeIdInvalid",
                "BadBrowseNameInvalid",
                "BadNoMatch",
            ):
                return "A node does not exist on the server. Check the node ids and the browse path."
            if name in ("BadNotWritable", "BadWriteNotSupported"):
                return "That node is read only on the server."
            if name in ("BadUserAccessDeniedForWrite", "BadNotWritableForUser"):
                return "This user may not write that node. Ask the server admin for write access."
            if name in ("BadTypeMismatch", "BadOutOfRange"):
                return f"The server would not take that value ({name}). Check its type and range."
            if name in (
                "BadTooManySessions",
                "BadTooManySubscriptions",
                "BadTooManyMonitoredItems",
            ):
                return f"The server at {where} is at its limit ({name}). Free some sessions or subscribe to fewer nodes."
            return f"The OPC UA server at {where} answered {name}."
        text = str(e)
        if "No matching endpoints" in text or "no endpoint" in text.lower():
            return f"The server at {where} does not offer that security policy and mode. Pick one it lists."
    net = P.network_words(exc, where, "OPC UA server")
    if net:
        return net
    return f"The OPC UA connection to {where} failed: {type(exc).__name__}: {exc}"[:500]


def plain_value(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return v if len(v) <= MAX_TEXT else v[:MAX_TEXT]
    if isinstance(v, (bytes, bytearray)):
        return base64.b64encode(bytes(v[:MAX_TEXT])).decode()
    if isinstance(v, dt.datetime):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [plain_value(x) for x in v[:MAX_ITEMS]]
    if isinstance(v, ua.LocalizedText):
        return v.Text
    if isinstance(v, (ua.NodeId, ua.QualifiedName)):
        return v.to_string()
    if hasattr(v, "name") and hasattr(v, "value"):
        return v.name
    return str(v)


def too_big(v: Any) -> bool:
    if isinstance(v, (str, bytes, bytearray)):
        return len(v) > MAX_TEXT
    return isinstance(v, (list, tuple)) and len(v) > MAX_ITEMS


def value_of(name: str, nid: str, dv: Any) -> dict[str, Any]:
    code = dv.StatusCode_ if hasattr(dv, "StatusCode_") else dv.StatusCode
    sc = code if isinstance(code, ua.StatusCode) else ua.StatusCode(code or 0)
    quality = "good" if sc.is_good() else "uncertain" if sc.is_uncertain() else "bad"
    when = dv.SourceTimestamp or dv.ServerTimestamp
    raw = dv.Value.Value if dv.Value is not None else None
    val = plain_value(raw)
    out = {
        "name": name,
        "value": val,
        "quality": quality,
        "status": sc.name,
        "node_id": nid,
    }
    if too_big(raw):
        # a 200 kB string or a long array is a file, not a reading
        out["status"] = f"{sc.name}, cut to {MAX_TEXT} characters or {MAX_ITEMS} items"
    if when:
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        out["ts"] = int(when.timestamp() * 1000)
    if isinstance(val, (dict, list)):
        out["type"] = "json"
    return out


async def resolve(
    client: Client, cfg: dict[str, Any]
) -> tuple[list[tuple[Any, str, str]], int]:
    """(node, node id, signal name) for the listed nodes and every variable under the browse path, with the count before the cap."""
    out: list[tuple[Any, str, str]] = []
    for nid, name in node_list(cfg):
        node = client.get_node(nid)
        if name is None:
            try:
                name = (await node.read_browse_name()).Name
            except ua.UaStatusCodeError as exc:
                raise ConnectorError(
                    f"Node {nid} does not exist on the server ({status_name(exc.code)})"
                ) from None
        out.append((node, nid, name))
    root_text = (cfg.get("browse_path") or "").strip()
    if root_text:
        root = await browse_root(client, root_text)
        found: list[tuple[Any, str, str]] = []
        await walk_variables(
            root, "", found, depth=int(cfg.get("browse_depth") or 4), cap=MAX_NODES + 1
        )
        known = {nid for _, nid, _ in out}
        out.extend(x for x in found if x[1] not in known)
    if not out:
        raise ConnectorError(
            "List at least one node id, or a browse path to subscribe under"
        )
    return out[:MAX_NODES], len(out)


async def browse_root(client: Client, text: str) -> Any:
    if text.startswith(("ns=", "i=", "s=", "g=", "b=")):
        return client.get_node(text)
    parts = [p for p in text.strip("/").split("/") if p]
    if parts and parts[0] == "Objects":
        parts = parts[1:]
    node = client.nodes.objects
    for p in parts:
        found = None
        for child in await node.get_children():
            bn = await child.read_browse_name()
            if bn.Name == p or bn.to_string() == p:
                found = child
                break
        if found is None:
            raise ConnectorError(
                f"The browse path {text} stops at {p}, which is not there. Check the path."
            )
        node = found
    return node


async def walk_variables(
    node: Any, prefix: str, out: list, depth: int, cap: int = MAX_NODES
) -> None:
    if depth < 0 or len(out) >= cap:
        return
    for child in await node.get_children(refs=ua.ObjectIds.HierarchicalReferences):
        cls = await child.read_node_class()
        name = (await child.read_browse_name()).Name
        path = f"{prefix}/{name}" if prefix else name
        if cls == ua.NodeClass.Variable:
            out.append((child, child.nodeid.to_string(), path))
        if cls in (ua.NodeClass.Object, ua.NodeClass.Variable) and depth > 0:
            await walk_variables(child, path, out, depth - 1, cap)
        if len(out) >= cap:
            return


def intervals(cfg: dict[str, Any]) -> tuple[float, float, int]:
    """Sampling and publishing interval in ms and the queue per node, held to sane bounds."""
    sampling = max(MIN_INTERVAL_MS, P.as_int(cfg, "sampling_interval_ms", 1000))
    publishing = max(MIN_INTERVAL_MS, P.as_int(cfg, "publishing_interval_ms", 1000))
    queue = min(MAX_QUEUE, max(1, P.as_int(cfg, "queue_size", 10)))
    return float(sampling), float(publishing), queue


def capped_words(total: int) -> str:
    return (
        f"{total} nodes are under the browse path, Abenix subscribes to the first {MAX_NODES}. "
        "Narrow the browse path or list the nodes you need."
    )


def plain_event(ev: Any, names: dict[str, str]) -> dict[str, Any] | None:
    """A subscription event as a plain dict, so no asyncua object outlives the publish."""
    if isinstance(ev, StatusChangeEvent):
        note = getattr(ev, "notification", None)
        code = getattr(note, "Status", note)
        sc = code if isinstance(code, ua.StatusCode) else ua.StatusCode(code or 0)
        if not sc.is_good():
            raise ConnectorError(f"The server ended the subscription ({sc.name})")
        return None
    if not isinstance(ev, DataChangeEvent):
        return None
    nid = ev.node.nodeid.to_string()
    return value_of(names.get(nid, nid), nid, ev.data.monitored_item.Value)


class OpcUaConnector(SourceConnector):
    transport = "opcua"
    label = "OPC UA"
    description = (
        "Values from a PLC or SCADA server over OPC UA. Abenix subscribes to the nodes you list or "
        "every variable under a browse path, and keeps each value's status code as its quality."
    )
    config_fields = (
        ConfigField(
            "endpoint",
            "Endpoint",
            kind="url",
            required=True,
            group="Connection",
            description="opc.tcp://host:port with any path. Example: opc.tcp://opc-plc.abenix-testbed.svc.cluster.local:50000",
        ),
        ConfigField(
            "security_policy",
            "Security policy",
            kind="select",
            group="Security",
            default="None",
            options=tuple(POLICIES),
            description="None, or the policy the server lists. Basic256Sha256 is the common one.",
        ),
        ConfigField(
            "security_mode",
            "Security mode",
            kind="select",
            group="Security",
            default="None",
            options=tuple(MODES),
            description="None with policy None, otherwise Sign or SignAndEncrypt.",
        ),
        ConfigField(
            "username",
            "User name",
            kind="string",
            group="Sign in",
            description="Leave empty to connect anonymously. Example: operator",
        ),
        ConfigField(
            "password",
            "Password",
            kind="secret",
            group="Sign in",
            description="Stored encrypted and never shown again.",
        ),
        ConfigField(
            "client_cert",
            "Client certificate",
            kind="string",
            group="Security",
            description="PEM text of the application certificate the server trusts. Empty makes a new one each connect, which the server must accept. Example: -----BEGIN CERTIFICATE----- ...",
        ),
        ConfigField(
            "client_key",
            "Client key",
            kind="secret",
            group="Security",
            description="PEM private key for the client certificate. Stored encrypted. Example: -----BEGIN PRIVATE KEY----- ...",
        ),
        ConfigField(
            "cert_sign_in",
            "Sign in with the certificate",
            kind="bool",
            group="Sign in",
            default="false",
            description="Use the client certificate as the user identity instead of a user name.",
        ),
        ConfigField(
            "nodes",
            "Nodes",
            kind="string",
            group="Reading",
            description="One node id per line, optionally = signal name. Example: ns=2;s=Line1.Speed = Line1/Speed_rpm",
        ),
        ConfigField(
            "browse_path",
            "Browse path",
            kind="string",
            group="Reading",
            description="Subscribe to every variable under this folder, by path from Objects or by node id. Example: Objects/OpcPlc/Telemetry/Basic",
        ),
        ConfigField(
            "browse_depth",
            "Browse depth",
            kind="int",
            group="Reading",
            default="4",
            description="How many folder levels under the browse path to look into.",
        ),
        ConfigField(
            "asset",
            "Asset path",
            kind="string",
            group="Reading",
            description="The subject the values arrive on, which becomes group/asset/part. Example: plant/line-1. Empty means opcua/<host>.",
        ),
        ConfigField(
            "sampling_interval_ms",
            "Sampling interval (ms)",
            kind="int",
            group="Reading",
            default="1000",
            description="How often the server samples each node.",
        ),
        ConfigField(
            "publishing_interval_ms",
            "Publishing interval (ms)",
            kind="int",
            group="Reading",
            default="1000",
            description="How often the server sends the changes it collected.",
        ),
        ConfigField(
            "queue_size",
            "Queue per node",
            kind="int",
            group="Reading",
            default="10",
            description="Changes the server keeps per node between publishes, so fast changes are not lost.",
        ),
    )
    capabilities = {"receive": "subscribe", "write": True}
    scale_mode = "lease"
    default_decoder = "values"

    async def run(self, ctx: RunContext) -> None:
        cfg, secrets = ctx.config, ctx.secrets
        sup = P.Supervisor(ctx, lambda e: words(e, cfg), "opcua")
        subject = asset_of(cfg)

        async def once() -> None:
            client = await make_client(cfg, secrets)
            try:
                await client.connect()
                nodes, total = await resolve(client, cfg)
                names = {nid: name for _, nid, name in nodes}
                sampling, publishing, queue = intervals(cfg)
                # no handler: notifications go to one queue, not one task each
                sub = await client.create_subscription(
                    ua.CreateSubscriptionParameters(
                        RequestedPublishingInterval=publishing,
                        RequestedLifetimeCount=600,
                        RequestedMaxKeepAliveCount=20,
                        MaxNotificationsPerPublish=10000,
                        PublishingEnabled=True,
                        Priority=0,
                    ),
                    None,
                    queue_maxsize=20000,
                )
                events = sub.__aiter__()
                results = await sub.subscribe_data_change(
                    [n for n, _, _ in nodes],
                    sampling_interval=sampling,
                    queuesize=queue,
                )
                bad = [
                    nodes[i][1] for i, r in enumerate(results) if not isinstance(r, int)
                ]
                if len(bad) == len(nodes):
                    raise ConnectorError(
                        f"None of the nodes could be subscribed, for example {bad[0]}. Check the node ids."
                    )
                sup.connected()
                notes = []
                if total > MAX_NODES:
                    notes.append(capped_words(total))
                if bad:
                    notes.append(
                        f"{len(bad)} node(s) could not be subscribed, for example {bad[0]}."
                    )
                if notes:
                    ctx.set_status("connected", " ".join(notes))
                headers = {
                    "content-type": CONTENT_TYPE,
                    "opcua.endpoint": endpoint_of(cfg),
                }

                async def pump() -> None:
                    q = getattr(sub, "_event_queue", None)
                    async for ev in events:
                        batch = []
                        v = plain_event(ev, names)
                        if v is not None:
                            batch.append(v)
                        # one envelope for everything the publish brought
                        while q is not None and not q.empty() and len(batch) < 5000:
                            nxt = q.get_nowait()
                            if nxt is None:
                                break
                            v = plain_event(nxt, names)
                            if v is not None:
                                batch.append(v)
                        if not batch:
                            continue
                        await ctx.emit(
                            Envelope(
                                connection_id=ctx.connection_id,
                                tenant=ctx.tenant,
                                subject=subject,
                                payload=json.dumps(
                                    {"ts": P.now_ms(), "values": batch}, default=str
                                ).encode(),
                                headers=dict(headers),
                                t_recv=time.time(),
                            )
                        )

                async def watchdog() -> None:
                    state = client.get_node(ua.ObjectIds.Server_ServerStatus_State)
                    while True:
                        await asyncio.sleep(5)
                        await asyncio.wait_for(state.read_value(), 10)

                await P.until_stopped(ctx, pump(), watchdog())
            finally:
                try:
                    await asyncio.wait_for(client.disconnect(), 5)
                except Exception:  # noqa: BLE001
                    pass

        await sup.run(once)

    async def test(
        self, cfg: dict[str, Any], secrets: dict[str, Any]
    ) -> dict[str, Any]:
        deadline = time.monotonic() + 5.0
        out = P.result()
        client = None
        try:
            client = await make_client(cfg, secrets, timeout=4)
            await asyncio.wait_for(client.connect(), P.deadline_left(deadline))
            out["connected"] = True
            nodes, total = await asyncio.wait_for(
                resolve(client, cfg), P.deadline_left(deadline)
            )
            out["node_count"] = total
            if total > MAX_NODES:
                out["note"] = capped_words(total)
            values = []
            for node, nid, name in nodes[:50]:
                dv = await asyncio.wait_for(
                    node.read_attribute(ua.AttributeIds.Value),
                    P.deadline_left(deadline),
                )
                values.append(value_of(name, nid, dv))
            out["messages"] = len(values)
            out["subjects_seen"] = [n for _, n, _ in nodes[:50]]
            out["sample"] = json.dumps({"values": values[:10]}, default=str)[
                : P.SAMPLE_MAX
            ]
            out["ok"] = True
        except Exception as exc:  # noqa: BLE001
            out["error"] = P.scrub(words(exc, cfg), secrets)
        finally:
            if client is not None:
                try:
                    await asyncio.wait_for(client.disconnect(), 2)
                except Exception:  # noqa: BLE001
                    pass
        return out

    async def write(
        self,
        cfg: dict[str, Any],
        secrets: dict[str, Any],
        target: dict[str, Any],
        value: Any,
    ) -> dict[str, Any]:
        nid = str(target.get("node_id") or "").strip()
        if not nid:
            raise ConnectorError(
                "The command has no node id to write. Set one on the writable signal."
            )
        client = None
        try:
            client = await make_client(cfg, secrets)
            await client.connect()
            node = client.get_node(nid)
            vtype = await node.read_data_type_as_variant_type()
            v = coerce(value if target.get("value") is None else target["value"], vtype)
            try:
                await node.write_attribute(
                    ua.AttributeIds.Value, ua.DataValue(ua.Variant(v, vtype))
                )
            except ua.UaStatusCodeError as exc:
                name = status_name(exc.code)
                # signed in by now, so an access refusal is about this node
                if name in DENIED_WRITE:
                    raise ConnectorError(
                        f"The server would not let Abenix write {nid} ({name}). "
                        "It is read only, or this user may not write it."
                    ) from None
                raise
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(P.scrub(words(exc, cfg), secrets)) from None
        finally:
            if client is not None:
                try:
                    await asyncio.wait_for(client.disconnect(), 3)
                except Exception:  # noqa: BLE001
                    pass
        return {"published": True, "at": P.iso_now(), "node_id": nid}


def coerce(value: Any, vtype: Any) -> Any:
    """The command's value as the node's own type, in plain words when it does not fit."""
    V = ua.VariantType
    try:
        if vtype == V.Boolean:
            if isinstance(value, str):
                low = value.strip().lower()
                if low not in ("true", "false", "1", "0", "on", "off", "yes", "no"):
                    raise ValueError
                return low in ("true", "1", "on", "yes")
            return bool(value)
        if vtype in (
            V.SByte,
            V.Byte,
            V.Int16,
            V.UInt16,
            V.Int32,
            V.UInt32,
            V.Int64,
            V.UInt64,
        ):
            f = float(value)
            if f != int(f):
                raise ValueError
            return int(f)
        if vtype in (V.Float, V.Double):
            return float(value)
        if vtype == V.String:
            return value if isinstance(value, str) else json.dumps(value)
    except (TypeError, ValueError):
        raise ConnectorError(
            f"{value!r} does not fit this node, which takes {vtype.name}"
        ) from None
    return value
