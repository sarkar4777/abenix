"""Warm runner for one code asset version: prepare, exec and gateway roles."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import shutil
import signal
import struct
import sys
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger("coderun")

DEFAULT_PATH = (
    "/tmp/.pyuser/bin:/tmp/.npm-global/bin:"
    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)
RESERVED_ENV = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "PYTHONUSERBASE",
        "PYTHONDONTWRITEBYTECODE",
        "NPM_CONFIG_PREFIX",
        "ABENIX_INPUT_FILE",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
    }
)
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
MANIFEST = "abenix-runner.json"
READY_MARKER = ".coderun-ready"
BUILD_TMP = ".build-tmp"
MAX_FRAME = 64 * 1024 * 1024
INPUT_FILE_REF = b"/tmp/input.json"

_POOLS = (
    ("python", re.compile(r"^(?:[\w.:-]+/)*python3?:(\d+\.\d+)")),
    ("node", re.compile(r"^(?:[\w.:-]+/)*node:(\d+)")),
    ("go", re.compile(r"^(?:[\w.:-]+/)*golang:(\d+\.\d+)")),
    ("ruby", re.compile(r"^(?:[\w.:-]+/)*ruby:(\d+\.\d+)")),
    ("java", re.compile(r"^(?:[\w.:-]+/)*eclipse-temurin:(\d+)")),
)


# Kept identical to engine.code_runners.pool_for_image, a test pins the two.
def pool_for_image(image: str) -> str | None:
    img = (image or "").strip().lower()
    for family, rx in _POOLS:
        m = rx.match(img)
        if m:
            return f"{family}-{m.group(1)}"
    return None


# Kept identical to engine.code_runners.subject_for, a test pins the two.
def subject_for(tenant_id: str, asset_id: str, revision: str, network: bool) -> str:
    base = f"code.{tenant_id}.{asset_id}.{revision}"
    return base + ".net" if network else base


# Kept identical to engine.tools.code_asset.single_root_prefix, a test pins the two.
def single_root_prefix(names: list[str]) -> str:
    parts = [n for n in names if n and not n.startswith("__MACOSX/")]
    if not parts:
        return ""
    first = parts[0].split("/", 1)[0]
    if not first or any(n.split("/", 1)[0] != first for n in parts):
        return ""
    if not any(n.startswith(first + "/") and len(n) > len(first) + 1 for n in parts):
        return ""
    return first + "/"


def _safe_rel(name: str) -> str | None:
    n = name.replace("\\", "/")
    if not n or n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        return None
    parts = [p for p in n.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def extract_zip(data: bytes, dest: Path) -> int:
    """Unpack an asset zip the way the Job path does, refusing paths that escape."""
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        prefix = single_root_prefix(zf.namelist())
        for info in zf.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX/"):
                continue
            rel = _safe_rel(info.filename[len(prefix) :])
            if rel is None:
                raise ValueError(f"unsafe path in archive: {info.filename!r}")
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            mode = (info.external_attr >> 16) & 0o777
            os.chmod(target, 0o755 if mode & 0o111 else 0o644)
            count += 1
    return count


# ── workspace ────────────────────────────────────────────────────────────────


class Workspace:
    """A built tree for one revision. Concurrent first calls build it once."""

    _locks: dict[str, asyncio.Lock] = {}

    def __init__(self, root: Path, revision: str):
        self.root = Path(root)
        self.revision = revision
        self.builds = 0

    @property
    def marker(self) -> Path:
        return self.root / READY_MARKER

    def ready(self) -> bool:
        try:
            return self.marker.read_text().strip() == self.revision
        except OSError:
            return False

    async def ensure(
        self,
        fetch: Callable[[], Awaitable[bytes]],
        build: Callable[[Path], Awaitable[None]],
    ) -> str:
        if self.ready():
            return "hit"
        lock = Workspace._locks.setdefault(str(self.root), asyncio.Lock())
        async with lock:
            if self.ready():
                return "hit"
            data = await fetch()
            app = self.root / "app"
            if app.exists():
                shutil.rmtree(app)
            await asyncio.to_thread(extract_zip, data, app)
            self.builds += 1
            await build(self.root)
            shutil.rmtree(self.root / BUILD_TMP, ignore_errors=True)
            self.marker.write_text(self.revision)
            return "miss"


def build_env(root: Path) -> dict[str, str]:
    tmp = root / BUILD_TMP
    tmp.mkdir(parents=True, exist_ok=True)
    (root / "home").mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ.get("CODERUN_PATH", DEFAULT_PATH),
        "HOME": str(root / "home"),
        "TMPDIR": str(tmp),
        "LANG": "C.UTF-8",
        "PYTHONUSERBASE": str(root / ".pyuser"),
        "PIP_USER": "1",
        "PIP_CACHE_DIR": str(tmp / "pip"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "NPM_CONFIG_PREFIX": str(root / ".npm-global"),
        "npm_config_cache": str(tmp / "npm"),
    }


# ── process control ──────────────────────────────────────────────────────────


def run_limits(
    timeout_s: int, memory_mb: int, *, cpu: bool = True
) -> list[tuple[str, int, int]]:
    limits: list[tuple[str, int, int]] = []
    if cpu and timeout_s > 0:
        limits.append(("RLIMIT_CPU", int(timeout_s) + 1, int(timeout_s) + 2))
    as_mult = float(os.environ.get("CODERUN_AS_MULTIPLIER", "1") or 0)
    if as_mult > 0 and memory_mb > 0:
        cap = int(memory_mb * as_mult) * 1024 * 1024
        limits.append(("RLIMIT_AS", cap, cap))
    nproc = int(os.environ.get("CODERUN_MAX_PROCS", "512"))
    if nproc > 0:
        limits.append(("RLIMIT_NPROC", nproc, nproc))
    fsize = int(os.environ.get("CODERUN_MAX_FILE_MB", "256")) * 1024 * 1024
    if fsize > 0:
        limits.append(("RLIMIT_FSIZE", fsize, fsize))
    return limits


def make_preexec(limits: list[tuple[str, int, int]]) -> Callable[[], None]:
    def _apply() -> None:
        import resource

        for name, soft, hard in limits:
            resource.setrlimit(getattr(resource, name), (soft, hard))

    return _apply


def kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


class _Capped:
    def __init__(self, cap: int, tail: bool = False):
        self.cap = cap
        self.tail = tail
        self.buf = bytearray()
        self.dropped = 0

    def add(self, chunk: bytes) -> None:
        if self.tail:
            self.buf += chunk
            if len(self.buf) > self.cap:
                self.dropped += len(self.buf) - self.cap
                del self.buf[: len(self.buf) - self.cap]
            return
        room = max(self.cap - len(self.buf), 0)
        self.buf += chunk[:room]
        self.dropped += max(0, len(chunk) - room)

    def text(self) -> str:
        return self.buf.decode("utf-8", errors="replace")


async def _pump(stream: asyncio.StreamReader | None, sink: _Capped) -> None:
    if stream is None:
        return
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return
        sink.add(chunk)


async def run_process(
    cmd: str,
    *,
    cwd: str,
    env: dict[str, str],
    stdin_bytes: bytes,
    timeout_s: float,
    limits: list[tuple[str, int, int]],
    max_stdout: int,
    max_stderr: int = 16384,
) -> dict[str, Any]:
    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        "/bin/sh",
        "-c",
        cmd,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        preexec_fn=make_preexec(limits),
    )
    out, err = _Capped(max_stdout), _Capped(max_stderr, tail=True)

    async def _feed() -> None:
        try:
            if stdin_bytes:
                proc.stdin.write(stdin_bytes)
                await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass

    pumps = [
        asyncio.ensure_future(_feed()),
        asyncio.ensure_future(_pump(proc.stdout, out)),
        asyncio.ensure_future(_pump(proc.stderr, err)),
    ]
    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout_s)
    except asyncio.TimeoutError:
        timed_out = True
    finally:
        # also reaps background children the run left behind
        kill_group(proc.pid)
    await proc.wait()
    _, pending = await asyncio.wait(pumps, timeout=2)
    for p in pending:
        p.cancel()
    return {
        "exit_code": -9 if timed_out else proc.returncode,
        "timed_out": timed_out,
        "stdout": out.text(),
        "stdout_truncated": out.dropped > 0,
        "stderr_tail": err.text(),
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }


def scrub_env(req_env: dict[str, Any] | None, home: str) -> dict[str, str]:
    """Only the caller's env plus a fixed minimum. Nothing of the runner's own."""
    env: dict[str, str] = {}
    for k, v in (req_env or {}).items():
        k = str(k)
        if ENV_NAME_RE.match(k) and k not in RESERVED_ENV:
            env[k] = str(v)
    env.update(
        PATH=os.environ.get("CODERUN_PATH", DEFAULT_PATH),
        HOME=home,
        TMPDIR=home,
        LANG="C.UTF-8",
        PYTHONUSERBASE="/tmp/.pyuser",
        PYTHONDONTWRITEBYTECODE="1",
        NPM_CONFIG_PREFIX="/tmp/.npm-global",
        ABENIX_INPUT_FILE=f"{home}/input.json",
    )
    return env


# ── exec agent ───────────────────────────────────────────────────────────────


async def read_frame(reader: asyncio.StreamReader) -> dict[str, Any]:
    (n,) = struct.unpack(">I", await reader.readexactly(4))
    if n > MAX_FRAME:
        raise ValueError("frame too large")
    return json.loads(await reader.readexactly(n))


async def write_frame(writer: asyncio.StreamWriter, obj: dict[str, Any]) -> None:
    data = json.dumps(obj).encode()
    writer.write(struct.pack(">I", len(data)) + data)
    await writer.drain()


def load_manifest(app_dir: Path) -> dict[str, Any]:
    try:
        m = json.loads((app_dir / MANIFEST).read_text())
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def mentions_shared_input(app_dir: Path, run_cmd: str, limit: int = 2000) -> bool:
    if INPUT_FILE_REF.decode() in run_cmd:
        return True
    seen = 0
    for p in app_dir.rglob("*"):
        if seen >= limit:
            break
        if "node_modules" in p.parts or not p.is_file():
            continue
        seen += 1
        try:
            if p.stat().st_size > 1_000_000:
                continue
            if INPUT_FILE_REF in p.read_bytes():
                return True
        except OSError:
            continue
    return False


class HandlerSlot:
    """One long-lived handler process speaking the line protocol."""

    def __init__(self, cmd: str, cwd: str, home: str, max_stdout: int):
        self.cmd = cmd
        self.cwd = cwd
        self.home = home
        self.max_stdout = max_stdout
        self.proc: asyncio.subprocess.Process | None = None
        self.env_key = ""
        self.stderr = _Capped(16384, tail=True)
        self._err_task: asyncio.Future | None = None

    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self, env: dict[str, str], env_key: str, memory_mb: int) -> None:
        await self.stop()
        Path(self.home).mkdir(parents=True, exist_ok=True)
        self.proc = await asyncio.create_subprocess_exec(
            "/bin/sh",
            "-c",
            self.cmd,
            cwd=self.cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            limit=self.max_stdout + 1024,
            preexec_fn=make_preexec(run_limits(0, memory_mb, cpu=False)),
        )
        self.env_key = env_key
        self.stderr = _Capped(16384, tail=True)
        self._err_task = asyncio.ensure_future(_pump(self.proc.stderr, self.stderr))

    async def stop(self) -> None:
        if self.proc is not None:
            kill_group(self.proc.pid)
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except asyncio.TimeoutError:
                pass
        if self._err_task is not None:
            self._err_task.cancel()
        self.proc = None

    async def call(self, req_id: str, payload: Any, timeout_s: float) -> dict[str, Any]:
        assert self.proc is not None
        line = json.dumps({"id": req_id, "input": payload}) + "\n"
        self.proc.stdin.write(line.encode())
        await self.proc.stdin.drain()
        deadline = time.monotonic() + timeout_s
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise asyncio.TimeoutError()
            raw = await asyncio.wait_for(self.proc.stdout.readline(), left)
            if not raw:
                raise EOFError("handler exited")
            try:
                msg = json.loads(raw)
            except ValueError:
                self.stderr.add(raw)
                continue
            if isinstance(msg, dict) and msg.get("id") == req_id:
                return msg
            self.stderr.add(raw)


class Executor:
    def __init__(
        self,
        *,
        ws: Path,
        tmp: Path,
        scratch: Path,
        run_cmd: str,
        concurrency: int,
        max_stdout: int = 1_000_000,
        mode: str | None = None,
    ):
        self.ws = Path(ws)
        self.tmp = Path(tmp)
        self.scratch = Path(scratch)
        self.run_cmd = run_cmd
        self.max_stdout = max_stdout
        self.manifest = load_manifest(self.ws / "app")
        self.mode = (mode or self.manifest.get("mode") or "process").lower()
        self.handler_cmd = self.manifest.get("handler_command") or run_cmd
        want = int(self.manifest.get("concurrency") or concurrency or 1)
        self.shared_input = self.mode == "process" and mentions_shared_input(
            self.ws / "app", run_cmd
        )
        self.concurrency = 1 if self.shared_input else max(1, want)
        self.sem = asyncio.Semaphore(self.concurrency)
        self.inflight = 0
        self.slots: asyncio.Queue[HandlerSlot] = asyncio.Queue()
        if self.mode == "handler":
            for i in range(self.concurrency):
                self.slots.put_nowait(
                    HandlerSlot(
                        self.handler_cmd,
                        str(self.tmp / "app"),
                        str(self.scratch / f"handler-{i}"),
                        max_stdout,
                    )
                )

    def link_workspace(self) -> None:
        """Point /tmp/<entry> at the read-only build so Job-path paths still resolve."""
        self.tmp.mkdir(parents=True, exist_ok=True)
        for entry in self.ws.iterdir():
            if entry.name in (READY_MARKER, BUILD_TMP):
                continue
            link = self.tmp / entry.name
            try:
                if link.is_symlink() and os.readlink(link) == str(entry):
                    continue
                if link.is_symlink() or link.is_file():
                    link.unlink()
                elif link.is_dir():
                    shutil.rmtree(link)
                link.symlink_to(entry)
            except OSError as e:
                log.warning("could not link %s: %s", link, e)

    def _purge_tmp(self) -> None:
        keep = {e.name for e in self.ws.iterdir()}
        for p in self.tmp.iterdir():
            if p.name in keep:
                continue
            try:
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink()
            except OSError:
                pass

    async def handle(self, req: dict[str, Any]) -> dict[str, Any]:
        async with self.sem:
            self.inflight += 1
            try:
                if self.mode == "handler":
                    return await self._handler_run(req)
                return await self._process_run(req)
            finally:
                self.inflight -= 1

    async def _process_run(self, req: dict[str, Any]) -> dict[str, Any]:
        self.link_workspace()
        home = self.scratch / uuid.uuid4().hex
        home.mkdir(mode=0o700, parents=True)
        input_bytes = json.dumps(req.get("input", {})).encode()
        timeout_s = int(req.get("timeout_s") or 120)
        try:
            (home / "input.json").write_bytes(input_bytes)
            if self.concurrency == 1:
                (self.tmp / "input.json").write_bytes(input_bytes)
            res = await run_process(
                "{ " + self.run_cmd + "; }",
                cwd=str(self.tmp / "app"),
                env=scrub_env(req.get("env"), str(home)),
                stdin_bytes=input_bytes,
                timeout_s=timeout_s,
                limits=run_limits(timeout_s, int(req.get("memory_mb") or 0)),
                max_stdout=self.max_stdout,
            )
        finally:
            shutil.rmtree(home, ignore_errors=True)
            if self.concurrency == 1:
                self._purge_tmp()
        res["ok"] = res["exit_code"] == 0 and not res["timed_out"]
        res["cache"] = "hit"
        res["mode"] = "process"
        return res

    def _fail(self, t0: float, cache: str, **kw: Any) -> dict[str, Any]:
        out = {
            "ok": False,
            "timed_out": False,
            "stdout": "",
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "cache": cache,
            "mode": "handler",
        }
        out.update(kw)
        return out

    async def _handler_run(self, req: dict[str, Any]) -> dict[str, Any]:
        self.link_workspace()
        slot = await self.slots.get()
        t0 = time.monotonic()
        timeout_s = float(req.get("timeout_s") or 120)
        env_items = sorted((req.get("env") or {}).items())
        env_key = hashlib.sha256(json.dumps(env_items).encode()).hexdigest()
        cache = "hit"
        try:
            if not slot.alive() or slot.env_key != env_key:
                cache = "miss"
                await slot.start(
                    scrub_env(req.get("env"), slot.home),
                    env_key,
                    int(req.get("memory_mb") or 0),
                )
            try:
                msg = await slot.call(uuid.uuid4().hex, req.get("input", {}), timeout_s)
            except asyncio.TimeoutError:
                tail = slot.stderr.text()
                await slot.stop()
                return self._fail(
                    t0, cache, exit_code=-9, timed_out=True, stderr_tail=tail
                )
            except (EOFError, BrokenPipeError, ConnectionResetError) as e:
                code = slot.proc.returncode if slot.proc else None
                tail = slot.stderr.text()
                await slot.stop()
                return self._fail(
                    t0,
                    cache,
                    exit_code=code if code is not None else 1,
                    stderr_tail=f"{tail}\nhandler died: {e}",
                )
            ok = "error" not in msg
            stdout = json.dumps(msg.get("output")) if ok else ""
            return {
                "ok": ok,
                "exit_code": 0 if ok else 1,
                "timed_out": False,
                "stdout": stdout[: self.max_stdout],
                "stdout_truncated": len(stdout) > self.max_stdout,
                "stderr_tail": slot.stderr.text()
                + ("" if ok else f"\n{msg.get('error')}"),
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "cache": cache,
                "mode": "handler",
            }
        finally:
            self.slots.put_nowait(slot)


async def serve_exec(executor: Executor, sock_path: str, stop: asyncio.Event) -> None:
    Path(sock_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        os.unlink(sock_path)
    except FileNotFoundError:
        pass

    async def _conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            req = await read_frame(reader)
            try:
                resp = await executor.handle(req)
            except Exception as e:
                log.exception("exec failed")
                resp = {"ok": False, "exit_code": None, "error": f"exec error: {e}"}
            await write_frame(writer, resp)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_unix_server(_conn, path=sock_path)
    os.chmod(sock_path, 0o666)
    async with server:
        await stop.wait()
        idle_since: float | None = None
        while True:
            if executor.inflight == 0:
                idle_since = idle_since or time.monotonic()
                if time.monotonic() - idle_since > 2:
                    break
            else:
                idle_since = None
            await asyncio.sleep(0.2)


# ── gateway ──────────────────────────────────────────────────────────────────

_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1,
    2.5,
    5,
    10,
    30,
    60,
    120,
    300,
    900,
)


class Metrics:
    def __init__(self, runner: str, pool: str):
        self.labels = f'runner="{runner}",pool="{pool}"'
        self.runs: dict[str, int] = {}
        self.cache: dict[str, int] = {}
        self.buckets = [0] * len(_BUCKETS)
        self.dur_sum = 0.0
        self.dur_count = 0
        self.inflight = 0
        self.pending = 0

    def observe(self, outcome: str, cache: str | None, seconds: float | None) -> None:
        self.runs[outcome] = self.runs.get(outcome, 0) + 1
        if cache:
            self.cache[cache] = self.cache.get(cache, 0) + 1
        if seconds is not None:
            self.dur_sum += seconds
            self.dur_count += 1
            for i, b in enumerate(_BUCKETS):
                if seconds <= b:
                    self.buckets[i] += 1

    def render(self) -> str:
        lb = self.labels
        out = [
            "# TYPE abenix_coderunner_inflight gauge",
            f"abenix_coderunner_inflight{{{lb}}} {self.inflight}",
            "# TYPE abenix_coderunner_pending gauge",
            f"abenix_coderunner_pending{{{lb}}} {self.pending}",
            "# TYPE abenix_coderunner_load gauge",
            f"abenix_coderunner_load{{{lb}}} {self.inflight + self.pending}",
            "# TYPE abenix_coderunner_runs_total counter",
        ]
        for k, v in sorted(self.runs.items()):
            out.append(f'abenix_coderunner_runs_total{{{lb},outcome="{k}"}} {v}')
        out.append("# TYPE abenix_coderunner_cache_total counter")
        for k, v in sorted(self.cache.items()):
            out.append(f'abenix_coderunner_cache_total{{{lb},result="{k}"}} {v}')
        out.append("# TYPE abenix_coderunner_duration_seconds histogram")
        for b, c in zip(_BUCKETS, self.buckets):
            out.append(
                f'abenix_coderunner_duration_seconds_bucket{{{lb},le="{b}"}} {c}'
            )
        out.append(
            f'abenix_coderunner_duration_seconds_bucket{{{lb},le="+Inf"}} {self.dur_count}'
        )
        out.append(f"abenix_coderunner_duration_seconds_sum{{{lb}}} {self.dur_sum}")
        out.append(f"abenix_coderunner_duration_seconds_count{{{lb}}} {self.dur_count}")
        return "\n".join(out) + "\n"


def socket_exec_call(sock_path: str) -> Callable[[dict], Awaitable[dict]]:
    async def _call(req: dict[str, Any]) -> dict[str, Any]:
        try:
            reader, writer = await asyncio.open_unix_connection(sock_path)
        except OSError as e:
            return {"ok": False, "refused": True, "reason": f"exec unavailable: {e}"}
        try:
            fwd = {k: req.get(k) for k in ("input", "env", "timeout_s", "memory_mb")}
            await write_frame(writer, fwd)
            timeout = float(req.get("timeout_s") or 120) + 15
            return await asyncio.wait_for(read_frame(reader), timeout)
        except (
            asyncio.IncompleteReadError,
            ConnectionResetError,
            asyncio.TimeoutError,
        ) as e:
            return {
                "ok": False,
                "exit_code": None,
                "error": f"exec connection lost: {e!r}",
            }
        finally:
            writer.close()

    return _call


class Gateway:
    def __init__(
        self,
        *,
        revision: str,
        concurrency: int,
        exec_call: Callable[[dict], Awaitable[dict]],
        pod: str = "",
        max_pending: int | None = None,
        metrics: Metrics | None = None,
    ):
        self.revision = revision
        self.sem = asyncio.Semaphore(max(1, concurrency))
        self.exec_call = exec_call
        self.pod = pod
        self.max_pending = max_pending if max_pending is not None else concurrency * 64
        self.metrics = metrics or Metrics(pod, "")
        self.draining = False
        self._tasks: set[asyncio.Future] = set()

    @property
    def busy(self) -> int:
        return self.metrics.inflight + self.metrics.pending

    async def on_msg(self, msg: Any) -> None:
        t = asyncio.ensure_future(self._handle(msg))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _handle(self, msg: Any) -> None:
        try:
            req = json.loads(msg.data)
        except ValueError:
            resp = {"ok": False, "refused": True, "reason": "bad request"}
        else:
            resp = await self.process(req)
        try:
            await msg.respond(json.dumps(resp).encode())
        except Exception as e:
            log.warning("reply failed: %s", e)

    def _refuse(self, reason: str) -> dict[str, Any]:
        self.metrics.observe("refused", None, None)
        return {"ok": False, "refused": True, "reason": reason, "runner": self.pod}

    async def process(self, req: dict[str, Any]) -> dict[str, Any]:
        if self.draining:
            return self._refuse("draining")
        if str(req.get("revision") or "") != self.revision:
            return self._refuse("revision mismatch")
        if self.metrics.pending >= self.max_pending:
            return self._refuse("busy")
        t0 = time.monotonic()
        self.metrics.pending += 1
        acquired = False
        try:
            await self.sem.acquire()
            acquired = True
            self.metrics.pending -= 1
            self.metrics.inflight += 1
            resp = await self.exec_call(req)
        finally:
            if acquired:
                self.metrics.inflight -= 1
                self.sem.release()
            else:
                self.metrics.pending -= 1
        resp["runner"] = self.pod
        resp["queue_ms"] = max(
            0, int((time.monotonic() - t0) * 1000) - int(resp.get("duration_ms") or 0)
        )
        if resp.get("refused"):
            self.metrics.observe("refused", None, None)
        else:
            if resp.get("ok"):
                outcome = "ok"
            elif resp.get("timed_out"):
                outcome = "timeout"
            else:
                outcome = "error"
            dur = resp.get("duration_ms")
            self.metrics.observe(
                outcome, resp.get("cache"), dur / 1000 if dur is not None else None
            )
        return resp

    async def drain(self, grace_s: float) -> None:
        self.draining = True
        deadline = time.monotonic() + grace_s
        while (self._tasks or self.busy) and time.monotonic() < deadline:
            await asyncio.sleep(0.1)


async def serve_http(port: int, metrics: Metrics, healthy: Callable[[], bool]) -> Any:
    async def _conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = (await asyncio.wait_for(reader.readline(), 5)).decode(
                errors="replace"
            )
            while (await asyncio.wait_for(reader.readline(), 5)) not in (
                b"\r\n",
                b"\n",
                b"",
            ):
                pass
            parts = line.split(" ")
            path = parts[1] if len(parts) > 1 else "/"
            if path.startswith("/metrics"):
                status, body = "200 OK", metrics.render()
                ctype = "text/plain; version=0.0.4"
            elif path.startswith("/healthz"):
                ok = healthy()
                status = "200 OK" if ok else "503 Service Unavailable"
                body, ctype = ("ok\n" if ok else "not ready\n"), "text/plain"
            else:
                status, body, ctype = "404 Not Found", "not found\n", "text/plain"
            data = body.encode()
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\n"
                f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode()
                + data
            )
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    return await asyncio.start_server(_conn, "0.0.0.0", port)


# ── role entrypoints ─────────────────────────────────────────────────────────


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


async def prepare_main() -> int:
    root = Path(_env("CODERUN_BUILD_ROOT", "/tmp"))
    revision = _env("CODERUN_REVISION")
    url = _env("CODERUN_FETCH_URL")
    token = os.environ.pop("CODERUN_FETCH_TOKEN", "")
    build_cmd = _env("CODERUN_BUILD_CMD", "true") or "true"
    build_timeout = int(_env("CODERUN_BUILD_TIMEOUT", "900"))
    max_zip = int(_env("CODERUN_MAX_ZIP_MB", "200")) * 1024 * 1024

    def _get() -> bytes:
        req = urllib.request.Request(url)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read(max_zip + 1)
        if len(data) > max_zip:
            raise ValueError("archive larger than CODERUN_MAX_ZIP_MB")
        return data

    async def _fetch() -> bytes:
        return await asyncio.to_thread(_get)

    async def _build(ws_root: Path) -> None:
        res = await run_process(
            "{ " + build_cmd + "; }",
            cwd=str(ws_root / "app"),
            env=build_env(ws_root),
            stdin_bytes=b"",
            timeout_s=build_timeout,
            limits=run_limits(build_timeout, 0),
            max_stdout=65536,
            max_stderr=65536,
        )
        sys.stderr.write(res["stdout"] + res["stderr_tail"])
        if res["exit_code"] != 0:
            raise RuntimeError(
                f"build failed exit={res['exit_code']} timed_out={res['timed_out']}"
            )

    t0 = time.monotonic()
    state = await Workspace(root, revision).ensure(_fetch, _build)
    log.info("workspace %s (%s) in %.1fs", revision, state, time.monotonic() - t0)
    return 0


async def exec_main() -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    loop.add_signal_handler(signal.SIGINT, stop.set)
    ws = Path(_env("CODERUN_WS", "/ws"))
    if not (ws / READY_MARKER).exists():
        log.error("workspace at %s is not built", ws)
        return 1
    executor = Executor(
        ws=ws,
        tmp=Path(_env("CODERUN_TMP", "/tmp")),
        scratch=Path(_env("CODERUN_SCRATCH", "/scratch")),
        run_cmd=_env("CODERUN_RUN_CMD"),
        concurrency=int(_env("CODERUN_CONCURRENCY", "4")),
        max_stdout=int(_env("CODERUN_MAX_STDOUT", "1000000")),
    )
    executor.link_workspace()
    log.info(
        "exec ready mode=%s concurrency=%d shared_input=%s",
        executor.mode,
        executor.concurrency,
        executor.shared_input,
    )
    await serve_exec(executor, _env("CODERUN_SOCKET", "/run/coderun/exec.sock"), stop)
    return 0


async def gateway_main() -> int:
    import nats  # type: ignore

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    loop.add_signal_handler(signal.SIGINT, stop.set)
    name = _env("CODERUN_NAME", "coderun")
    pod = _env("POD_NAME", name)
    revision = _env("CODERUN_REVISION")
    network = _env("CODERUN_NETWORK", "false").lower() == "true"
    subject = subject_for(
        _env("CODERUN_TENANT"), _env("CODERUN_ASSET"), revision, network
    )
    sock = _env("CODERUN_SOCKET", "/run/coderun/exec.sock")
    concurrency = int(_env("CODERUN_CONCURRENCY", "4"))
    metrics = Metrics(name, pool_for_image(_env("CODERUN_IMAGE")) or "")
    gw = Gateway(
        revision=revision,
        concurrency=concurrency,
        exec_call=socket_exec_call(sock),
        pod=pod,
        max_pending=int(_env("CODERUN_MAX_PENDING", "0")) or None,
        metrics=metrics,
    )
    nc = await nats.connect(
        servers=[_env("NATS_URL", "nats://abenix-nats:4222")],
        user=_env("NATS_USER") or None,
        password=_env("NATS_PASSWORD") or None,
        name=pod,
        max_reconnect_attempts=-1,
        reconnect_time_wait=1,
    )
    for k in ("NATS_USER", "NATS_PASSWORD"):
        os.environ.pop(k, None)
    sub = await nc.subscribe(subject, queue=name, cb=gw.on_msg)
    http = await serve_http(
        int(_env("CODERUN_METRICS_PORT", "9464")),
        metrics,
        lambda: nc.is_connected and not gw.draining and os.path.exists(sock),
    )
    log.info("gateway %s on %s queue=%s", pod, subject, name)
    await stop.wait()
    log.info("draining")
    try:
        await sub.unsubscribe()
    except Exception:
        pass
    await gw.drain(float(_env("CODERUN_DRAIN_SECONDS", "900")))
    http.close()
    await nc.close()
    return 0


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    role = argv[1] if len(argv) > 1 else ""
    entry = {"prepare": prepare_main, "exec": exec_main, "gateway": gateway_main}.get(
        role
    )
    if entry is None:
        print("usage: runner.py prepare|exec|gateway", file=sys.stderr)
        return 2
    try:
        return asyncio.run(entry())
    except Exception:
        log.exception("%s failed", role)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
