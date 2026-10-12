"""OPC UA connector against an in-process asyncua server: subscribe, quality, names, write, sign-in."""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import socket

import pytest

pytest.importorskip("asyncua")

from asyncua import Server, ua  # noqa: E402
from asyncua.server.user_managers import UserManager  # noqa: E402

from app.telemetry.connectors import opcua as O  # noqa: E402
from app.telemetry.connectors.base import ConnectorError, RunContext  # noqa: E402

logging.getLogger("asyncua").setLevel(logging.ERROR)


def arun(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))

    return wrapper


class Users(UserManager):
    def get_user(self, iserver, username=None, password=None, certificate=None):
        if username == "abenix" and password == "pw-123456":
            from asyncua.crypto.permission_rules import User, UserRole

            return User(role=UserRole.User)
        return None


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def plc():
    port = free_port()
    srv = Server(user_manager=Users())
    await srv.init()
    srv.set_endpoint(f"opc.tcp://127.0.0.1:{port}/plc")
    srv.set_security_policy([ua.SecurityPolicyType.NoSecurity])
    idx = await srv.register_namespace("urn:abenix:test")
    line = await srv.nodes.objects.add_folder(idx, "Line1")
    temp = await line.add_variable(ua.NodeId("Temp", idx), "Temperature", 21.5)
    speed = await line.add_variable(ua.NodeId("Speed", idx), "Speed", 1200)
    await speed.set_writable()
    await srv.start()
    return srv, port, idx, temp, speed


def cfg(port, idx, **kw):
    return {
        "endpoint": f"opc.tcp://127.0.0.1:{port}/plc",
        "username": "abenix",
        "nodes": f"ns={idx};s=Temp = Line1/Temperature_C\nns={idx};s=Speed",
        "sampling_interval_ms": "50",
        "publishing_interval_ms": "50",
        "asset": "plant/line-1",
        **kw,
    }


def test_declares_plain_fields():
    d = O.OpcUaConnector.describe()
    assert d["transport"] == "opcua" and O.OpcUaConnector.default_decoder == "values"
    keys = {f["key"]: f for f in d["config_fields"]}
    assert keys["endpoint"]["required"] and keys["password"]["kind"] == "secret"
    assert "Basic256Sha256" in keys["security_policy"]["options"]
    assert keys["security_mode"]["options"] == ["None", "Sign", "SignAndEncrypt"]
    for f in d["config_fields"]:
        assert f["label"] and f["description"], f["key"]


def test_node_list_and_names():
    nodes = O.node_list(
        {
            "nodes": "ns=3;s=SlowDouble1 = Line1/Speed_rpm\n# note\nns=3;s=StepUp",
            "subjects": ["i=2259"],
        }
    )
    assert nodes == [
        ("ns=3;s=SlowDouble1", "Line1/Speed_rpm"),
        ("ns=3;s=StepUp", None),
        ("i=2259", None),
    ]
    with pytest.raises(ConnectorError, match="is not a node id"):
        O.node_list({"nodes": "Temperature"})


def test_quality_from_status_codes():
    good = ua.DataValue(ua.Variant(1.5, ua.VariantType.Double))
    bad = ua.DataValue(
        ua.Variant(0.0, ua.VariantType.Double),
        StatusCode=ua.StatusCode(ua.StatusCodes.BadSensorFailure),
    )
    unc = ua.DataValue(
        ua.Variant(2.0, ua.VariantType.Double),
        StatusCode=ua.StatusCode(ua.StatusCodes.UncertainLastUsableValue),
    )
    assert O.value_of("t", "n", good)["quality"] == "good"
    b = O.value_of("t", "n", bad)
    assert b["quality"] == "bad" and b["status"] == "BadSensorFailure"
    assert O.value_of("t", "n", unc)["quality"] == "uncertain"


def test_coerce_to_the_node_type():
    V = ua.VariantType
    assert O.coerce("true", V.Boolean) is True and O.coerce("12", V.Int32) == 12
    assert O.coerce(1, V.Double) == 1.0
    with pytest.raises(ConnectorError, match="does not fit"):
        O.coerce("12.5", V.Int16)


def test_security_settings_must_agree():
    with pytest.raises(
        ConnectorError, match="Security policy None goes with mode None"
    ):
        asyncio.run(
            O.make_client(
                {"endpoint": "opc.tcp://h:4840", "security_policy": "Basic256Sha256"},
                {},
            )
        )
    with pytest.raises(ConnectorError, match="opc.tcp://"):
        O.endpoint_of({"endpoint": "http://h"})


def test_status_errors_in_plain_words():
    e = ua.UaStatusCodeError(ua.StatusCodes.BadUserAccessDenied)
    assert "refused the sign-in (BadUserAccessDenied)" in O.words(
        e, {"endpoint": "opc.tcp://plc:4840"}
    )
    e = ua.UaStatusCodeError(ua.StatusCodes.BadNotWritable)
    assert "read only" in O.words(e, {"endpoint": "opc.tcp://plc:4840"})
    e = ua.UaStatusCodeError(ua.StatusCodes.BadCertificateUntrusted)
    assert "does not trust" in O.words(e, {"endpoint": "opc.tcp://plc:4840"})


@arun
async def test_live_subscribe_write_and_refusal():
    srv, port, idx, temp, speed = await plc()
    try:
        c = O.OpcUaConnector()
        good = cfg(port, idx)
        out = await c.test(good, {"password": "pw-123456"})
        assert out["ok"], out["error"]
        assert {v["name"] for v in json.loads(out["sample"])["values"]} == {
            "Line1/Temperature_C",
            "Speed",
        }

        bad = await c.test(good, {"password": "nope-nope"})
        assert not bad["ok"] and "refused the sign-in" in bad["error"]

        ctx = RunContext(
            connection_id="c1",
            tenant="t1",
            name="PLC",
            config=good,
            secrets={"password": "pw-123456"},
            replica="r1",
            shared=False,
        )
        task = asyncio.create_task(c.run(ctx))
        for _ in range(300):
            if ctx.status == "connected" and ctx.queue:
                break
            await asyncio.sleep(0.01)
        await temp.write_value(
            ua.DataValue(
                ua.Variant(99.0, ua.VariantType.Double),
                StatusCode=ua.StatusCode(ua.StatusCodes.BadSensorFailure),
            )
        )
        await c.write(
            good, {"password": "pw-123456"}, {"node_id": f"ns={idx};s=Speed"}, "1500"
        )
        seen: dict = {}
        for _ in range(300):
            for env in list(ctx.queue):
                for v in json.loads(env.payload)["values"]:
                    seen[(v["name"], v["value"])] = v
            # a bad status may come without its value, as the spec allows
            temps = [
                v
                for (n, _), v in seen.items()
                if n == "Line1/Temperature_C" and v["quality"] == "bad"
            ]
            if ("Speed", 1500) in seen and temps:
                break
            await asyncio.sleep(0.01)
        assert seen[("Speed", 1500)]["quality"] == "good"
        assert temps[0]["status"] == "BadSensorFailure"
        env = ctx.queue[0]
        assert (
            env.subject == "plant/line-1"
            and env.headers["content-type"] == O.CONTENT_TYPE
        )
        assert await speed.read_value() == 1500

        with pytest.raises(ConnectorError, match="would not let Abenix write"):
            await c.write(
                good, {"password": "pw-123456"}, {"node_id": f"ns={idx};s=Temp"}, 1
            )
        ctx.stopping.set()
        await asyncio.wait_for(task, 10)
        assert ctx.status == "disabled"
    finally:
        await srv.stop()


def test_a_bad_subscription_status_ends_the_session():
    from asyncua.common.subscription import StatusChangeEvent

    bad = StatusChangeEvent(
        notification=ua.StatusChangeNotification(
            Status=ua.StatusCode(ua.StatusCodes.BadShutdown)
        )
    )
    with pytest.raises(ConnectorError, match="ended the subscription"):
        O.plain_event(bad, {})
    good = StatusChangeEvent(
        notification=ua.StatusChangeNotification(
            Status=ua.StatusCode(ua.StatusCodes.Good)
        )
    )
    assert O.plain_event(good, {}) is None


def test_huge_values_are_cut():
    big = ua.DataValue(ua.Variant("x" * 200000, ua.VariantType.String))
    v = O.value_of("Big", "ns=3;s=LongString200kB", big)
    assert len(v["value"]) == O.MAX_TEXT and "cut to" in v["status"]
