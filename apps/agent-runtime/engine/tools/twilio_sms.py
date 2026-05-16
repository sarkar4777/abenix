"""Send SMS / WhatsApp messages via Twilio."""

from __future__ import annotations

import os
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_BASE = "https://api.twilio.com/2010-04-01"


class TwilioSmsTool(BaseTool):
    name = "twilio_sms"
    description = (
        "Send SMS or WhatsApp messages via Twilio. Requires "
        "TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN; sender controlled by "
        "TWILIO_FROM_NUMBER (SMS) or TWILIO_WHATSAPP_FROM (WhatsApp). "
        "Without credentials it returns a 'not configured — would have sent' "
        "structured response so dev pipelines still progress."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "E.164 phone number ('+447700900123') or 'whatsapp:+447700900123'.",
            },
            "body": {
                "type": "string",
                "description": "Message text. Max 1600 chars for SMS, longer for WhatsApp.",
            },
            "channel": {
                "type": "string",
                "enum": ["sms", "whatsapp"],
                "default": "sms",
            },
            "media_url": {
                "type": "string",
                "description": "Optional MMS/WhatsApp media URL (publicly reachable).",
            },
        },
        "required": ["to", "body"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        to = (arguments.get("to") or "").strip()
        body = (arguments.get("body") or "").strip()
        channel = arguments.get("channel", "sms")
        media_url = arguments.get("media_url")
        if not to or not body:
            return ToolResult(content="to and body are required", is_error=True)

        sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
        token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
        if channel == "whatsapp":
            from_ = os.environ.get("TWILIO_WHATSAPP_FROM", "").strip()
            if to and not to.startswith("whatsapp:"):
                to = f"whatsapp:{to}"
        else:
            from_ = os.environ.get("TWILIO_FROM_NUMBER", "").strip()

        if not (sid and token and from_):
            # Graceful no-op so dev pipelines don't break.
            return ToolResult(
                content=(
                    f"[twilio_sms not configured] Would have sent {channel.upper()} to {to}:\n"
                    f"  {body[:240]}{'…' if len(body) > 240 else ''}"
                ),
                metadata={
                    "skipped": True,
                    "reason": "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / "
                    "TWILIO_FROM_NUMBER (or TWILIO_WHATSAPP_FROM) not set",
                    "queued": {
                        "to": to,
                        "from": from_,
                        "body": body,
                        "channel": channel,
                    },
                },
            )

        payload = {"From": from_, "To": to, "Body": body}
        if media_url:
            payload["MediaUrl"] = media_url

        try:
            async with httpx.AsyncClient(timeout=20, auth=(sid, token)) as c:
                r = await c.post(
                    f"{_BASE}/Accounts/{sid}/Messages.json",
                    data=payload,
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            return ToolResult(
                content=f"Twilio HTTP {e.response.status_code}: {e.response.text[:200]}",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(content=f"Twilio error: {e}", is_error=True)

        return ToolResult(
            content=(
                f"Twilio {channel.upper()} sent.\n"
                f"  SID: {data.get('sid')}\n"
                f"  Status: {data.get('status')}\n"
                f"  To: {data.get('to')}  From: {data.get('from')}\n"
                f"  Price: {data.get('price', '?')} {data.get('price_unit', '')}"
            ),
            metadata={
                "sid": data.get("sid"),
                "status": data.get("status"),
                "channel": channel,
                "to": data.get("to"),
                "from": data.get("from"),
            },
        )
