"""Cold vs warm code asset latency through the real code_asset tool.

Run it inside an agent-runtime pod, where DATABASE_URL, REDIS_URL, NATS_URL,
the CODE_RUNNER_* settings and the service account are already present:

    kubectl -n abenix cp scripts/load/code_runner_bench.py <pod>:/tmp/bench.py
    kubectl -n abenix exec <pod> -- python /tmp/bench.py --asset <id> \
        --api http://abenix-api:8000 --token <bearer> --scenario all

Scenarios: cold (runner deleted), warm (sequential), zero (scaled to zero and
back), version (new version uploaded under load), concurrency (N at once).

Exits 0 when every threshold holds, 1 when one fails, 2 when it could not run or got no answers.
This file stays self contained because it is copied into the pod on its own.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

SCENARIOS = ["cold", "warm", "zero", "version", "concurrency"]
PLAIN_NUMBERS = (
    "scenario",
    "calls",
    "errors",
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "overhead_p50_ms",
    "overhead_p95_ms",
    "calls_per_s",
    "first_call_runner",
    "first_call_ms",
    "seconds_until_warm",
    "seconds_until_warm_again",
)

cr: Any = None
CodeAssetTool: Any = None


def load_engine() -> None:
    global cr, CodeAssetTool
    here = Path(__file__).resolve().parents
    for p in (
        "/app/apps/agent-runtime",
        str(here[2] / "apps" / "agent-runtime") if len(here) > 2 else "",
    ):
        if p and Path(p).is_dir() and p not in sys.path:
            sys.path.insert(0, p)
    from engine import code_runners
    from engine.tools.code_asset import CodeAssetTool as tool

    cr, CodeAssetTool = code_runners, tool


def pct(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q / 100 * (len(xs) - 1))))]


def check(name: str, measured: float, limit: float, ceiling: bool = True) -> bool:
    ok = measured <= limit if ceiling else measured >= limit
    print(
        f"{'PASS' if ok else 'FAIL'} {name} measured={measured} limit={limit}",
        flush=True,
    )
    return ok


def print_measured(results: list[dict]) -> None:
    for r in results:
        if r:
            pairs = (f"{k}={r[k]}" for k in PLAIN_NUMBERS if k in r)
            print("MEASURED " + " ".join(pairs), flush=True)


def evaluate(
    results: list[dict],
    max_p50_ms: float = 500,
    max_p99_ms: float = 5000,
    min_calls_per_s: float = 10,
    max_failed: int = 0,
    max_wake_seconds: float = 180,
) -> int:
    ran = [r for r in results if r]
    empty = [r["scenario"] for r in ran if r["calls"] <= r["errors"]]
    if not ran or empty:
        print(f"no successful calls, scenarios {empty or 'none ran'}", flush=True)
        return 2
    checks = []
    for r in ran:
        name = r["scenario"]
        if max_failed >= 0:
            checks.append(check(f"{name}_failed_calls", r["errors"], max_failed))
        if name == "warm" and max_p50_ms > 0:
            checks.append(check("warm_p50_ms", r["p50_ms"], max_p50_ms))
        if name == "warm" and max_p99_ms > 0:
            checks.append(check("warm_p99_ms", r["p99_ms"], max_p99_ms))
        if name == "concurrency" and min_calls_per_s > 0:
            checks.append(
                check(
                    "concurrency_calls_per_s",
                    r["calls_per_s"],
                    min_calls_per_s,
                    ceiling=False,
                )
            )
        wake = r.get("seconds_until_warm", r.get("seconds_until_warm_again"))
        if wake is not None and max_wake_seconds > 0:
            checks.append(check(f"{name}_wake_seconds", wake, max_wake_seconds))
    return 0 if all(checks) else 1


def summary(name: str, rows: list[dict]) -> dict:
    ok = [r for r in rows if r["ok"]]
    total = [r["ms"] for r in ok]
    over = [r["ms"] - r["run_ms"] for r in ok if r.get("run_ms") is not None]
    out = {
        "scenario": name,
        "calls": len(rows),
        "errors": len(rows) - len(ok),
        "runner": dict(Counter(r["runner"] for r in rows)),
        "p50_ms": round(pct(total, 50), 1),
        "p95_ms": round(pct(total, 95), 1),
        "p99_ms": round(pct(total, 99), 1),
        "overhead_p50_ms": round(pct(over, 50), 1),
        "overhead_p95_ms": round(pct(over, 95), 1),
    }
    print(json.dumps(out))
    return out


class Bench:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.db = os.environ.get("DATABASE_URL", "")
        self.redis = os.environ.get("REDIS_URL", "")
        self.input = json.loads(args.input)
        self.asset: dict = {}

    async def load(self) -> None:
        assets = await cr._load_assets(self.db, [self.args.asset])
        if self.args.asset not in assets:
            print(f"asset {self.args.asset} not found", file=sys.stderr, flush=True)
            sys.exit(2)
        self.asset = assets[self.args.asset]

    def tool(self) -> CodeAssetTool:
        return CodeAssetTool(
            tenant_id=self.asset["tenant_id"], redis_url=self.redis, db_url=self.db
        )

    async def call(self) -> dict:
        t0 = time.perf_counter()
        res = await self.tool().execute(
            {
                "code_asset_id": self.args.asset,
                "input": self.input,
                "timeout_seconds": self.args.timeout,
            }
        )
        md = res.metadata or {}
        return {
            "ok": not res.is_error,
            "ms": (time.perf_counter() - t0) * 1000,
            "run_ms": md.get("run_ms"),
            "runner": md.get("runner", "?"),
            "name": md.get("runner_name") or "",
            "reason": md.get("runner_reason") or "",
            "error": res.content[:300] if res.is_error else "",
        }

    async def wait_warm(self, limit_s: float) -> tuple[float, list[dict]]:
        t0 = time.perf_counter()
        rows = []
        while time.perf_counter() - t0 < limit_s:
            r = await self.call()
            rows.append(r)
            if r["runner"] == "warm":
                return time.perf_counter() - t0, rows
            await asyncio.sleep(1)
        return float("nan"), rows

    def spec(self):
        return cr.spec_for(self.asset, self.asset["tenant_id"], False, cr.settings())

    async def cold(self) -> dict:
        spec = self.spec()
        k = cr.K8s(cr.settings())
        k.delete(spec.name)
        while k.get_deployment(spec.name) is not None:
            await asyncio.sleep(1)
        await asyncio.sleep(3)
        cr._kicked.clear()
        first = await self.call()
        took, rows = await self.wait_warm(self.args.warm_limit)
        out = {
            "scenario": "cold",
            "calls": len(rows) + 1,
            "errors": sum(1 for r in [first, *rows] if not r["ok"]),
            "first_call_runner": first["runner"],
            "first_call_ms": round(first["ms"], 1),
            "first_call_reason": first["reason"],
            "seconds_until_warm": round(took, 1),
            "calls_while_warming": len(rows),
            "first_warm_ms": round(rows[-1]["ms"], 1) if rows else None,
        }
        print(json.dumps(out))
        return out

    async def warm(self) -> dict:
        _, _ = await self.wait_warm(self.args.warm_limit)
        rows = [await self.call() for _ in range(self.args.n)]
        return summary("warm", rows)

    async def zero(self) -> dict:
        await self.wait_warm(self.args.warm_limit)
        print(await cr.scale_asset_to_zero(self.db, self.args.asset))
        spec = self.spec()
        k = cr.K8s(cr.settings())
        while True:
            pods = k.core.list_namespaced_pod(
                k.ns, label_selector=f"abenix.io/code-runner={spec.name}"
            ).items
            if not pods:
                break
            await asyncio.sleep(2)
        cr._kicked.clear()
        first = await self.call()
        took, rows = await self.wait_warm(self.args.warm_limit)
        out = {
            "scenario": "zero",
            "calls": len(rows) + 1,
            "errors": sum(1 for r in [first, *rows] if not r["ok"]),
            "first_call_runner": first["runner"],
            "first_call_ms": round(first["ms"], 1),
            "seconds_until_warm_again": round(took, 1),
            "errors_while_warming": sum(1 for r in rows if not r["ok"]),
        }
        print(json.dumps(out))
        return out

    def _api(
        self, method: str, path: str, data: bytes | None = None, ctype: str = ""
    ) -> bytes:
        req = urllib.request.Request(
            self.args.api.rstrip("/") + path, data=data, method=method
        )
        req.add_header("Authorization", f"Bearer {self.args.token}")
        if ctype:
            req.add_header("Content-Type", ctype)
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read()

    def upload_same_code_as_new_version(self) -> None:
        zip_bytes = self._api("GET", f"/api/code-assets/{self.args.asset}/download")
        boundary = uuid.uuid4().hex
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n{{}}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="asset.zip"\r\n'
                "Content-Type: application/zip\r\n\r\n"
            ).encode()
            + zip_bytes
            + f"\r\n--{boundary}--\r\n".encode()
        )
        self._api(
            "POST",
            f"/api/code-assets/{self.args.asset}/versions",
            body,
            f"multipart/form-data; boundary={boundary}",
        )

    async def version(self) -> dict:
        if not (self.args.api and self.args.token):
            print(
                json.dumps(
                    {"scenario": "version", "skipped": "needs --api and --token"}
                )
            )
            return {}
        await self.wait_warm(self.args.warm_limit)
        rows: list[dict] = []
        stop = asyncio.Event()

        async def worker():
            while not stop.is_set():
                rows.append(await self.call())

        tasks = [asyncio.ensure_future(worker()) for _ in range(self.args.version_load)]
        await asyncio.sleep(5)
        before = self.spec().name
        await asyncio.to_thread(self.upload_same_code_as_new_version)
        await self.load()
        after = self.spec().name
        await asyncio.sleep(self.args.version_seconds)
        stop.set()
        await asyncio.gather(*tasks)
        out = summary("version", rows)
        out.update(
            {
                "old_runner": before,
                "new_runner": after,
                "calls_by_runner": dict(
                    Counter(r["name"] or r["runner"] for r in rows)
                ),
                "error_samples": [r["error"] for r in rows if not r["ok"]][:3],
            }
        )
        print(json.dumps(out))
        return out

    async def concurrency(self) -> dict:
        await self.wait_warm(self.args.warm_limit)
        t0 = time.perf_counter()
        rows = await asyncio.gather(
            *(self.call() for _ in range(self.args.concurrency))
        )
        wall = time.perf_counter() - t0
        out = summary("concurrency", list(rows))
        out["wall_s"] = round(wall, 2)
        out["calls_per_s"] = round(sum(1 for r in rows if r["ok"]) / wall, 1)
        out["error_samples"] = [r["error"] for r in rows if not r["ok"]][:3]
        print(json.dumps(out))
        return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", required=True, help="code asset id")
    ap.add_argument("--nats", default="", help="NATS URL, defaults to NATS_URL")
    ap.add_argument(
        "--api", default="", help="API base URL, needed for the version scenario"
    )
    ap.add_argument(
        "--token", default="", help="API bearer token, needed for the version scenario"
    )
    ap.add_argument("--input", default="{}", help="JSON input for every call")
    ap.add_argument(
        "--scenario",
        default="all",
        help="all or a comma list of cold,warm,zero,version,concurrency",
    )
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--concurrency", type=int, default=500)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--warm-limit", type=float, default=300)
    ap.add_argument("--version-load", type=int, default=20)
    ap.add_argument("--version-seconds", type=float, default=60)
    ap.add_argument(
        "--max-p50-ms", type=float, default=500, help="warm p50, 0 means not checked"
    )
    ap.add_argument(
        "--max-p99-ms", type=float, default=5000, help="warm p99, 0 means not checked"
    )
    ap.add_argument(
        "--min-calls-per-s",
        type=float,
        default=10,
        help="concurrency scenario, 0 means not checked",
    )
    ap.add_argument(
        "--max-failed",
        type=int,
        default=0,
        help="failed calls per scenario, below 0 means not checked",
    )
    ap.add_argument(
        "--max-wake-seconds",
        type=float,
        default=180,
        help="cold and zero, seconds until warm, 0 means not checked",
    )
    args = ap.parse_args()
    wanted = (
        SCENARIOS
        if args.scenario == "all"
        else [s.strip() for s in args.scenario.split(",")]
    )
    if set(wanted) - set(SCENARIOS):
        ap.error(f"--scenario takes all or a comma list of {','.join(SCENARIOS)}")
    if args.nats:
        os.environ["NATS_URL"] = args.nats
    os.environ.setdefault("CODE_RUNNER_MODE", "auto")
    load_engine()
    b = Bench(args)
    await b.load()
    results = []
    for name in SCENARIOS:
        if name in wanted:
            results.append(await getattr(b, name)())
    print("SUMMARY " + json.dumps(results))
    print_measured(results)
    return evaluate(
        results,
        args.max_p50_ms,
        args.max_p99_ms,
        args.min_calls_per_s,
        args.max_failed,
        args.max_wake_seconds,
    )


def cli() -> int:
    try:
        return asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print(f"code runner bench could not run, {exc!r}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(cli())
