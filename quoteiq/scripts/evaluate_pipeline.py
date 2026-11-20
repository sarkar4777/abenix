"""Run the QuoteIQ example emails through the quoteiq-rfq pipeline and score the runs.

Each email in test-data/emails goes through the pipeline on a running Abenix, the
way the app sends it, and each run is saved. Every saved run is then scored against
test-data/expected-outcomes.json:

  - the RFQ status: Success, Need customer clarification or Escalated
  - the outcome of every RFQ line
  - for a line not in the catalogue, that the nearest products include the expected
    size, for the matcher and in the escalation for staff
  - for a matched line, that its prices are exactly what the ERP code asset
    computes for the same SKU and quantities
  - for a drafted email, the recipient, the greeting, and that no SKU appears
  - that no line answer holds a tool call written as text, which never ran

The report also gives each email's run time and cost, adding up every step,
including each line's search.

    pip install -r quoteiq/api/requirements.txt  # only to run emails, not to score
    export QUOTEIQ_ABENIX_API_KEY=af_...        # the key the app uses
    python3 quoteiq/scripts/evaluate_pipeline.py              # all seven emails
    python3 quoteiq/scripts/evaluate_pipeline.py 02 07        # emails by number
    python3 quoteiq/scripts/evaluate_pipeline.py --score-only # score saved runs again

ABENIX_API_URL defaults to http://localhost:8000. Runs are saved in --runs-dir,
by default quoteiq-eval in the system's temporary folder. Exits non-zero when
any email fails. Running the emails calls the model; scoring saved runs doesn't.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EMAILS = ROOT / "test-data" / "emails"
EXPECTED = ROOT / "test-data" / "expected-outcomes.json"
ASSET = ROOT / "code-assets" / "erp-query" / "main.py"
SDK = ROOT / "api" / "sdk"

PIPELINE = "quoteiq-rfq"
STATUS_FOR_OUTCOME = {
    "quote": "Success",
    "clarification": "Need customer clarification",
    "escalation": "Escalated",
}
SUCCEEDED = {"completed", "succeeded"}
FAILED = {"failed", "error", "cancelled", "canceled", "timeout"}
SKU = re.compile(r"FW-\d{5}")
TEXT_TOOL_CALL = re.compile(r"<(function_calls|invoke|parameter)\b")
RUN_TIMEOUT_SECONDS = 900
POLL_SECONDS = 5


def load_erp():
    spec = importlib.util.spec_from_file_location("erp_query", ASSET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


erp = load_erp()
PRODUCTS = erp.load_products()


# ---------------------------------------------------------------- running


def email_files(numbers: list[str]) -> list[Path]:
    files = sorted(EMAILS.glob("*.txt"))
    if not numbers:
        return files
    chosen = [f for f in files if any(f.name.startswith(n.zfill(2)) for n in numbers)]
    missing = [n for n in numbers if not any(f.name.startswith(n.zfill(2)) for f in files)]
    if missing:
        sys.exit(f"No example email numbered {', '.join(missing)} in {EMAILS}")
    return chosen


def headers_of(text: str) -> tuple[str, str]:
    """The sender's address and the subject, read from the headers as the app does."""
    sender = re.search(r"^From:.*<([^>]+)>", text, re.M)
    subject = re.search(r"^Subject:\s*(.*)$", text, re.M)
    if not sender or not subject:
        raise ValueError("the email has no From address or Subject")
    return sender.group(1).strip(), subject.group(1).strip()


async def run_emails(files: list[Path], runs_dir: Path, staff_name: str) -> None:
    api_key = os.environ.get("QUOTEIQ_ABENIX_API_KEY", "").strip()
    if not api_key:
        sys.exit("Set QUOTEIQ_ABENIX_API_KEY to the Abenix API key the QuoteIQ app uses")
    sys.path.insert(0, str(SDK))
    try:
        from abenix_sdk import Abenix  # the SDK the app vendors
    except ImportError as exc:
        sys.exit(f"Running the emails needs the app's dependencies ({exc.name} is missing): "
                 "pip install -r quoteiq/api/requirements.txt")
    base_url = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    async with Abenix(api_key=api_key, base_url=base_url) as sdk:
        for path in files:
            text = path.read_text(encoding="utf-8")
            sender, subject = headers_of(text)
            started = time.monotonic()
            try:
                run = await sdk.execute(
                    PIPELINE,
                    text,
                    wait="submitted",
                    context={"email_id": path.stem, "staff_name": staff_name,
                             "sender_email": sender, "subject": subject},
                )
            except Exception as exc:  # noqa: BLE001 - any failure to start ends the evaluation
                sys.exit(f"{path.stem}: could not start {PIPELINE} on {base_url}: {describe(exc)}")
            if not run.execution_id:
                sys.exit(f"{path.stem}: Abenix started no run")
            result = await follow(sdk, run.execution_id)
            (runs_dir / f"{path.stem}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
            print(f"ran   {path.stem}: {result.get('status')} in {time.monotonic() - started:.0f}s "
                  f"(execution {run.execution_id})")


def describe(exc: BaseException) -> str:
    """An HTTP error as its status and Abenix's message, anything else as itself."""
    response = getattr(exc, "response", None)
    if response is None:
        return str(exc) or type(exc).__name__
    try:
        body = response.json()
        message = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else body.get("error")
    except ValueError:
        message = None
    return f"HTTP {response.status_code}" + (f": {message}" if message else "")


async def follow(sdk: Any, execution_id: str) -> dict[str, Any]:
    """Poll the run until it ends. A failed check is tried again until the deadline."""
    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
    run: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            run = await sdk.executions.get(execution_id) or {}
        except Exception as exc:  # noqa: BLE001
            print(f"      checking execution {execution_id} failed, trying again: {describe(exc)}")
        if str(run.get("status") or "").lower() in SUCCEEDED | FAILED:
            return run
        await asyncio.sleep(POLL_SECONDS)
    return {**run, "status": "timeout"}


# ---------------------------------------------------------------- reading a run


def parse(value: Any) -> Any:
    """JSON text as an object. When an answer holds text before its JSON, its
    verdict is the last complete top-level object."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        pass
    decoder, i, last = json.JSONDecoder(), 0, None
    while (i := value.find("{", i)) >= 0:
        try:
            obj, length = decoder.raw_decode(value[i:])
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict):
            last = obj
        i += length
    return last if last is not None else value


def run_output(run: dict[str, Any]) -> dict[str, Any] | None:
    """The result node's output, which is what the app reads."""
    node = (run.get("node_results") or {}).get("result")
    if isinstance(node, dict) and isinstance(node.get("output"), dict):
        return node["output"]
    for key in ("output", "output_message"):
        out = parse(run.get(key))
        if isinstance(out, dict):
            return out
    return None


def line_answer(item: Any) -> Any:
    """A line result is the matcher's step result, its answer under "response"."""
    if isinstance(item, dict) and "response" in item:
        return parse(item["response"])
    return parse(item)


def run_cost(run: dict[str, Any]) -> float:
    """Every agent step's cost, each line's search included."""
    total = 0.0

    def add(output: Any) -> None:
        nonlocal total
        output = parse(output)
        if isinstance(output, list):
            for item in output:
                add(item)
        elif isinstance(output, dict) and "response" in output and "cost" in output:
            total += float(output.get("cost") or 0)

    for node in (run.get("node_results") or {}).values():
        if isinstance(node, dict):
            add(node.get("output"))
    return total


# ---------------------------------------------------------------- scoring


def product_awg(sku: str) -> Any:
    answer = erp.run({"operation": "get_product", "sku": sku}, PRODUCTS)
    return (answer.get("product") or {}).get("awg")


def score(email: dict[str, Any], run: dict[str, Any]) -> list[str]:
    status = str(run.get("status") or "").lower()
    if status not in SUCCEEDED:
        return [f"the run {status or 'has no status'}: {run.get('error_message') or run.get('error') or ''}".strip()]
    out = run_output(run)
    if not isinstance(out, dict):
        return ["the run has no result"]
    problems: list[str] = []

    got_status = STATUS_FOR_OUTCOME.get(out.get("outcome"), out.get("outcome"))
    if got_status != email["expected_status"]:
        problems.append(f"status {got_status!r}, expected {email['expected_status']!r}")

    raw_lines = parse(out.get("lines"))
    raw_lines = raw_lines if isinstance(raw_lines, list) else []
    if any(TEXT_TOOL_CALL.search(json.dumps(item, default=str)) for item in raw_lines):
        problems.append("a line answer holds a tool call written as text")
    lines = [a for a in (line_answer(item) for item in raw_lines) if isinstance(a, dict)]

    got = sorted(str(line.get("outcome")) for line in lines)
    want = sorted(line["expected"] for line in email["lines"])
    if got != want:
        problems.append(f"line outcomes {got}, expected {want}")

    escalation = parse(out.get("escalation"))
    items = (escalation or {}).get("items") if isinstance(escalation, dict) else None
    for expected in email["lines"]:
        if "nearest_awg" not in expected:
            continue
        ref = expected["ref"]
        line = next((x for x in lines if ref in str(x.get("customer_reference", ""))), {})
        skus = {n.get("sku") for n in line.get("nearest") or [] if isinstance(n, dict) and n.get("sku")}
        if expected["nearest_awg"] not in {product_awg(s) for s in skus}:
            problems.append(f"{ref}: the nearest products {sorted(skus)} have no {expected['nearest_awg']} AWG size")
        item = next((i for i in items or [] if isinstance(i, dict) and ref in str(i.get("customer_reference", ""))), {})
        if not item.get("nearest_products"):
            problems.append(f"{ref}: the escalation names no nearest products")

    for line in lines:
        if line.get("outcome") != "matched":
            continue
        sku = (line.get("product") or {}).get("sku")
        prices = (line.get("pricing") or {}).get("prices") or []
        if not prices:
            problems.append(f"line {line.get('line_ref')}: matched but not priced")
            continue
        quantities = [p.get("requested_qty") for p in prices if p.get("requested_qty") is not None]
        truth = erp.run({"operation": "get_price", "sku": sku, "quantities": quantities or None}, PRODUCTS)
        fields = ("quoted_qty", "moq_applied", "discount_pct", "net_unit_price", "line_total")
        if [[t.get(f) for f in fields] for t in truth.get("prices") or []] != \
           [[p.get(f) for f in fields] for p in prices]:
            problems.append(f"line {line.get('line_ref')}: prices differ from the ERP's for {sku}")

    if out.get("outcome") in ("quote", "clarification"):
        mail = parse(out.get("email"))
        if not isinstance(mail, dict):
            problems.append("no email was drafted")
        else:
            if SKU.search(json.dumps(mail)):
                problems.append("the drafted email names a SKU")
            if mail.get("to") != out.get("sender_email"):
                problems.append(f"the email goes to {mail.get('to')!r}, not the sender {out.get('sender_email')!r}")
            greeting = str(mail.get("greeting") or "").strip()
            if email.get("expected_greeting") and greeting != email["expected_greeting"]:
                problems.append(f"greeting {greeting!r}, expected {email['expected_greeting']!r}")
    return problems


def score_all(files: list[Path], runs_dir: Path) -> bool:
    expected = {e["file"]: e for e in json.loads(EXPECTED.read_text(encoding="utf-8"))["emails"]}
    passed = scored = 0
    total_cost = 0.0
    print()
    for path in files:
        saved = runs_dir / f"{path.stem}.json"
        if not saved.exists():
            print(f"--    {path.name}: no saved run in {runs_dir}")
            continue
        run = json.loads(saved.read_text(encoding="utf-8"))
        run = run.get("data", run) if isinstance(run.get("data"), dict) else run
        problems = score(expected[path.name], run)
        cost = run_cost(run)
        total_cost += cost
        scored += 1
        passed += not problems
        seconds = (run.get("duration_ms") or 0) / 1000
        print(f"{'PASS' if not problems else 'FAIL'}  {path.name}  ({seconds:.0f}s, ${cost:.3f})")
        for p in problems:
            print(f"      - {p}")
    print(f"\n{passed} of {scored} emails passed, ${total_cost:.2f} in all")
    return scored > 0 and passed == scored


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("emails", nargs="*", help="email numbers, e.g. 02 07 (default: all)")
    parser.add_argument("--score-only", action="store_true", help="score the saved runs without running anything")
    parser.add_argument("--runs-dir", type=Path, default=Path(tempfile.gettempdir()) / "quoteiq-eval")
    parser.add_argument("--staff-name", default="QuoteIQ Sales", help="who signs the drafted emails")
    args = parser.parse_args()

    files = email_files(args.emails)
    args.runs_dir.mkdir(parents=True, exist_ok=True)
    if not args.score_only:
        asyncio.run(run_emails(files, args.runs_dir, args.staff_name))
    return 0 if score_all(files, args.runs_dir) else 1


if __name__ == "__main__":
    sys.exit(main())
