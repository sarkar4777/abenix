"""Reading a quoteiq-rfq run: its live progress and its final result.

Pure functions with no I/O, so the rules that decide an email's status can be
tested without Abenix.

The pipeline decides the RFQ outcome. The app only reads it, and calls a run
a System error when it can't be read: a run that crashes can't report its own
failure, and a half-read run must not reach a reviewer as if it were whole.
"""

from __future__ import annotations

import json
import re
from typing import Any

# "[not available]" is the engine's text for a template that never resolved,
# for example the branch the switch skipped.
NOT_AVAILABLE = "[not available]"

STATUS_FOR_OUTCOME = {
    "quote": "success",
    "clarification": "clarification",
    "escalation": "escalated",
}
LINE_OUTCOMES = {"matched", "needs_clarification", "not_in_catalogue", "erp_record_inconsistent"}
FAILED_RUN = {"failed", "error", "cancelled", "canceled", "timeout"}
SUCCEEDED_RUN = {"completed", "succeeded"}
TERMINAL_RUN = FAILED_RUN | SUCCEEDED_RUN

STEPS = ("extract", "search", "decide", "draft_email", "escalation")
_ITEM = re.compile(r"^search\[(\d+)\]$")
# A step's status in Abenix, as the step tracker shows it. Others pass through.
_STEP_STATE = {"completed": "done", "partial": "failed"}

# The parts of a drafted email the model writes. The recipient is never one.
DRAFT_FIELDS = ("subject", "greeting", "body", "closing")

# A catalogue SKU. SKUs are for staff and must never reach a customer.
SKU = re.compile(r"\bFW-\d{5}\b")


class RunUnreadable(Exception):
    """The run failed, or its output isn't what the pipeline promises."""


def unavailable(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() in {"", NOT_AVAILABLE})


def _json(value: Any) -> Any:
    """A JSON value from text, tolerating a code fence or text around one object."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start : end + 1])
        except ValueError:
            pass
    return None


# ── live progress ────────────────────────────────────────────────────────


def step_state(status: Any) -> str:
    status = str(status or "completed").lower()
    return _STEP_STATE.get(status, status)


def new_progress() -> dict[str, Any]:
    return {"steps": {step: "pending" for step in STEPS}, "searched": [], "lines_done": 0}


def apply_event(progress: dict[str, Any], event: dict[str, Any]) -> bool:
    """Fold one run event into the progress. True when something changed.

    Each line's search reports as search[0], search[1]… Only how many have
    finished is known while the run goes; the number of lines and their
    outcomes come with the run's result.
    """
    kind = event.get("event")
    node = str(event.get("node_id") or "")
    if kind not in {"node_start", "node_complete"} or not node:
        return False
    item = _ITEM.match(node)
    if item:
        # The for_each step publishes no start of its own, only its items'.
        changed = progress["steps"]["search"] == "pending"
        if changed:
            progress["steps"]["search"] = "running"
        index = int(item.group(1))
        if kind == "node_complete" and index not in progress["searched"]:
            progress["searched"].append(index)
            progress["lines_done"] = len(progress["searched"])
            changed = True
        return changed
    if node not in progress["steps"]:
        return False
    new = "running" if kind == "node_start" else step_state(event.get("status"))
    if progress["steps"].get(node) == new:
        return False
    progress["steps"][node] = new
    return True


# ── the finished run ─────────────────────────────────────────────────────


def run_output(run: dict[str, Any]) -> Any:
    """The result node's output: from node_results, else the run's output text."""
    result_node = (run.get("node_results") or {}).get("result")
    if isinstance(result_node, dict) and isinstance(result_node.get("output"), dict):
        return result_node["output"]
    for key in ("output", "output_message"):
        parsed = _json(run.get(key))
        if isinstance(parsed, dict):
            return parsed
    return None


def as_text(value: Any) -> str | None:
    """A free-text field as text. The model sometimes answers one with an object,
    for example a problem as {"fields_disagree": [...]}."""
    if unavailable(value):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "; ".join(t for t in (as_text(v) for v in value) if t)
    if isinstance(value, dict):
        parts = []
        for key, v in value.items():
            text = as_text(v)
            if text:
                parts.append(f"{str(key).replace('_', ' ')}: {text}")
        return "; ".join(parts) or None
    return str(value)


TEXT_FIELDS = ("customer_reference", "reason", "problem")


def differs_on(value: Any) -> dict[str, list[Any]] | None:
    """What the candidates differ on, as {attribute: [values]}.

    The matcher answers either that, or a list of {"attribute", "values"}.
    """
    out: dict[str, list[Any]] = {}
    if isinstance(value, dict):
        for key, values in value.items():
            out[str(key)] = values if isinstance(values, list) else [values]
    elif isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict) and entry.get("attribute"):
                values = entry.get("values")
                out[str(entry["attribute"])] = values if isinstance(values, list) else [values]
    return out or None


def read_line(item: Any, index: int) -> dict[str, Any]:
    """One matcher answer, parsed. The matcher answers with one line of JSON."""
    if not isinstance(item, dict):
        raise RunUnreadable(f"line {index + 1} has no result")
    answer = _json(item.get("response")) if "response" in item else item
    if not isinstance(answer, dict):
        raise RunUnreadable(f"line {index + 1}'s result isn't JSON")
    outcome = answer.get("outcome")
    if outcome not in LINE_OUTCOMES:
        raise RunUnreadable(f"line {index + 1} has no known outcome ({outcome!r})")
    line = dict(answer)
    line["line_ref"] = answer.get("line_ref") or index + 1
    line["differs_on"] = differs_on(answer.get("differs_on"))
    for key in TEXT_FIELDS:
        if key in line:
            line[key] = as_text(line[key])
    line["cost"] = item.get("cost")
    line["duration_ms"] = item.get("duration_ms")
    return line


def skus_in(text: dict[str, str]) -> list[str]:
    """Every SKU in an email's text, in order, once each."""
    found = [m.group(0) for f in DRAFT_FIELDS for m in SKU.finditer(text.get(f) or "")]
    return list(dict.fromkeys(found))


def read_email(value: Any, to: str) -> dict[str, str]:
    """The drafted email. The recipient is always the address in the headers.

    An email that names a SKU is unreadable: it must not reach a reviewer who
    might send it as it stands.
    """
    email = _json(value)
    if not isinstance(email, dict):
        raise RunUnreadable("no email was drafted")
    missing = [f for f in DRAFT_FIELDS if unavailable(email.get(f))]
    if missing:
        raise RunUnreadable(f"the drafted email has no {', '.join(missing)}")
    out = {"to": to, **{f: str(email[f]) for f in DRAFT_FIELDS}}
    skus = skus_in(out)
    if skus:
        raise RunUnreadable(
            f"the drafted email names the catalogue SKU {', '.join(skus)}, and SKUs must not reach the customer"
        )
    return out


def _escalation_item(item: dict[str, Any]) -> dict[str, Any]:
    """One item for staff. The decider names the nearest products either
    nearest_products or, as the matcher does, nearest."""
    out = {k: v for k, v in item.items() if k != "nearest"}
    out.update({k: as_text(item[k]) for k in TEXT_FIELDS if k in item})
    nearest = item.get("nearest_products") or item.get("nearest")
    out["nearest_products"] = [p for p in nearest if isinstance(p, dict)] if isinstance(nearest, list) else []
    return out


def read_run(run: dict[str, Any], *, to: str) -> dict[str, Any]:
    """Everything the app keeps from a finished pipeline run.

    Raises RunUnreadable when the run failed or its output can't be read.
    """
    status = str(run.get("status") or "").lower()
    if status in FAILED_RUN:
        detail = run.get("error_message") or run.get("failure_code") or ""
        raise RunUnreadable(f"the run {status}" + (f": {detail}" if detail else ""))
    out = run_output(run)
    if not isinstance(out, dict):
        raise RunUnreadable("the run returned no result")
    outcome = out.get("outcome")
    if outcome not in STATUS_FOR_OUTCOME:
        raise RunUnreadable(f"the run's outcome isn't quote, clarification or escalation ({outcome!r})")
    raw_lines = _json(out.get("lines"))
    if not isinstance(raw_lines, list) or not raw_lines:
        raise RunUnreadable("the run found no RFQ lines")
    lines = [read_line(item, i) for i, item in enumerate(raw_lines)]

    email = read_email(out.get("email"), to) if outcome != "escalation" else None
    escalation = None
    if outcome == "escalation":
        escalation = _json(out.get("escalation"))
        if not isinstance(escalation, dict):
            raise RunUnreadable("the escalation is missing")
        escalation = {k: (None if unavailable(v) else v) for k, v in escalation.items()}
        for key in ("summary", "reason"):
            escalation[key] = as_text(escalation.get(key))
        items = escalation.get("items")
        escalation["items"] = [_escalation_item(item) for item in (items if isinstance(items, list) else [])
                               if isinstance(item, dict)]

    sender = _json(out.get("sender"))
    brief = _json(out.get("email_brief"))
    return {
        "status": STATUS_FOR_OUTCOME[outcome],
        "outcome": outcome,
        "reason": None if unavailable(out.get("reason")) else out.get("reason"),
        "sender": sender if isinstance(sender, dict) else None,
        "email_brief": brief if isinstance(brief, dict) else None,
        "lines": lines,
        "email": email,
        "escalation": escalation,
    }


def read_redraft(output: Any, to: str) -> dict[str, str]:
    """The drafter's answer when the app runs it on a reviewer's note."""
    return read_email(output, to)


def without_skus(value: Any) -> Any:
    """A copy with every SKU gone: sku and skus keys dropped, SKUs in text
    replaced. For what the email drafter is given."""
    if isinstance(value, dict):
        return {k: without_skus(v) for k, v in value.items() if k not in {"sku", "skus"}}
    if isinstance(value, list):
        return [without_skus(v) for v in value]
    if isinstance(value, str):
        return SKU.sub("the catalogue item", value)
    return value


# What the drafter needs of each line: what was asked, what fits, the price.
_DRAFTER_LINE_FIELDS = (
    "line_ref", "outcome", "customer_reference", "understood", "reason", "product", "pricing",
    "candidates_total", "differs_on", "nearest", "problem",
)


def lines_for_drafter(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The line results as context for a redraft, without SKUs."""
    return [without_skus({k: line[k] for k in _DRAFTER_LINE_FIELDS if line.get(k) is not None}) for line in lines]
