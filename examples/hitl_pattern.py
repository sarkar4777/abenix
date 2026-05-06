"""End-to-end HITL example.

Demonstrates the v1.1.5 SDK pattern: execute(wait="until_gate") returns
early on an approval gate, the caller decides, then resumes via
forge.approvals.wait_for().

Run:
    export ABENIX_API_KEY=af_...
    export ABENIX_BASE_URL=https://api.your-cluster.dev
    python examples/hitl_pattern.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "packages" / "sdk" / "python")
)

from abenix_sdk import Abenix

AGENT_SLUG = os.environ.get("ABENIX_HITL_AGENT", "alarm-triage")
DEMO_PAYLOAD = {
    "device_id": "pump-7",
    "alarm_code": "VIB-HIGH-CRIT",
    "proposed_action": "remote_reset",
}


async def auto_approver(forge: Abenix, approval_id: str) -> None:
    """Stand-in for a human reviewer.

    A real app routes this to a UI (operator clicks the bell, opens
    /approvals, hits Approve), or to a policy engine, or to chatops.
    """
    await asyncio.sleep(0.2)
    await forge.approvals.approve(
        approval_id,
        reason="auto-approved for demo run",
        client_token=f"demo-{approval_id}",
    )


async def main() -> None:
    api_key = os.environ.get("ABENIX_API_KEY")
    if not api_key:
        raise SystemExit("Set ABENIX_API_KEY first.")

    async with Abenix(
        api_key=api_key,
        base_url=os.environ.get("ABENIX_BASE_URL", "http://localhost:8000"),
    ) as forge:
        result = await forge.execute(
            AGENT_SLUG,
            f"Triage and act on alarm: {DEMO_PAYLOAD}",
            wait="until_gate",
        )

        if result.status != "paused" or result.paused_at is None:
            print("Agent finished without hitting a gate.")
            print("Output:", result.output[:400])
            return

        ref = result.paused_at
        print(f"Paused on gate '{ref.gate_kind or 'untyped'}': {ref.title}")
        print(f"  payload: {ref.payload}")
        print(f"  approval_id: {ref.approval_id}")

        approver = asyncio.create_task(auto_approver(forge, ref.approval_id))
        approval = await forge.approvals.wait_for(ref.approval_id, timeout_seconds=120)
        await approver

        print(f"Approval resolved: {approval.get('status')}")
        signoffs = approval.get("signoffs") or []
        for s in signoffs:
            print(
                f"  signoff by {s.get('user_email')}: {s.get('decision')} ({s.get('reason')})"
            )


if __name__ == "__main__":
    asyncio.run(main())
