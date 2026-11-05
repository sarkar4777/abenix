"""The in-cluster half of scripts/edge-e2e.sh. One subcommand per step, a plain line and exit 1 on failure."""

from __future__ import annotations

import hashlib
import io
import json
import os
import secrets as pysecrets
import sys
import tarfile
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

WORK = Path(os.environ.get("E2E_WORK", "/tmp/e2e"))
API = os.environ.get("E2E_API", "http://abenix-api.abenix.svc.cluster.local:8000")
BROKER = os.environ.get("E2E_BROKER", "abenix-mosquitto.abenix.svc.cluster.local")
BROKER_PORT = int(os.environ.get("E2E_BROKER_PORT", "1883"))
UPLINK = os.environ.get(
    "E2E_UPLINK", "http://e2e-uplink.abenix.svc.cluster.local:18001"
)
MODEL = os.environ.get("E2E_MODEL", "claude-haiku-4-5")
TIMEOUT = 40.0


class Fail(Exception):
    pass


def jdump(o: Any) -> str:
    return json.dumps(o, separators=(",", ":"), default=str)


def secret(name: str) -> str:
    return (WORK / "secrets" / name).read_text().strip()


def login() -> str:
    env = json.loads((WORK / "env.json").read_text())
    r = httpx.post(
        f"{API}/api/auth/login",
        json={"email": env["email"], "password": env["password"]},
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise Fail(
            f"could not sign in to the platform as {env['email']}, HTTP {r.status_code}"
        )
    tok = r.json()["data"]["access_token"]
    (WORK / "token").write_text(tok)
    return tok


def api(method: str, path: str, **kw: Any) -> httpx.Response:
    tok_file = WORK / "token"
    tok = tok_file.read_text() if tok_file.exists() else login()
    for attempt in (1, 2):
        r = httpx.request(
            method,
            API + path,
            headers={"Authorization": f"Bearer {tok}"},
            timeout=kw.pop("timeout", TIMEOUT),
            **kw,
        )
        if r.status_code != 401 or attempt == 2:
            return r
        tok = login()
    return r


def data_of(r: httpx.Response, what: str) -> Any:
    if r.status_code >= 300:
        raise Fail(f"{what} answered {r.status_code} {r.text[:300]}")
    return r.json()["data"]


def track(kind: str, value: str) -> None:
    path = WORK / "created.json"
    seen = json.loads(path.read_text()) if path.exists() else {}
    seen.setdefault(kind, []).append(value)
    path.write_text(json.dumps(seen))


# Platform steps


def cmd_save_secret(name: str) -> None:
    path = WORK / "secrets" / name
    path.write_text(sys.stdin.read())
    path.chmod(0o600)


def cmd_save_env() -> None:
    path = WORK / "env.json"
    path.write_text(sys.stdin.read())
    path.chmod(0o600)


def cmd_ready() -> None:
    d = data_of(api("GET", "/api/edge/runtime/download"), "the edge API")
    if "auth_token" not in d["variants"][0]["helm_install"]:
        raise Fail(
            "the API pod runs edge code from before this change. Roll it first with bash scripts/deploy.sh reload api"
        )
    print("ok")


def cmd_signing_key() -> None:
    print(
        data_of(api("GET", "/api/edge/signing-key"), "the signing key")[
            "public_key_pem"
        ]
    )


def cmd_mint(name: str) -> None:
    print(
        data_of(
            api("POST", "/api/edge/tokens/mint", json={"name": name}), "token mint"
        )["platform_token"]
    )


def cmd_agent(name: str, tools: str, max_runtime: str) -> None:
    body = {
        "name": name,
        "description": "Edge end to end test agent",
        "system_prompt": "You are an edge test agent. Follow the user's instruction exactly.",
        "model_config": {
            "model": MODEL,
            "temperature": 0.0,
            "max_tokens": 64,
            "max_iterations": 1,
            "tools": [t for t in tools.split(",") if t],
            "edge_compatible": True,
            "edge_constraints": {
                "max_payload_bytes": 4096,
                "max_runtime_seconds": int(max_runtime),
            },
        },
    }
    d = data_of(api("POST", "/api/agents", json=body), "creating an agent")
    a = d.get("agent") or d
    track("agents", a["id"])
    print(a["id"])


def _members(bundle: bytes) -> dict[str, bytes]:
    out = {}
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:") as tar:
        for m in tar:
            f = tar.extractfile(m)
            out[m.name] = f.read() if f else b""
    return out


def cmd_compile(agent_id: str, name: str) -> None:
    r = api("POST", f"/api/edge/agents/{agent_id}/compile")
    if r.status_code != 200:
        raise Fail(f"compile answered {r.status_code} {r.text[:300]}")
    bundle = r.content
    (WORK / name).write_bytes(bundle)
    if hashlib.sha256(bundle).hexdigest() != r.headers.get("x-bundle-digest"):
        raise Fail("the digest header does not match the bundle bytes")
    m = _members(bundle)
    missing = {"agent.yaml", "system_prompt.md", "signature.sig"} - set(m)
    if missing:
        raise Fail(f"the bundle misses {sorted(missing)}")
    if len(m["signature.sig"]) < 256:
        raise Fail("the signature is too short to be real")
    man = yaml.safe_load(m["agent.yaml"])
    print(f"{man['slug']} {man.get('tenant_id') or ''} {r.headers['x-bundle-digest']}")


def cmd_find_gw(gateway_id: str, timeout: str) -> None:
    end = time.time() + float(timeout)
    while True:
        gws = data_of(api("GET", "/api/edge/gateways"), "the gateway list")["gateways"]
        g = next((x for x in gws if x["gateway_id"] == gateway_id), None)
        if g and g["status"] == "online":
            track("gateways", g["id"])
            print(g["id"])
            return
        if time.time() > end:
            raise Fail(
                f"gateway {gateway_id} is not online on the platform after {timeout} s, it is {g['status'] if g else 'absent'}"
            )
        time.sleep(3)


def cmd_register_gw(gateway_id: str, endpoint: str) -> None:
    d = data_of(
        api(
            "POST",
            "/api/edge/gateways/register",
            json={
                "gateway_id": gateway_id,
                "name": gateway_id,
                "endpoint_url": endpoint,
            },
        ),
        "registering a gateway",
    )
    track("gateways", d["gateway"]["id"])
    print(d["gateway"]["id"])


def cmd_set_push(pk: str, token_name: str) -> None:
    data_of(
        api(
            "PATCH", f"/api/edge/gateways/{pk}", json={"push_token": secret(token_name)}
        ),
        "setting the push token",
    )
    print("ok")


def cmd_deploy(pk: str, agent_id: str, expr: str) -> None:
    r = api(
        "POST",
        f"/api/edge/gateways/{pk}/deploy",
        json={"agent_id": agent_id},
        timeout=60.0,
    )
    body = r.json()
    d = body.get("data") or (body.get("error") or {}).get("details") or {}
    if not d:
        raise Fail(f"deploy answered {r.status_code} {r.text[:300]}")
    d["_status"] = r.status_code
    if not eval(expr, {}, {"d": d}):  # noqa: S307
        brief = {
            k: d.get(k)
            for k in (
                "_status",
                "deployed",
                "delivered_via",
                "queued",
                "gateway_reachable",
                "message",
            )
        }
        brief["mqtt_error"] = (d.get("mqtt") or {}).get("error")
        brief["http_status"] = (d.get("http") or {}).get("status")
        raise Fail(f"deploy did not hold {expr}, got {jdump(brief)}")
    print(d["bundle_digest"])


def _wait_gw(pk: str, expr: str, timeout: float) -> dict[str, Any]:
    end = time.time() + timeout
    g: dict[str, Any] = {}
    while True:
        g = data_of(api("GET", f"/api/edge/gateways/{pk}"), "the gateway")
        try:
            if eval(expr, {}, {"g": g}):  # noqa: S307
                return g
        except (KeyError, TypeError, IndexError):
            pass
        if time.time() > end:
            brief = {
                k: g.get(k)
                for k in (
                    "status",
                    "enrolled_at",
                    "last_seen_at",
                    "problem",
                    "uplink",
                    "collector_health",
                )
            }
            raise Fail(
                f"gateway did not reach {expr} in {timeout:g} s, it shows {jdump(brief)[:900]}"
            )
        time.sleep(3)


def cmd_gw_wait(pk: str, expr: str, timeout: str) -> None:
    g = _wait_gw(pk, expr, float(timeout))
    print(g.get("gateway_id"))


# Gateway under direct test


def _auth(token_name: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret(token_name)}"} if token_name else {}


def cmd_wait_up(base: str) -> None:
    if httpx.get(f"{base}/health", timeout=3.0).status_code != 200:
        raise Fail("not healthy yet")
    print("ok")


def cmd_agents(base: str, slug: str, digest: str) -> None:
    rows = httpx.get(f"{base}/agents", timeout=TIMEOUT).json()["agents"]
    row = next((a for a in rows if a["slug"] == slug), None)
    if not row:
        raise Fail(
            f"{slug} is not loaded, the gateway lists {[a['slug'] for a in rows]}"
        )
    if digest != "-" and row["digest"] != digest:
        raise Fail(f"{slug} has digest {row['digest'][:16]}, wanted {digest[:16]}")
    print("ok")


def cmd_wait_agent(base: str, slug: str, digest: str, timeout: str) -> None:
    end = time.time() + float(timeout)
    err = ""
    while time.time() < end:
        try:
            cmd_agents(base, slug, digest)
            return
        except (Fail, httpx.HTTPError, ValueError, KeyError) as e:
            err = str(e)
        time.sleep(2)
    raise Fail(f"agent did not arrive in {timeout} s, {err}")


def cmd_push(base: str, slug: str, file: str, token_name: str, want: str) -> None:
    r = httpx.post(
        f"{base}/agents/{slug}/bundle",
        content=(WORK / file).read_bytes() if (WORK / file).exists() else b"",
        headers=_auth(None if token_name == "-" else token_name),
        timeout=TIMEOUT,
    )
    if str(r.status_code) != want:
        raise Fail(f"install answered {r.status_code}, wanted {want}, {r.text[:300]}")
    print("ok")


def cmd_ask(base: str, token_name: str, slug: str) -> None:
    word = "ZEBRA" + pysecrets.token_hex(3).upper()
    r = httpx.post(
        f"{base}/agents/{slug}/execute",
        json={"message": f"Reply with exactly this word and nothing else {word}"},
        headers=_auth(token_name),
        timeout=120.0,
    )
    if r.status_code != 200:
        raise Fail(f"execute answered {r.status_code} {r.text[:300]}")
    res = r.json().get("result") or {}
    if not res.get("ok"):
        raise Fail(f"no model answer, {str(res.get('error'))[:300]}")
    if word not in (res.get("text") or ""):
        raise Fail(
            f"the model answered but not with the word asked for, {str(res.get('text'))[:120]}"
        )
    print("ok")


def cmd_exec_alive(base: str, token_name: str, slug: str) -> None:
    r = httpx.post(
        f"{base}/agents/{slug}/execute",
        json={"message": "hello"},
        headers=_auth(token_name),
        timeout=120.0,
    )
    if r.status_code != 200 or r.json().get("slug") != slug:
        raise Fail(f"execute answered {r.status_code} {r.text[:300]}")
    print("ok")


def cmd_auth_rotated(base: str, old: str, new: str, slug: str) -> None:
    for name, want in ((old, 401), (new, 200)):
        r = httpx.post(
            f"{base}/agents/{slug}/execute",
            json={"message": "hi"},
            headers=_auth(name),
            timeout=120.0,
        )
        if r.status_code != want:
            label = "the old" if want == 401 else "the new"
            raise Fail(f"{label} token got {r.status_code}, wanted {want}")
    print("ok")


# Bundles signed with a test key, for the refusals a platform bundle cannot show


def _tar(members: list) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for m in members:
            if isinstance(m, tarfile.TarInfo):
                tar.addfile(m)
                continue
            info = tarfile.TarInfo(name=m[0])
            info.size = len(m[1])
            info.mtime = int(time.time())
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(m[1]))
    return out.getvalue()


def _strip(bundle: bytes) -> bytes:
    off = 0
    while off + 512 <= len(bundle):
        h = bundle[off : off + 512]
        if not any(h):
            break
        size = int(h[124:136].replace(b"\0", b" ").strip() or b"0", 8)
        end = off + 512 + -(-size // 512) * 512
        if h[:100].split(b"\0", 1)[0] == b"signature.sig":
            return bundle[:off] + bundle[end:]
        off = end
    return bundle


def _sign(members: list, key: rsa.RSAPrivateKey | None) -> bytes:
    if key is None:
        return _tar(members)
    framed = _tar(members + [("signature.sig", bytes(key.key_size // 8))])
    sig = key.sign(
        _strip(framed),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )
    at = framed.index(b"signature.sig") + 512
    return framed[:at] + sig + framed[at + len(sig) :]


def _manifest(
    slug: str, tenant: str, tools: list[str] | None = None, runtime: int = 2
) -> bytes:
    return yaml.safe_dump(
        {
            "name": "Refusal test",
            "slug": slug,
            "tenant_id": tenant,
            "version": "1.0.0",
            "model": MODEL,
            "temperature": 0.0,
            "max_iterations": 1,
            "max_tokens": 16,
            "tools": tools if tools is not None else ["current_time"],
            "edge_constraints": {
                "max_payload_bytes": 4096,
                "max_runtime_seconds": runtime,
            },
        },
        sort_keys=True,
    ).encode()


def _test_key() -> rsa.RSAPrivateKey:
    path = WORK / "test_key.pem"
    if not path.exists():
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        path.write_bytes(
            k.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def cmd_test_key() -> None:
    pub = (
        _test_key()
        .public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    print(pub.decode())


def cmd_suite(base: str, token_name: str, tenant: str, slug: str) -> None:
    """One line per check, a tab, then ok or what went wrong. Runs against a pod that trusts the test key."""
    key = _test_key()
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    auth = _auth(token_name)
    results: list[tuple[str, str]] = []

    def good(s: str = slug, t: str = tenant, **kw: Any) -> list:
        return [
            ("agent.yaml", _manifest(s, t, **kw)),
            ("system_prompt.md", b"You are a test agent."),
        ]

    def post(path: str, body: bytes, headers: dict[str, str]) -> httpx.Response:
        return httpx.post(
            f"{base}{path}", content=body, headers=headers, timeout=TIMEOUT
        )

    def refused(name: str, url_slug: str, bundle: bytes, text: str) -> None:
        r = post(f"/agents/{url_slug}/bundle", bundle, auth)
        if r.status_code != 400:
            results.append(
                (name, f"answered {r.status_code}, wanted 400, {r.text[:200]}")
            )
        elif text not in r.text:
            results.append((name, f"refused for another reason, {r.text[:200]}"))
        else:
            results.append((name, "ok"))

    h = httpx.get(f"{base}/health", timeout=TIMEOUT)
    results.append(
        (
            "health_open_without_token",
            "ok" if h.status_code == 200 else f"answered {h.status_code}",
        )
    )

    bundle = _sign(good(), key)
    for name, headers in (
        ("install_refused_without_token", {}),
        ("install_refused_wrong_token", {"Authorization": "Bearer wrong"}),
    ):
        r = post(f"/agents/{slug}/bundle", bundle, headers)
        results.append(
            (
                name,
                (
                    "ok"
                    if r.status_code == 401
                    else f"answered {r.status_code}, wanted 401"
                ),
            )
        )

    r = post(f"/agents/{slug}/bundle", bundle, auth)
    ok = r.status_code == 200
    results.append(
        (
            "signed_bundle_installs",
            "ok" if ok else f"answered {r.status_code} {r.text[:200]}",
        )
    )
    digest = hashlib.sha256(bundle).hexdigest()

    for name, headers in (
        ("execute_refused_without_token", {}),
        ("execute_refused_wrong_token", {"Authorization": "Bearer wrong"}),
    ):
        r = post(f"/agents/{slug}/execute", b'{"message":"hi"}', headers)
        results.append(
            (
                name,
                (
                    "ok"
                    if r.status_code == 401
                    else f"answered {r.status_code}, wanted 401"
                ),
            )
        )

    tampered = bytearray(bundle)
    at = bytes(tampered).index(b"You are a test agent.")
    tampered[at] ^= 1
    refused("tampered_refused", slug, bytes(tampered), "signature")
    refused("wrong_key_refused", slug, _sign(good(), other), "signature")
    refused(
        "wrong_tenant_refused",
        "e2e-foreign",
        _sign(good("e2e-foreign", "another-tenant"), key),
        "tenant",
    )
    refused(
        "unsigned_refused",
        "e2e-unsigned",
        _sign(good("e2e-unsigned"), None),
        "unsigned",
    )
    refused(
        "traversal_slug_refused",
        "e2e-evil",
        _sign(good("../../../../tmp/e2e-evil"), key),
        "slug",
    )
    refused("slug_mismatch_refused", "e2e-other", _sign(good(), key), "sent to")
    refused(
        "traversal_member_refused",
        "e2e-member",
        _sign(good("e2e-member") + [("../../../tmp/e2e-evil", b"owned")], key),
        "unsafe path",
    )
    link = tarfile.TarInfo("link")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    refused(
        "symlink_member_refused",
        "e2e-link",
        _sign(good("e2e-link") + [link], key),
        "link or device",
    )

    r = post("/agents/..%2f..%2fetc/bundle", bundle, auth)
    results.append(
        (
            "traversal_url_refused",
            "ok" if r.status_code in (400, 404) else f"answered {r.status_code}",
        )
    )

    rows = httpx.get(f"{base}/agents", timeout=TIMEOUT).json()["agents"]
    slugs = sorted(a["slug"] for a in rows)
    held = next((a for a in rows if a["slug"] == slug), None)
    results.append(
        (
            "refused_bundles_change_nothing",
            (
                "ok"
                if slugs == [slug] and held and held["digest"] == digest
                else f"gateway lists {slugs}"
            ),
        )
    )

    # the code path needs an agent that lists the tool, or the whitelist answers first
    coder = _sign(good("e2e-coder", tools=["code_executor"]), key)
    post("/agents/e2e-coder/bundle", coder, auth)
    r = post(
        "/agents/e2e-coder/execute",
        json.dumps({"message": "", "params": {"code": "print(6*7)"}}).encode(),
        auth,
    )
    res = r.json().get("result") or {}
    results.append(
        (
            "params_code_off_by_default",
            (
                "ok"
                if res.get("ok") is False and "off" in str(res.get("error"))
                else f"got {jdump(res)[:200]}"
            ),
        )
    )

    t0 = time.time()
    r = post(f"/agents/{slug}/execute", b'{"message":"hi"}', auth)
    took = time.time() - t0
    res = r.json().get("result") or {}
    results.append(
        (
            "max_runtime_seconds_enforced",
            (
                "ok"
                if res.get("ok") is False and took < 8
                else f"took {took:.1f} s against a 2 s limit, {jdump(res)[:200]}"
            ),
        )
    )
    for name, msg in results:
        print(f"{name}\t{msg}")
    print(f"digest\t{digest}")


# MQTT


def cmd_mqtt_retained(gateway_id: str, slug: str, digest: str) -> None:
    import paho.mqtt.client as mqtt

    got: dict[str, Any] = {}
    ev = threading.Event()

    def on_connect(c: Any, _u: Any, _f: Any, rc: Any, _p: Any = None) -> None:
        c.subscribe(f"edge/{gateway_id}/deploy/{slug}", qos=1)

    def on_message(_c: Any, _u: Any, msg: Any) -> None:
        got.update(
            retain=msg.retain,
            qos=msg.qos,
            digest=hashlib.sha256(msg.payload).hexdigest(),
        )
        ev.set()

    c = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=f"e2e-{pysecrets.token_hex(4)}"
    )
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(BROKER, BROKER_PORT, 30)
    c.loop_start()
    ev.wait(15)
    c.loop_stop()
    c.disconnect()
    if not got:
        raise Fail("the broker holds no retained bundle for this agent")
    if not got["retain"] or got["qos"] != 1:
        raise Fail(
            f"bundle arrived with retain {got['retain']} and QoS {got['qos']}, wanted retained at QoS 1"
        )
    if digest != "-" and got["digest"] != digest:
        raise Fail("the retained bundle is not the one deployed")
    print("ok")


def cmd_mqtt_send(
    gateway_id: str, slug: str, tenant: str, want: str, wait_ack: str
) -> None:
    """A test-key bundle, QoS 1 and retained, then the gateway's answer when it is online."""
    import paho.mqtt.client as mqtt

    bundle = _sign(
        [
            ("agent.yaml", _manifest(slug, tenant)),
            ("system_prompt.md", b"You are a test agent."),
        ],
        _test_key(),
    )
    digest = hashlib.sha256(bundle).hexdigest()
    (WORK / f"mqtt-{slug}.digest").write_text(digest)
    acks: list[dict[str, Any]] = []
    subscribed = threading.Event()
    answered = threading.Event()

    def on_connect(c: Any, _u: Any, _f: Any, rc: Any, _p: Any = None) -> None:
        c.subscribe(f"edge/{gateway_id}/ack/{slug}", qos=1)

    def on_message(_c: Any, _u: Any, msg: Any) -> None:
        a = json.loads(msg.payload)
        if a.get("digest") == digest:
            acks.append(a)
            answered.set()

    c = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=f"e2e-{pysecrets.token_hex(4)}"
    )
    c.on_connect = on_connect
    c.on_subscribe = lambda *_a: subscribed.set()
    c.on_message = on_message
    c.connect(BROKER, BROKER_PORT, 30)
    c.loop_start()
    subscribed.wait(10)
    c.publish(
        f"edge/{gateway_id}/deploy/{slug}", bundle, qos=1, retain=True
    ).wait_for_publish(10)
    if wait_ack == "yes":
        answered.wait(20)
    c.loop_stop()
    c.disconnect()
    if wait_ack != "yes":
        print(digest)
        return
    if not acks:
        raise Fail("the gateway sent no answer over MQTT in 20 s")
    if str(bool(acks[0].get("ok"))).lower() != want:
        raise Fail(f"the gateway answered {jdump(acks[0])[:300]}, wanted ok {want}")
    print(digest)


def cmd_mqtt_publish(topic: str, count: str) -> None:
    import paho.mqtt.client as mqtt

    c = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=f"e2e-{pysecrets.token_hex(4)}"
    )
    c.connect(BROKER, BROKER_PORT, 30)
    c.loop_start()
    for i in range(int(count)):
        c.publish(topic, json.dumps({"temp_c": 20 + i}), qos=1).wait_for_publish(5)
        time.sleep(1)
    c.loop_stop()
    c.disconnect()
    print("ok")


# Gateway mode through the platform


def cmd_gw_create() -> None:
    conf = json.load(sys.stdin)
    run, group = conf["run"], conf["group"]
    can = {
        "interface": "socketcand",
        "host": "127.0.0.1",
        "port": 29536,
        "channel": "vcan0",
        "bitrate": "250000",
    }
    collectors: list[dict[str, Any]] = [
        {
            "type": "can",
            "name": "j1939",
            **can,
            "protocol": "j1939",
            "request_pgns": "65253, 65260",
            "request_every_s": 10,
            "asset": {"group": group, "node": "truck-j"},
            "interval_s": 2,
        },
        {
            "type": "can",
            "name": "obd2",
            **can,
            "protocol": "obd2",
            "obd_pids": "0C, 0D, 05",
            "asset": {"group": group, "node": "truck-o"},
            "interval_s": 2,
        },
        {
            "type": "nmea_gps",
            "name": "gps",
            "port": "tcp://127.0.0.1:10110",
            "asset": {"group": group, "node": "truck-g", "device": "gps"},
            "interval_s": 2,
        },
        {
            "type": "mqtt_bridge",
            "name": "bridge",
            "broker": f"mqtt://{BROKER}:{BROKER_PORT}",
            "topics": f"e2e/{run}/#",
            "asset": {"group": group, "node": "sens", "device": "bridge"},
            "interval_s": 1,
        },
        {
            "type": "file_tail",
            "name": "seq",
            "path": "/var/lib/abenix-edge/e2e/seq*.csv",
            "format": "csv",
            "from_start": True,
            "asset": {"group": group, "node": "log", "device": "csv"},
            "interval_s": 1,
        },
        {
            "type": "file_tail",
            "name": "bulk",
            "path": "/var/lib/abenix-edge/e2e/bulk*.csv",
            "format": "csv",
            "from_start": True,
            "asset": {"group": group, "node": "bulk", "device": "fill"},
            "interval_s": 1,
        },
    ]
    if conf.get("testbed"):
        ns = conf.get("testbed_ns", "abenix-testbed")
        collectors += [
            {
                "type": "modbus",
                "name": "meter",
                "mode": "tcp",
                "host": f"meter.{ns}.svc.cluster.local",
                "port": 502,
                "unit_id": 1,
                "registers": "voltage_v, holding, 0, float32, 1, V\nfrequency_hz, holding, 8, uint16, 0.01, Hz",
                "asset": {"group": group, "node": "meter-1", "device": "main"},
                "interval_s": 2,
            },
            {
                "type": "opcua",
                "name": "plc",
                "endpoint": f"opc.tcp://opc-plc.{ns}.svc.cluster.local:50000",
                "username": "abenix",
                "password": conf.get("opcua_password", ""),
                "nodes": "ns=3;s=StepUp, Counters/StepUp",
                "read_mode": "subscribe",
                "asset": {"group": group, "node": "plc", "device": "plc"},
                "interval_s": 1,
            },
        ]
    body = {
        "name": f"e2e gateway {run}",
        "roles": ["collect", "agents"],
        "collectors": collectors,
        "settings": {
            "heartbeat_s": 5,
            "self_metrics_s": 2,
            "buffer_max_age_h": 72,
            "buffer_max_mb": 16,
            "gzip": True,
        },
    }
    g = data_of(api("POST", "/api/edge/gateways", json=body), "creating the gateway")
    track("gateways", g["id"])
    print(f"{g['id']} {g['gateway_id']}")


def cmd_gw_install(pk: str, url: str) -> None:
    d = data_of(
        api("POST", f"/api/edge/gateways/{pk}/install", json={"platform_url": url}),
        "the install step",
    )
    print(d["enroll_token"])


def cmd_enroll_refused(token_name: str) -> None:
    r = httpx.post(
        f"{API}/api/edge/enroll", json={"token": secret(token_name)}, timeout=TIMEOUT
    )
    if r.status_code not in (401, 410):
        raise Fail(f"a used enrolment token got {r.status_code}, wanted 401")
    print("ok")


def cmd_key_refused(token_name: str) -> None:
    r = httpx.post(
        f"{API}/api/edge/heartbeat",
        json={"gateway_id": "x"},
        headers={"Authorization": f"Bearer {secret(token_name)}"},
        timeout=TIMEOUT,
    )
    if r.status_code != 401:
        raise Fail(f"the old gateway key got {r.status_code}, wanted 401")
    print("ok")


def cmd_gw_revoke(pk: str) -> None:
    data_of(api("POST", f"/api/edge/gateways/{pk}/revoke"), "revoking the gateway")
    print("ok")


def cmd_devices(group: str, node: str, timeout: str) -> None:
    end = time.time() + float(timeout)
    rows: list[dict[str, Any]] = []
    while time.time() < end:
        rows = data_of(
            api("GET", "/api/telemetry/devices", params={"group": group, "node": node}),
            "telemetry devices",
        )
        if any((r.get("metric_count") or 0) > 0 for r in rows):
            print("ok")
            return
        time.sleep(3)
    raise Fail(f"no readings reached telemetry for {group}/{node} in {timeout} s")


def _history(
    group: str, node: str, device: str, metric: str, t0: float, t1: float
) -> list[dict[str, Any]]:
    r = api(
        "GET",
        "/api/telemetry/history",
        params={
            "group": group,
            "node": node,
            "device": device,
            "metric": metric,
            "from": str(int(t0)),
            "to": str(int(t1)),
            "step": "1s",
        },
    )
    if r.status_code == 404:
        return []
    d = data_of(r, "telemetry history")
    series = d.get("series") or d.get("metrics") or d
    if isinstance(series, dict):
        series = series.get(metric) or []
    elif (
        isinstance(series, list)
        and series
        and isinstance(series[0], dict)
        and "points" in series[0]
    ):
        series = next((s["points"] for s in series if s.get("metric") == metric), [])
    return series or []


def _values(points: list[dict[str, Any]]) -> list[int]:
    out = []
    for p in points:
        v = (
            p.get("max")
            if p.get("max") is not None
            else p.get("avg") if p.get("avg") is not None else p.get("v")
        )
        if v is not None:
            out.append(int(round(v)))
    return out


def cmd_expect_seq(
    group: str,
    node: str,
    device: str,
    metric: str,
    t0: str,
    t1: str,
    first: str,
    last: str,
    timeout: str,
) -> None:
    want = list(range(int(first), int(last) + 1))
    end = time.time() + float(timeout)
    vals: list[int] = []
    while True:
        vals = _values(_history(group, node, device, metric, float(t0), float(t1)))
        if vals == want:
            print(jdump({"points": len(vals), "first": vals[0], "last": vals[-1]}))
            return
        if time.time() > end:
            missing = sorted(set(want) - set(vals))
            extra = [v for v in vals if v not in set(want)]
            raise Fail(
                f"got {len(vals)} of {len(want)} readings after {timeout} s, missing {missing[:12]}, unexpected {extra[:12]}, in order {vals == sorted(vals)}"
            )
        time.sleep(4)


def cmd_edge_seq(gateway_id: str, t0: str, t1: str, timeout: str) -> None:
    end = time.time() + float(timeout)
    while True:
        vals = _values(
            _history("edge", gateway_id, "gateway", "Edge/Seq", float(t0), float(t1))
        )
        gaps = [(a, b) for a, b in zip(vals, vals[1:]) if b != a + 1]
        if len(vals) >= 2 and not gaps:
            print(jdump({"points": len(vals), "first": vals[0], "last": vals[-1]}))
            return
        if time.time() > end:
            raise Fail(
                f"{len(vals)} Edge/Seq points, {len(gaps)} gaps or repeats, first ones {gaps[:6]}"
            )
        time.sleep(4)


def cmd_uplink(action: str) -> None:
    path = "/cut?seconds=3600" if action == "cut" else "/restore"
    r = httpx.post(UPLINK + path, timeout=TIMEOUT)
    if r.status_code != 200:
        raise Fail(f"the uplink relay answered {r.status_code}")
    print("ok")


def cmd_cleanup() -> None:
    path = WORK / "created.json"
    seen = json.loads(path.read_text()) if path.exists() else {}
    for pk in seen.get("gateways", []):
        api("DELETE", f"/api/edge/gateways/{pk}", params={"remove_source": "true"})
    for aid in seen.get("agents", []):
        api("DELETE", f"/api/agents/{aid}")
    print("ok")


def blackhole() -> None:
    """Accepts connections and never answers, the model that makes max_runtime_seconds matter."""
    import socket

    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 8099))
    s.listen(64)
    held = []
    while True:
        held.append(s.accept()[0])
        held[:] = held[-64:]


def fake_platform() -> None:
    """Enrolment, heartbeat and ingest with a switch for the link, for scripts/edge-conformance.sh."""
    import gzip
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    state: dict[str, Any] = {
        "down": False,
        "enrolls": 0,
        "heartbeats": 0,
        "values": {},
        "keys": set(),
    }
    data_dir = "/var/lib/abenix-edge"
    config = {
        "roles": ["collect", "agents"],
        "heartbeat_s": 1,
        "self_metrics_s": 1,
        "uplink": {"gzip": True},
        "gateway_asset": {"group": "conf"},
        "collectors": [
            {
                "id": "tail",
                "type": "file_tail",
                "name": "tail",
                "path": f"{data_dir}/rows*.csv",
                "format": "csv",
                "from_start": True,
                "interval_s": 0.5,
                "asset": {"group": "conf", "node": "log", "device": "csv"},
            },
            {
                "id": "bridge",
                "type": "mqtt_bridge",
                "name": "bridge",
                "broker": f"mqtt://{BROKER}:{BROKER_PORT}",
                "topics": "conf/#",
                "interval_s": 0.5,
                "asset": {"group": "conf", "node": "sens", "device": "bridge"},
            },
        ],
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a: Any) -> None:
            pass

        def _send(self, code: int, doc: Any) -> None:
            raw = json.dumps(doc, default=lambda o: sorted(o)).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            self._send(200, state)

        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("content-length") or 0))
            path = self.path.split("?")[0]
            if path.startswith("/control/"):
                state["down"] = path.endswith("/down")
                return self._send(200, {"down": state["down"]})
            if state["down"]:
                self.connection.close()
                return None
            if path == "/api/edge/enroll":
                state["enrolls"] += 1
                return self._send(
                    200,
                    {
                        "data": {
                            "id": "pk",
                            "gateway_id": "conf-gw",
                            "name": "conf",
                            "key": "tgk_conf",
                            "connection_id": "c1",
                            "ingest_url": "/api/telemetry/ingest/c1",
                            "config": config,
                            "config_version": 1,
                            "signing_pubkey_pem": (WORK / "pub.pem").read_text(),
                            "tenant_id": "tenant-a",
                        }
                    },
                )
            if path == "/api/edge/heartbeat":
                state["heartbeats"] += 1
                return self._send(200, {"data": {"config_version": 1}})
            if self.headers.get("content-encoding") == "gzip":
                body = gzip.decompress(body)
            key = self.headers.get("idempotency-key") or ""
            if key not in state["keys"]:
                state["keys"].add(key)
                for v in json.loads(body)["values"]:
                    state["values"].setdefault(v["name"], []).append(v["value"])
            return self._send(202, {"data": {"accepted": True}})

    ThreadingHTTPServer(("0.0.0.0", 8100), Handler).serve_forever()


def cmd_fake_expect(expr: str, timeout: str) -> None:
    end = time.time() + float(timeout)
    s: dict[str, Any] = {}
    while time.time() < end:
        s = httpx.get("http://localhost:8100/state", timeout=5.0).json()
        if eval(expr, {}, {"s": s}):  # noqa: S307
            print("ok")
            return
        time.sleep(0.5)
    brief = {k: s.get(k) for k in ("enrolls", "heartbeats", "down")}
    brief["names"] = sorted(s.get("values") or {})
    raise Fail(f"{expr} did not hold in {timeout} s, {jdump(brief)}")


def cmd_fake_link(state: str) -> None:
    httpx.post(f"http://localhost:8100/control/{state}", timeout=5.0)
    print("ok")


COMMANDS = {
    k[4:].replace("_", "-"): v
    for k, v in list(globals().items())
    if k.startswith("cmd_")
}
COMMANDS["blackhole"] = blackhole
COMMANDS["fake-platform"] = fake_platform


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "secrets").mkdir(exist_ok=True)
    args = sys.argv[1:]
    if not args or args[0] not in COMMANDS:
        print(f"unknown step, choose from {sorted(COMMANDS)}", file=sys.stderr)
        return 2
    try:
        COMMANDS[args[0]](*args[1:])
        return 0
    except Fail as e:
        print(str(e), file=sys.stderr)
    except (httpx.HTTPError, OSError, ValueError, KeyError) as e:
        print(f"{args[0]} failed {type(e).__name__} {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
