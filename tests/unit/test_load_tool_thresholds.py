"""Load tools turn measured numbers into PASS or FAIL lines and an exit code."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.telemetry import loadtest

ROOT = Path(__file__).resolve().parents[2]
NAN = float("nan")


def load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


decision_load = load("scripts/load/decision_load.py", "decision_load_under_test")
code_runner = load("scripts/load/code_runner_bench.py", "code_runner_under_test")
middleware = load("scripts/load/middleware_bench.py", "middleware_under_test")
sim = load("infra/helm/testbed/sim/sim.py", "sim_under_test")


def run_tool(rel: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / rel), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


# decision_load


def decision_report(ok=1000, errors=None, rps=500.0, p95=200.0):
    return {"ok": ok, "errors": errors or {}, "rps": rps, "p95_ms": p95}


def test_decision_passes_and_prints_one_line_per_threshold(capsys):
    assert decision_load.evaluate(decision_report(), 100, 0.05, 5000) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "PASS rps measured=500.0 limit=100",
        "PASS error_rate measured=0.0 limit=0.05",
        "PASS p95_ms measured=200.0 limit=5000",
    ]


@pytest.mark.parametrize(
    "report,failed",
    [
        (decision_report(rps=99.0), "rps"),
        (decision_report(errors={"500": 100}), "error_rate"),
        (decision_report(p95=5001.0), "p95_ms"),
    ],
)
def test_decision_fails_on_each_limit(report, failed, capsys):
    assert decision_load.evaluate(report, 100, 0.05, 5000) == 1
    assert f"FAIL {failed} " in capsys.readouterr().out


def test_decision_zero_samples_is_never_a_pass():
    report = decision_report(ok=0, errors={"ConnectError": 9}, rps=0.0, p95=0.0)
    assert decision_load.evaluate(report, 0, -1, 0) == 2


def test_decision_limit_of_zero_turns_off_floor_and_latency(capsys):
    report = decision_report(rps=1.0, p95=99999.0)
    assert decision_load.evaluate(report, 0, 0.05, 0) == 0
    assert capsys.readouterr().out.count("\n") == 1


class _Evaluate(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        doc = {"data": {"version": {"version": 1}, "trace_hash": body["as_of"]}}
        raw = json.dumps(doc).encode()
        self.send_response(200)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args):
        pass


@pytest.fixture
def evaluate_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Evaluate)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


DECISION_ARGS = ("--token", "t", "--key", "k", "--concurrency", "2", "--seconds", "1")


def test_decision_script_really_sends_requests(evaluate_server, tmp_path):
    r = run_tool(
        "scripts/load/decision_load.py",
        "--base",
        evaluate_server,
        *DECISION_ARGS,
        "--min-rps",
        "1",
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS rps" in r.stdout


def test_decision_script_exits_one_on_a_missed_limit(evaluate_server, tmp_path):
    r = run_tool(
        "scripts/load/decision_load.py",
        "--base",
        evaluate_server,
        *DECISION_ARGS,
        "--min-rps",
        "100000000",
        cwd=tmp_path,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL rps" in r.stdout


def test_decision_script_unreachable_target_exits_two(tmp_path):
    r = run_tool(
        "scripts/load/decision_load.py",
        "--base",
        "http://127.0.0.1:1",
        *DECISION_ARGS,
        cwd=tmp_path,
    )
    assert r.returncode == 2, r.stdout + r.stderr


def test_decision_script_bad_args_exit_two(tmp_path):
    r = run_tool("scripts/load/decision_load.py", "--base", "x", cwd=tmp_path)
    assert r.returncode == 2


# code_runner_bench


def warm(errors=0, p50=20.0, p99=50.0):
    return {
        "scenario": "warm",
        "calls": 200,
        "errors": errors,
        "p50_ms": p50,
        "p99_ms": p99,
    }


def concurrent(errors=0, per_s=50.0):
    return {
        "scenario": "concurrency",
        "calls": 500,
        "errors": errors,
        "calls_per_s": per_s,
    }


def cold(seconds=30.0, errors=0):
    return {
        "scenario": "cold",
        "calls": 5,
        "errors": errors,
        "seconds_until_warm": seconds,
    }


def zero(seconds=30.0):
    return {
        "scenario": "zero",
        "calls": 5,
        "errors": 0,
        "seconds_until_warm_again": seconds,
    }


def test_code_runner_passes_with_defaults(capsys):
    assert code_runner.evaluate([cold(), warm(), zero(), {}, concurrent()]) == 0
    out = capsys.readouterr().out
    for name in (
        "cold_wake_seconds",
        "zero_wake_seconds",
        "warm_p50_ms",
        "warm_p99_ms",
        "concurrency_calls_per_s",
        "warm_failed_calls",
    ):
        assert f"PASS {name} " in out
    assert "FAIL" not in out


@pytest.mark.parametrize(
    "results,failed",
    [
        ([warm(p50=501.0)], "warm_p50_ms"),
        ([warm(p99=5001.0)], "warm_p99_ms"),
        ([warm(errors=1)], "warm_failed_calls"),
        ([concurrent(per_s=9.0)], "concurrency_calls_per_s"),
        ([cold(seconds=181.0)], "cold_wake_seconds"),
        ([zero(seconds=181.0)], "zero_wake_seconds"),
        ([cold(seconds=NAN)], "cold_wake_seconds"),
        ([warm(p50=NAN)], "warm_p50_ms"),
    ],
)
def test_code_runner_fails_on_each_limit(results, failed, capsys):
    assert code_runner.evaluate(results) == 1
    assert f"FAIL {failed} " in capsys.readouterr().out


@pytest.mark.parametrize("results", [[], [{}], [warm(errors=200, p50=NAN, p99=NAN)]])
def test_code_runner_zero_samples_is_never_a_pass(results):
    assert code_runner.evaluate(results, max_failed=-1) == 2


def test_code_runner_prints_numbers_plainly(capsys):
    code_runner.print_measured([warm(), {}])
    out = capsys.readouterr().out
    assert out == "MEASURED scenario=warm calls=200 errors=0 p50_ms=20.0 p99_ms=50.0\n"


def test_code_runner_runs_alone_from_any_directory(tmp_path):
    copy = tmp_path / "bench.py"
    shutil.copy(ROOT / "scripts/load/code_runner_bench.py", copy)
    r = subprocess.run(
        [sys.executable, str(copy), "--asset", "a", "--scenario", "nope"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2
    assert "--scenario" in r.stderr


def test_code_runner_engine_failure_exits_two(tmp_path):
    copy = tmp_path / "bench.py"
    shutil.copy(ROOT / "scripts/load/code_runner_bench.py", copy)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    r = subprocess.run(
        [sys.executable, str(copy), "--asset", "a"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 2, r.stdout + r.stderr


# middleware_bench


def rates(bare=10000.0, old=2000.0, new=8000.0):
    return {"/api/health": {"bare": bare, "old": old, "new": new}}


def test_middleware_passes(capsys):
    assert middleware.evaluate(rates()) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "PASS health_new_ms_per_request measured=0.125 limit=5",
        "PASS health_overhead_ms measured=0.025 limit=2",
        "PASS health_speedup measured=4.0 limit=1.5",
    ]


@pytest.mark.parametrize(
    "measured,failed",
    [
        (rates(new=100.0, old=50.0), "health_new_ms_per_request"),
        (rates(bare=10000.0, new=400.0, old=100.0), "health_overhead_ms"),
        (rates(old=7000.0), "health_speedup"),
    ],
)
def test_middleware_fails_on_each_limit(measured, failed, capsys):
    assert middleware.evaluate(measured) == 1
    assert f"FAIL {failed} " in capsys.readouterr().out


@pytest.mark.parametrize("measured", [{}, rates(new=0.0)])
def test_middleware_zero_samples_is_never_a_pass(measured):
    assert middleware.evaluate(measured) == 2


def test_middleware_import_leaves_the_environment_alone():
    assert os.environ.get("IP_WHITELIST", "") != "0.0.0.0/0,::/0"


@pytest.mark.parametrize("limit,code,word", [("0", 0, "PASS"), ("0.000001", 1, "FAIL")])
def test_middleware_script_end_to_end(limit, code, word, tmp_path):
    r = run_tool(
        "scripts/load/middleware_bench.py",
        "--requests",
        "20",
        "--concurrency",
        "5",
        "--rounds",
        "1",
        "--max-new-ms",
        limit,
        "--max-overhead-ms",
        "0",
        "--min-speedup",
        "0",
        cwd=tmp_path,
    )
    if limit == "0":
        assert r.returncode == 0, r.stdout + r.stderr
        assert "new_ms_per_request" not in r.stdout
    else:
        assert r.returncode == code, r.stdout + r.stderr
        assert f"{word} health_new_ms_per_request" in r.stdout


# telemetry loadtest


def t2_report(**over):
    doc = {
        "published_total": 90000,
        "published_per_second": 1600.0,
        "ingested_per_second": 1590.0,
        "lost_messages": 0,
        "read_errors": 0,
    }
    return {**doc, **over}


def test_telemetry_passes(capsys):
    assert loadtest.evaluate(t2_report(), 400, 0.5, 0, 0) == 0
    assert capsys.readouterr().out.splitlines() == [
        "PASS held_rate measured=1590.0 limit=400",
        "PASS held_ratio measured=0.994 limit=0.5",
        "PASS lost_messages measured=0 limit=0",
        "PASS errors measured=0 limit=0",
    ]


@pytest.mark.parametrize(
    "over,failed",
    [
        ({"ingested_per_second": 399.0}, "held_rate"),
        ({"published_per_second": 4000.0}, "held_ratio"),
        ({"lost_messages": 1}, "lost_messages"),
        ({"read_errors": 1}, "errors"),
        ({"viewer_errors_total": 1}, "errors"),
    ],
)
def test_telemetry_fails_on_each_limit(over, failed, capsys):
    assert loadtest.evaluate(t2_report(**over), 400, 0.5, 0, 0) == 1
    assert f"FAIL {failed} " in capsys.readouterr().out


@pytest.mark.parametrize(
    "over",
    [
        {"published_total": 0, "published_per_second": 0.0},
        {"ingested_per_second": 0.0},
    ],
)
def test_telemetry_zero_samples_is_never_a_pass(over):
    assert loadtest.evaluate(t2_report(**over), 0, 0, -1, -1) == 2


def test_telemetry_default_floor_follows_the_offered_rate():
    assert loadtest.default_min_rate("t2", 200) == 400
    assert loadtest.default_min_rate("t7", 40) == 500
    assert loadtest.default_min_rate("t7", 200) == 2500


def test_telemetry_loss_counts_only_this_run():
    before = loadtest.loss_counters({"throttled": "7"}, {"dropped": 3})
    after = loadtest.loss_counters({"throttled": "7"}, {"dropped": 5})
    assert loadtest.loss_since(before, after) == {"dropped": 2, "throttled": 0}
    restarted = loadtest.loss_counters({}, {"dropped": None})
    assert loadtest.loss_since(before, restarted) == {"dropped": 0, "throttled": 0}


def test_telemetry_main_exits_with_the_verdict(monkeypatch, capsys):
    async def fake_t2(_seconds, _keep):
        return t2_report(lost_messages=4)

    monkeypatch.setattr(loadtest, "t2", fake_t2)
    monkeypatch.setattr(sys, "argv", ["loadtest", "t2"])
    with pytest.raises(SystemExit) as e:
        loadtest.main()
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert "FAIL lost_messages measured=4 limit=0" in out
    assert out.index("REPORT ") < out.index("FAIL lost_messages")


def test_telemetry_main_exits_two_when_it_cannot_run(monkeypatch):
    async def fake_t2(_seconds, _keep):
        raise RuntimeError("no enabled connection")

    monkeypatch.setattr(loadtest, "t2", fake_t2)
    monkeypatch.setattr(sys, "argv", ["loadtest", "t2"])
    with pytest.raises(SystemExit) as e:
        loadtest.main()
    assert e.value.code == 2


# telemetry-loadtest.sh against a stand in kubectl

FAKE_KUBECTL = """#!/bin/sh
case "$*" in
  *"apply -f"*) cat > "$FAKE_DIR/manifest.yaml"; exit 0 ;;
  *"delete job"*) exit 0 ;;
  *"logs "*) cat "$FAKE_DIR/pod.log"; exit 0 ;;
esac
[ -n "$FAKE_KUBECTL_DOWN" ] && exit 1
case "$*" in
  *readyReplicas*) echo 1 ;;
  *imagePullPolicy*) echo IfNotPresent ;;
  *containers*image*) echo img:1 ;;
  *"get pods"*) echo pod-1 ;;
  *exitCode*) echo "$FAKE_EXIT" ;;
  *status.phase*) echo "$FAKE_PHASE" ;;
esac
"""

REPORT = 'REPORT {"lost_messages": 0}\n'


def wrapper(tmp_path, *args, log="", code="0", phase="Succeeded", **env_over):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "kubectl"
    fake.write_text(FAKE_KUBECTL)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "pod.log").write_text(log)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DIR": str(tmp_path),
        "FAKE_EXIT": code,
        "FAKE_PHASE": phase,
        "LOADTEST_OUT_DIR": str(tmp_path / "out"),
        **env_over,
    }
    return subprocess.run(
        ["/bin/bash", str(ROOT / "scripts/telemetry-loadtest.sh"), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_wrapper_passes_on_exit_zero(tmp_path):
    log = REPORT + "PASS held_rate measured=1590.0 limit=400\n"
    r = wrapper(tmp_path, "t2", log=log)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.rstrip().endswith("PASS held_rate measured=1590.0 limit=400")


def test_wrapper_propagates_a_failed_threshold(tmp_path):
    log = REPORT + "FAIL lost_messages measured=4 limit=0\n"
    r = wrapper(tmp_path, "t2", log=log, code="1", phase="Failed")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL lost_messages measured=4 limit=0" in r.stdout


def test_wrapper_no_report_exits_two(tmp_path):
    r = wrapper(tmp_path, "t2", log="traceback\n", code="1", phase="Failed")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "no report" in r.stdout


def test_wrapper_empty_log_still_reaches_no_report(tmp_path):
    r = wrapper(tmp_path, "t2", log="", code="1", phase="Failed")
    assert r.returncode == 2
    assert "no report" in r.stdout


def test_wrapper_old_image_without_threshold_lines_is_not_a_pass(tmp_path):
    r = wrapper(tmp_path, "t2", log=REPORT)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "rebuild the API image" in r.stdout


def test_wrapper_zero_samples_exits_two(tmp_path):
    r = wrapper(tmp_path, "t2", log=REPORT, code="2", phase="Failed")
    assert r.returncode == 2


def test_wrapper_oom_killed_exits_two(tmp_path):
    log = REPORT + "PASS errors measured=0 limit=0\n"
    r = wrapper(tmp_path, "t2", log=log, code="137", phase="Failed")
    assert r.returncode == 2


def test_wrapper_without_an_exit_code_uses_the_lines(tmp_path):
    log = REPORT + "FAIL errors measured=2 limit=0\n"
    r = wrapper(tmp_path, "t2", log=log, code="", phase="Failed")
    assert r.returncode == 1, r.stdout + r.stderr


def test_wrapper_unreachable_cluster_exits_two(tmp_path):
    r = wrapper(tmp_path, "t2", FAKE_KUBECTL_DOWN="1")
    assert r.returncode == 2, r.stdout + r.stderr


@pytest.mark.parametrize(
    "args",
    [("t9",), ("t2", "--nope", "1"), ("t2", "--max-lost"), ("t2", "--max-lost", "x")],
)
def test_wrapper_bad_args_exit_two(tmp_path, args):
    assert wrapper(tmp_path, *args).returncode == 2


def test_wrapper_hands_thresholds_to_the_job_and_flags_win(tmp_path):
    log = REPORT + "PASS errors measured=0 limit=0\n"
    r = wrapper(
        tmp_path,
        "t2",
        "--min-rate",
        "800",
        log=log,
        LOADTEST_MIN_RATE="100",
        LOADTEST_MAX_LOST="3",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    manifest = (tmp_path / "manifest.yaml").read_text()
    assert manifest.index('"--min-rate", "100"') < manifest.index('"--min-rate", "800"')
    assert '"--max-lost", "3"' in manifest


def test_wrapper_stays_bash_32_clean():
    subprocess.run(
        ["/bin/bash", "-n", str(ROOT / "scripts/telemetry-loadtest.sh")], check=True
    )


# locustfile, against a stand in locust so the test needs no install


class _Worker:
    pass


@pytest.fixture
def locustfile(monkeypatch):
    listeners = []
    locust = types.ModuleType("locust")
    locust.HttpUser = object
    locust.between = lambda *_a: None
    locust.task = lambda _w: lambda f: f
    locust.events = types.SimpleNamespace(
        quitting=types.SimpleNamespace(
            add_listener=lambda f: (listeners.append(f), f)[1]
        )
    )
    runners = types.ModuleType("locust.runners")
    runners.WorkerRunner = _Worker
    monkeypatch.setitem(sys.modules, "locust", locust)
    monkeypatch.setitem(sys.modules, "locust.runners", runners)
    for name in ("LOCUST_MAX_FAIL_RATIO", "LOCUST_MAX_P95_MS", "LOCUST_MIN_RPS"):
        monkeypatch.delenv(name, raising=False)
    mod = load("tests/load/locustfile.py", "locustfile_under_test")
    mod.listener = listeners[0]
    return mod


def quit_with(mod, requests=1000, failures=0, p95=100.0, rps=20.0, runner=None):
    total = types.SimpleNamespace(
        num_requests=requests,
        num_failures=failures,
        total_rps=rps,
        get_response_time_percentile=lambda _q: p95,
    )
    env = types.SimpleNamespace(
        runner=runner,
        stats=types.SimpleNamespace(total=total),
        process_exit_code=None,
    )
    mod.listener(environment=env)
    return env.process_exit_code


def test_locust_passes(locustfile, capsys):
    assert quit_with(locustfile) == 0
    assert capsys.readouterr().out.splitlines() == [
        "PASS fail_ratio measured=0.0 limit=0.05",
        "PASS p95_ms measured=100.0 limit=3000.0",
        "PASS rps measured=20.0 limit=0.2",
    ]


@pytest.mark.parametrize(
    "over,failed",
    [
        ({"failures": 100}, "fail_ratio"),
        ({"p95": 3001.0}, "p95_ms"),
        ({"rps": 0.1}, "rps"),
    ],
)
def test_locust_fails_on_each_limit(locustfile, over, failed, capsys):
    assert quit_with(locustfile, **over) == 1
    assert f"FAIL {failed} " in capsys.readouterr().out


@pytest.mark.parametrize("over", [{"requests": 0}, {"requests": 5, "failures": 5}])
def test_locust_zero_samples_is_never_a_pass(locustfile, over, monkeypatch):
    monkeypatch.setenv("LOCUST_MAX_FAIL_RATIO", "1")
    assert quit_with(locustfile, **over) == 2


def test_locust_limits_come_from_the_environment(locustfile, monkeypatch):
    monkeypatch.setenv("LOCUST_MAX_P95_MS", "50")
    assert quit_with(locustfile) == 1
    monkeypatch.setenv("LOCUST_MAX_P95_MS", "0")
    assert quit_with(locustfile) == 0
    monkeypatch.setenv("LOCUST_MIN_RPS", "100")
    assert quit_with(locustfile) == 1


def test_locust_bad_limit_exits_two(locustfile, monkeypatch):
    monkeypatch.setenv("LOCUST_MIN_RPS", "fast")
    assert quit_with(locustfile) == 2


def test_locust_worker_leaves_the_verdict_to_the_master(locustfile):
    assert quit_with(locustfile, requests=0, runner=_Worker()) is None


def test_locust_calls_only_routes_that_exist():
    source = (ROOT / "tests/load/locustfile.py").read_text()
    routes = (ROOT / "apps/api/app/routers/analytics.py").read_text()
    assert "/api/analytics/overview" in source
    assert '@router.get("/overview")' in routes
    assert "/api/analytics/summary" not in source


# testbed-load burst


def test_testbed_burst_passes(capsys):
    assert sim.load_verdict(100000, 0, 25.0, 1250, 0) == 0
    assert capsys.readouterr().out.splitlines() == [
        "PASS delivered_rate measured=4000.0 limit=1250",
        "PASS failed_messages measured=0 limit=0",
    ]


@pytest.mark.parametrize(
    "delivered,failed_count,seconds,name",
    [
        (100000, 0, 100.0, "delivered_rate"),
        (99999, 1, 25.0, "failed_messages"),
    ],
)
def test_testbed_burst_fails_on_each_limit(
    delivered, failed_count, seconds, name, capsys
):
    assert sim.load_verdict(delivered, failed_count, seconds, 1250, 0) == 1
    assert f"FAIL {name} " in capsys.readouterr().out


def test_testbed_burst_zero_samples_is_never_a_pass():
    assert sim.load_verdict(0, 100, 25.0, 0, -1) == 2


def test_testbed_chart_hands_thresholds_to_the_job():
    template = (ROOT / "infra/helm/testbed/templates/sims.yaml").read_text()
    assert "LOAD_MIN_RATE" in template
    assert "LOAD_MAX_FAILED" in template


class _Producer:
    fail_start = False
    fail_every = 0

    def __init__(self, **_kw):
        self.sent = 0

    async def start(self):
        if self.fail_start:
            raise OSError("no broker")

    async def send(self, *_a, **_kw):
        self.sent += 1
        fut = asyncio.get_running_loop().create_future()
        if self.fail_every and self.sent % self.fail_every == 0:
            fut.set_exception(OSError("not acked"))
        else:
            fut.set_result(None)
        return fut

    async def flush(self):
        pass

    async def stop(self):
        pass


def burst(monkeypatch, **env):
    kafka = types.ModuleType("aiokafka")
    kafka.AIOKafkaProducer = _Producer
    monkeypatch.setitem(sys.modules, "aiokafka", kafka)

    async def no_topics(_topics):
        pass

    monkeypatch.setattr(sim, "ensure_topics", no_topics)
    monkeypatch.setattr(sim, "kafka_kwargs", lambda: {})
    monkeypatch.setenv("LOAD_COUNT", "20")
    monkeypatch.setenv("LOAD_RATE", "100000")
    monkeypatch.setenv("LOAD_MIN_RATE", "1")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    try:
        asyncio.run(sim.role_load())
    except SystemExit as e:
        return e.code
    return 0


def test_testbed_burst_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(_Producer, "fail_every", 0)
    assert burst(monkeypatch) == 0
    assert "PASS failed_messages measured=0 limit=0" in capsys.readouterr().out
    monkeypatch.setattr(_Producer, "fail_every", 5)
    assert burst(monkeypatch) == 1
    assert "FAIL failed_messages measured=4 limit=0" in capsys.readouterr().out
    assert burst(monkeypatch, LOAD_MAX_FAILED="4") == 0
    monkeypatch.setattr(_Producer, "fail_every", 1)
    assert burst(monkeypatch, LOAD_MAX_FAILED="-1") == 2
    monkeypatch.setattr(_Producer, "fail_every", 0)
    assert burst(monkeypatch, LOAD_MIN_RATE="fast") == 2
    monkeypatch.setattr(_Producer, "fail_start", True)
    assert burst(monkeypatch) == 2
