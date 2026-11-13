"""A stand-in for the Abenix SDK and synthetic quoteiq-rfq runs, so the app's
rules can be tested without a platform or a model."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

SENDER = {"name": "Daniel Okafor", "title": "", "email": "d.okafor@quillfeather-avionics.example",
          "organisation": "Quillfeather Avionics", "team": "Purchasing Department"}


def matched_line(ref: int, colour: str, sku: str, qty: int = 100) -> dict[str, Any]:
    answer = {
        "line_ref": ref,
        "outcome": "matched",
        "customer_reference": f"600V 7/0.16 OD 1.1, {colour}",
        "understood": {"awg": 26, "stranding": "7/34", "od_mm": 1.1},
        "filters": {"awg": 26, "stranding": "7/34", "od_mm": 1.1},
        "candidates_total": 1,
        "product": {"sku": sku, "name": f"26 AWG (7/34) SPC Conductor, PTFE Insulation, 600 V, Colour {colour}, OD 1.10 mm",
                    "standard_part_number": None},
        "pricing": {"sku": sku, "currency": "USD", "unit_price": 0.41, "moq": 30, "lead_time_days": 21,
                    "prices": [{"requested_qty": qty, "quoted_qty": qty, "moq_applied": False, "discount_pct": 2.0,
                                "net_unit_price": 0.4018, "line_total": round(0.4018 * qty, 2)}]},
    }
    return {"response": json.dumps(answer), "cost": 0.02, "duration_ms": 9000}


def other_line(ref: int, outcome: str, **extra: Any) -> dict[str, Any]:
    answer = {"line_ref": ref, "outcome": outcome, "customer_reference": f"line {ref}", "reason": "because", **extra}
    return {"response": json.dumps(answer), "cost": 0.02, "duration_ms": 9000}


def email(kind: str = "quote") -> dict[str, str]:
    return {
        "to": SENDER["email"],
        "subject": "Re: RFQ: PTFE hook-up wire",
        "greeting": "Dear Daniel Okafor,",
        "body": "Thank you for your enquiry." + (" Please find our quotation below." if kind == "quote"
                                                 else " Which size and colour do you need?"),
        "closing": "Kind regards,\nPriya Shah",
    }


def run_output(outcome: str) -> dict[str, Any]:
    if outcome == "quote":
        lines = [matched_line(1, "Black", "FW-10001"), matched_line(2, "White", "FW-10002")]
    elif outcome == "clarification":
        lines = [other_line(1, "needs_clarification", differs_on={"awg": [20, 22]})]
    else:
        lines = [matched_line(1, "Red", "FW-10003"),
                 other_line(2, "not_in_catalogue", nearest=[{"sku": "FW-10004", "name": "8 AWG"}])]
    return {
        "email_id": "x",
        "outcome": outcome,
        "reason": "[not available]" if outcome != "escalation" else "A size we don't make",
        "sender": SENDER,
        "lines": lines,
        "email_brief": {"mode": outcome, "points": []},
        "email": email(outcome) if outcome != "escalation" else "[not available]",
        "escalation": ({"summary": "One size missing", "items": [{"outcome": "not_in_catalogue"}],
                        "reason": "[not available]"} if outcome == "escalation" else "[not available]"),
    }


def finished_run(execution_id: str, output: dict[str, Any] | None, status: str = "completed") -> dict[str, Any]:
    return {
        "id": execution_id,
        "agent_id": "pipeline-agent-id",
        "status": status,
        "cost": 0.31,
        "duration_ms": 61000,
        "error_message": "model overloaded" if status == "failed" else None,
        "output_message": json.dumps(output) if output else None,
        "node_results": {
            "extract": {"status": "completed"},
            "search": {"status": "completed"},
            "decide": {"status": "completed"},
            "result": {"status": "completed", "output": output} if output else {"status": "failed"},
        },
    }


@dataclass
class Started:
    execution_id: str | None
    status: str = "running"
    output: str = ""


class FakeExecutions:
    def __init__(self, sdk: "FakeSDK") -> None:
        self.sdk = sdk

    async def get(self, execution_id: str) -> dict[str, Any]:
        if self.sdk.check_errors:
            raise self.sdk.check_errors.pop(0)
        return self.sdk.runs[execution_id]


class FakeApprovals:
    def __init__(self, sdk: "FakeSDK") -> None:
        self.sdk = sdk

    async def create(self, title: str, payload: dict[str, Any], **kw: Any) -> dict[str, Any]:
        if self.sdk.fail_approvals:
            raise httpx.ConnectError("approvals down")
        approval_id = str(uuid.uuid4())
        row = {"id": approval_id, "title": title, "payload": payload, "status": "pending", "signoffs": [],
               "expires_at": "2099-01-01T00:00:00+00:00", **kw}
        self.sdk.approvals_by_id[approval_id] = row
        return row

    async def get(self, approval_id: str) -> dict[str, Any]:
        return self.sdk.approvals_by_id[approval_id]

    def _sign(self, approval_id: str, status: str, reason: str) -> dict[str, Any]:
        row = self.sdk.approvals_by_id[approval_id]
        if row["status"] != "pending":
            raise httpx.HTTPStatusError("decided", request=httpx.Request("POST", "http://x"),
                                        response=httpx.Response(409, json={"error": {"message": "already decided"}}))
        row["status"] = status
        row["signoffs"].append({"decision": status, "reason": reason, "user_name": "Admin"})
        self.sdk.signed.append((approval_id, status, reason))
        return row

    async def approve(self, approval_id: str, *, reason: str = "") -> dict[str, Any]:
        if self.sdk.hold_signing is not None:
            self.sdk.signing.set()
            await self.sdk.hold_signing.wait()
        return self._sign(approval_id, "approved", reason)

    async def return_for_changes(self, approval_id: str, reason: str) -> dict[str, Any]:
        return self._sign(approval_id, "returned", reason)

    async def deny(self, approval_id: str, *, reason: str = "") -> dict[str, Any]:
        return self._sign(approval_id, "denied", reason)


class NoStream:
    """The event stream isn't available, so the app polls the run."""

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        raise httpx.ConnectError("no stream in tests")


@dataclass
class FakeSDK:
    """One shared fake behind every new_sdk() call in a test."""

    pipeline_outputs: list[Any] = field(default_factory=list)   # per pipeline run: an output dict, or "failed"
    drafts: list[Any] = field(default_factory=list)              # per drafter run: an email dict, or "failed"
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    approvals_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    signed: list[tuple[str, str, str]] = field(default_factory=list)
    executed: list[dict[str, Any]] = field(default_factory=list)
    fail_approvals: bool = False
    check_errors: list[Exception] = field(default_factory=list)  # raised by the next run checks
    hold_signing: asyncio.Event | None = None  # approve waits on it, after setting signing
    signing: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self.executions = FakeExecutions(self)
        self.approvals = FakeApprovals(self)
        self.http = NoStream()

    async def execute(self, slug: str, message: str, act_as: Any = None, **kw: Any) -> Started:
        self.executed.append({"slug": slug, "message": message, "act_as": act_as, **kw})
        execution_id = str(uuid.uuid4())
        if slug == "quoteiq-rfq":
            out = self.pipeline_outputs.pop(0)
            self.runs[execution_id] = (finished_run(execution_id, None, "failed") if out == "failed"
                                       else finished_run(execution_id, out))
            return Started(execution_id)
        drafted = self.drafts.pop(0)
        if drafted == "failed":
            return Started(execution_id, status="failed")
        return Started(execution_id, status="completed", output=json.dumps(drafted))

    async def close(self) -> None:
        return None

    def approvals_for(self, status: str = "pending") -> list[dict[str, Any]]:
        return [a for a in self.approvals_by_id.values() if a["status"] == status]


def status_error(code: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(str(code), request=httpx.Request("GET", "http://x"),
                                 response=httpx.Response(code, json={"detail": "status " + str(code)}))
