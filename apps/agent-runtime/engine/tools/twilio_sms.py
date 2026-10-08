"""Send SMS / WhatsApp messages via Twilio."""

from __future__ import annotations

from typing import Any

import httpx

from engine.tools.base import BaseTool, ConfigField, Effect, ToolResult

_BASE = "https://api.twilio.com/2010-04-01"


class TwilioSmsTool(BaseTool):
    name = "twilio_sms"
    risk_tier = "high"
    effect = Effect(
        kind="send", label="Send an SMS or WhatsApp message", target_param="to"
    )
    config_fields = (
        ConfigField(
            "TWILIO_ACCOUNT_SID",
            label="Account SID",
            kind="string",
            required=True,
            group="Twilio",
            signup_url="https://console.twilio.com",
        ),
        ConfigField(
            "TWILIO_AUTH_TOKEN",
            label="Auth token",
            kind="secret",
            required=True,
            group="Twilio",
            signup_url="https://console.twilio.com",
        ),
        ConfigField(
            "TWILIO_FROM_NUMBER",
            label="From number",
            kind="string",
            required=True,
            group="Twilio",
        ),
        ConfigField(
            "TWILIO_WHATSAPP_FROM",
            label="WhatsApp from",
            kind="string",
            required=False,
            group="Twilio",
        ),
    )
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

        sid = self.cfg("TWILIO_ACCOUNT_SID", required=True).strip()
        token = self.cfg("TWILIO_AUTH_TOKEN", required=True).strip()
        if channel == "whatsapp":
            from_ = self.cfg("TWILIO_WHATSAPP_FROM", required=True).strip()
            if to and not to.startswith("whatsapp:"):
                to = f"whatsapp:{to}"
        else:
            from_ = self.cfg("TWILIO_FROM_NUMBER", required=True).strip()

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
