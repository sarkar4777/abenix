"""Runner behaviour: workspace, isolation of each run, handler mode, gateway."""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import runner

posix = pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX host")
PY = sys.executable


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buf.getvalue()


def _built_ws(root: Path, files: dict[str, str]) -> Path:
    ws = root / "ws"
    runner.extract_zip(_zip(files), ws / "app")
    (ws / runner.READY_MARKER).write_text("v1-test")
    return ws


def _executor(tmp_path: Path, files: dict[str, str], run_cmd: str, **kw):
    ws = _built_ws(tmp_path, files)
    ex = runner.Executor(
        ws=ws,
        tmp=tmp_path / "tmp",
        scratch=tmp_path / "scratch",
        run_cmd=run_cmd,
        concurrency=kw.pop("concurrency", 4),
        **kw,
    )
    ex.link_workspace()
    return ex


# ── mapping and payload ──────────────────────────────────────────────────────


def test_pool_mapping():
    assert runner.pool_for_image("python:3.12-slim") == "python-3.12"
    assert runner.pool_for_image("python:3.11") == "python-3.11"
    assert runner.pool_for_image("node:20-alpine") == "node-20"
    assert runner.pool_for_image("golang:1.22-alpine") == "go-1.22"
    assert runner.pool_for_image("docker.io/library/python:3.12-slim") == "python-3.12"
    assert runner.pool_for_image("localhost:5000/x/node:20") == "node-20"
    assert runner.pool_for_image("alpine:3.20") is None
    assert runner.pool_for_image("") is None


def test_subject_carries_tenant_asset_and_revision():
    assert runner.subject_for("t1", "a1", "v3-abc", False) == "code.t1.a1.v3-abc"
    assert runner.subject_for("t1", "a1", "v3-abc", True) == "code.t1.a1.v3-abc.net"


def test_zip_single_folder_is_stripped(tmp_path):
    runner.extract_zip(_zip({"proj/main.py": "x", "proj/lib/u.py": "y"}), tmp_path)
    assert (tmp_path / "main.py").read_text() == "x"
    assert (tmp_path / "lib" / "u.py").exists()


def test_zip_paths_that_escape_are_refused(tmp_path):
    with pytest.raises(ValueError):
        runner.extract_zip(_zip({"../evil.py": "x", "ok.py": "y"}), tmp_path / "d")


# ── workspace ────────────────────────────────────────────────────────────────


async def test_concurrent_first_calls_build_once_then_hit(tmp_path):
    ws = runner.Workspace(tmp_path / "ws", "v1-aaaaaa")
    fetches = 0

    async def fetch():
        nonlocal fetches
        fetches += 1
        await asyncio.sleep(0.05)
        return _zip({"main.py": "print(1)"})

    async def build(root):
        await asyncio.sleep(0.05)
        (root / "app" / "built").write_text("ok")

    states = await asyncio.gather(*(ws.ensure(fetch, build) for _ in range(8)))
    assert states.count("miss") == 1 and states.count("hit") == 7
    assert fetches == 1 and ws.builds == 1
    assert await ws.ensure(fetch, build) == "hit"
    again = runner.Workspace(tmp_path / "ws", "v1-aaaaaa")
    assert again.ready()
    assert not runner.Workspace(tmp_path / "ws", "v2-bbbbbb").ready()


# ── one run ──────────────────────────────────────────────────────────────────


@posix
async def test_env_is_only_the_request_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NATS_PASSWORD", "leak-me")
    monkeypatch.setenv("RUNNER_INTERNAL", "leak-me")
    ex = _executor(
        tmp_path,
        {"main.py": "x"},
        f"{PY} -c 'import os,json;print(json.dumps(dict(os.environ)))'",
    )
    res = await ex.handle(
        {
            "input": {},
            "env": {"API_KEY": "s3cret", "PATH": "/evil", "LD_PRELOAD": "/x.so"},
            "timeout_s": 20,
        }
    )
    assert res["ok"], res
    env = json.loads(res["stdout"])
    assert env["API_KEY"] == "s3cret"
    assert "NATS_PASSWORD" not in env and "RUNNER_INTERNAL" not in env
    assert "LD_PRELOAD" not in env and env["PATH"] != "/evil"
    allowed = {
        "API_KEY",
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "PYTHONUSERBASE",
        "PYTHONDONTWRITEBYTECODE",
        "NPM_CONFIG_PREFIX",
        "ABENIX_INPUT_FILE",
        "PWD",
        "SHLVL",
        "_",
        "LC_CTYPE",
    }
    assert set(env) <= allowed, set(env) - allowed
    assert env["HOME"].startswith(str(tmp_path / "scratch"))


@posix
async def test_rlimits_are_applied(tmp_path, monkeypatch):
    monkeypatch.setenv("CODERUN_MAX_PROCS", "300")
    monkeypatch.setenv("CODERUN_MAX_FILE_MB", "8")
    code = (
        "import resource as r,json;"
        "print(json.dumps({n:r.getrlimit(getattr(r,n)) for n in "
        "('RLIMIT_CPU','RLIMIT_AS','RLIMIT_NPROC','RLIMIT_FSIZE')}))"
    )
    ex = _executor(tmp_path, {"main.py": "x"}, f'{PY} -c "{code}"')
    res = await ex.handle({"input": {}, "env": {}, "timeout_s": 7, "memory_mb": 512})
    assert res["ok"], res
    lim = json.loads(res["stdout"])
    assert lim["RLIMIT_CPU"] == [8, 9]
    assert lim["RLIMIT_AS"] == [512 * 1024 * 1024] * 2
    assert lim["RLIMIT_NPROC"] == [300, 300]
    assert lim["RLIMIT_FSIZE"] == [8 * 1024 * 1024] * 2


@posix
async def test_timeout_kills_the_whole_process_group(tmp_path):
    pidfile = tmp_path / "bg.pid"
    ex = _executor(
        tmp_path,
        {"main.py": "x"},
        f"sleep 60 & echo $! > {pidfile}; sleep 60",
    )
    res = await ex.handle({"input": {}, "env": {}, "timeout_s": 1})
    assert res["timed_out"] and not res["ok"] and res["exit_code"] == -9
    assert res["duration_ms"] < 5000
    pid = int(pidfile.read_text())
    await asyncio.sleep(0.2)
    alive = True
    try:
        os.kill(pid, 0)
        alive = Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except ProcessLookupError:
        alive = False
    assert not alive


@posix
async def test_stdout_is_capped(tmp_path):
    ex = _executor(
        tmp_path,
        {"main.py": "x"},
        f"{PY} -c \"print('a'*50000)\"",
        max_stdout=1000,
    )
    res = await ex.handle({"input": {}, "env": {}, "timeout_s": 20})
    assert len(res["stdout"]) == 1000 and res["stdout_truncated"]


@posix
async def test_input_on_stdin_and_private_scratch_removed(tmp_path):
    ex = _executor(
        tmp_path,
        {
            "main.py": "import sys,json,os;d=json.load(sys.stdin);d['f']=os.path.exists(os.environ['ABENIX_INPUT_FILE']);print(json.dumps(d))"
        },
        f"{PY} main.py",
    )
    res = await ex.handle({"input": {"x": 1}, "env": {}, "timeout_s": 20})
    assert res["ok"], res
    assert json.loads(res["stdout"]) == {"x": 1, "f": True}
    assert res["cache"] == "hit"
    assert list((tmp_path / "scratch").iterdir()) == []


@posix
async def test_workspace_is_reached_through_tmp_links(tmp_path):
    ex = _executor(tmp_path, {"main.py": "print('hi')"}, f"{PY} /tmp_marker_unused")
    link = tmp_path / "tmp" / "app"
    assert link.is_symlink() and os.readlink(link) == str(tmp_path / "ws" / "app")
    link.unlink()
    link.mkdir()
    ex.link_workspace()
    assert link.is_symlink()


@posix
async def test_shared_input_file_forces_serial_runs(tmp_path):
    ex = _executor(
        tmp_path,
        {"main.py": "open('/tmp/input.json').read()"},
        f"{PY} main.py",
        concurrency=4,
    )
    assert ex.shared_input and ex.concurrency == 1
    other = _executor(tmp_path / "o", {"main.py": "import sys"}, f"{PY} main.py")
    assert not other.shared_input and other.concurrency == 4


# ── handler mode ─────────────────────────────────────────────────────────────

HANDLER = """
import json, os, sys, time
for line in sys.stdin:
    req = json.loads(line)
    inp = req["input"]
    print("log line that is not a reply", flush=True)
    if inp.get("sleep"):
        time.sleep(inp["sleep"])
    if inp.get("fail"):
        print(json.dumps({"id": req["id"], "error": "bad input"}), flush=True)
        continue
    out = {"pid": os.getpid(), "echo": inp, "secret": os.environ.get("TOKEN")}
    print(json.dumps({"id": req["id"], "output": out}), flush=True)
"""


@posix
async def test_handler_mode_reuses_one_process(tmp_path):
    ex = _executor(
        tmp_path,
        {
            "handler.py": HANDLER,
            "abenix-runner.json": json.dumps(
                {"mode": "handler", "handler_command": f"{PY} handler.py"}
            ),
        },
        f"{PY} main.py",
        concurrency=1,
    )
    assert ex.mode == "handler"
    r1 = await ex.handle({"input": {"a": 1}, "env": {"TOKEN": "t"}, "timeout_s": 10})
    r2 = await ex.handle({"input": {"a": 2}, "env": {"TOKEN": "t"}, "timeout_s": 10})
    assert r1["ok"] and r2["ok"], (r1, r2)
    o1, o2 = json.loads(r1["stdout"]), json.loads(r2["stdout"])
    assert o1["pid"] == o2["pid"] and o2["echo"] == {"a": 2} and o1["secret"] == "t"
    assert (r1["cache"], r2["cache"]) == ("miss", "hit")
    bad = await ex.handle(
        {"input": {"fail": 1}, "env": {"TOKEN": "t"}, "timeout_s": 10}
    )
    assert not bad["ok"] and "bad input" in bad["stderr_tail"]
    r3 = await ex.handle({"input": {}, "env": {"TOKEN": "rotated"}, "timeout_s": 10})
    assert r3["cache"] == "miss" and json.loads(r3["stdout"])["pid"] != o1["pid"]
    slow = await ex.handle(
        {"input": {"sleep": 5}, "env": {"TOKEN": "rotated"}, "timeout_s": 1}
    )
    assert slow["timed_out"] and not slow["ok"]
    after = await ex.handle({"input": {}, "env": {"TOKEN": "rotated"}, "timeout_s": 10})
    assert after["ok"] and after["cache"] == "miss"
    slot = ex.slots.get_nowait()
    await slot.stop()


# ── exec socket and gateway ──────────────────────────────────────────────────


@posix
async def test_socket_round_trip(tmp_path):
    ex = _executor(
        tmp_path, {"main.py": "import sys;print(sys.stdin.read())"}, f"{PY} main.py"
    )
    sock = str(tmp_path / "s" / "exec.sock")
    stop = asyncio.Event()
    server = asyncio.ensure_future(runner.serve_exec(ex, sock, stop))
    for _ in range(50):
        if os.path.exists(sock):
            break
        await asyncio.sleep(0.02)
    call = runner.socket_exec_call(sock)
    res = await call({"input": {"k": "v"}, "env": {}, "timeout_s": 10, "revision": "x"})
    assert res["ok"] and json.loads(res["stdout"]) == {"k": "v"}
    stop.set()
    await asyncio.wait_for(server, 10)
    gone = await runner.socket_exec_call(str(tmp_path / "nope.sock"))({"input": {}})
    assert gone["refused"]


class _Msg:
    def __init__(self, data: dict):
        self.data = json.dumps(data).encode()
        self.reply = None

    async def respond(self, data: bytes):
        self.reply = json.loads(data)


async def test_gateway_routes_refuses_and_counts():
    calls = []
    gate = asyncio.Event()

    async def fake_exec(req):
        calls.append(req)
        await gate.wait()
        return {
            "ok": True,
            "exit_code": 0,
            "stdout": "{}",
            "duration_ms": 5,
            "cache": "hit",
        }

    gw = runner.Gateway(
        revision="v1-abc", concurrency=2, exec_call=fake_exec, pod="p1", max_pending=1
    )
    assert (await gw.process({"revision": "v0-old"}))["reason"] == "revision mismatch"
    msgs = [_Msg({"revision": "v1-abc", "input": {"i": i}}) for i in range(3)]
    for m in msgs:
        await gw.on_msg(m)
    await asyncio.sleep(0.05)
    assert gw.metrics.inflight == 2 and gw.metrics.pending == 1
    busy = await gw.process({"revision": "v1-abc"})
    assert busy["refused"] and busy["reason"] == "busy"
    gate.set()
    await gw.drain(5)
    assert all(m.reply["ok"] and m.reply["runner"] == "p1" for m in msgs)
    assert gw.metrics.inflight == 0 and gw.metrics.pending == 0
    text = gw.metrics.render()
    assert 'abenix_coderunner_runs_total{runner="p1",pool="",outcome="ok"} 3' in text
    assert 'abenix_coderunner_cache_total{runner="p1",pool="",result="hit"} 3' in text
    assert (await gw.process({"revision": "v1-abc"}))["reason"] == "draining"


async def test_gateway_bad_json_is_refused():
    gw = runner.Gateway(revision="r", concurrency=1, exec_call=None, pod="p")
    msg = SimpleNamespace(data=b"not json", reply=None)

    async def respond(data):
        msg.reply = json.loads(data)

    msg.respond = respond
    await gw.on_msg(msg)
    await gw.drain(1)
    assert msg.reply["refused"]


async def test_http_health_and_metrics():
    m = runner.Metrics("r1", "python-3.12")
    m.observe("ok", "hit", 0.02)
    healthy = {"ok": False}
    server = await runner.serve_http(0, m, lambda: healthy["ok"])
    port = server.sockets[0].getsockname()[1]

    async def get(path):
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        await w.drain()
        body = await r.read()
        w.close()
        return body.decode()

    assert "503" in (await get("/healthz")).split("\r\n")[0]
    healthy["ok"] = True
    assert "200" in (await get("/healthz")).split("\r\n")[0]
    metrics = await get("/metrics")
    assert (
        'abenix_coderunner_duration_seconds_bucket{runner="r1",pool="python-3.12",le="0.025"} 1'
        in metrics
    )
    server.close()
