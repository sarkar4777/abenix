"""Email sender tool for delivering messages via async SMTP or dev-mode file logging."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from engine.tools.base import BaseTool, ToolResult

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "agent@abenix.dev")

EXPORT_DIR = os.environ.get("EXPORT_DIR", "/tmp/abenix_exports")


class EmailSenderTool(BaseTool):
    name = "email_sender"
    description = (
        "Send emails to one or more recipients with plain text or HTML content. "
        "Supports SMTP delivery in production and falls back to local file logging "
        "in development mode when SMTP is not configured. Useful for sending reports, "
        "notifications, alerts, and agent-generated content to users."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Comma-separated list of recipient email addresses",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line",
            },
            "body": {
                "type": "string",
                "description": "Email body content (plain text or HTML)",
            },
            "format": {
                "type": "string",
                "enum": ["text", "html"],
                "description": "Email body format",
                "default": "text",
            },
        },
        "required": ["to", "subject", "body"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        to = arguments.get("to", "")
        subject = arguments.get("subject", "")
        body = arguments.get("body", "")
        fmt = arguments.get("format", "text")

        if not to.strip():
            return ToolResult(content="Error: to is required", is_error=True)
        if not subject.strip():
            return ToolResult(content="Error: subject is required", is_error=True)
        if not body.strip():
            return ToolResult(content="Error: body is required", is_error=True)

        recipients = [addr.strip() for addr in to.split(",") if addr.strip()]

        try:
            if SMTP_HOST:
                return await self._send_smtp(recipients, subject, body, fmt)
            else:
                return await self._log_to_file(recipients, subject, body, fmt)
        except Exception as e:
            return ToolResult(content=f"Email failed: {e}", is_error=True)

    async def _send_smtp(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        fmt: str,
    ) -> ToolResult:
        """Send email via async SMTP with STARTTLS."""
        import aiosmtplib

        message = EmailMessage()
        message["From"] = SMTP_FROM
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject

        if fmt == "html":
            message.set_content(body, subtype="html")
        else:
            message.set_content(body)

        send_kwargs: dict[str, Any] = {
            "hostname": SMTP_HOST,
            "port": SMTP_PORT,
            "start_tls": True,
        }
        if SMTP_USER and SMTP_PASS:
            send_kwargs["username"] = SMTP_USER
            send_kwargs["password"] = SMTP_PASS

        await aiosmtplib.send(message, **send_kwargs)

        result = {
            "status": "sent",
            "recipients": recipients,
            "subject": subject,
            "format": fmt,
            "mode": "smtp",
        }
        return ToolResult(
            content=json.dumps(result, indent=2),
            metadata={"mode": "smtp", "recipient_count": len(recipients)},
        )

    async def _log_to_file(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        fmt: str,
    ) -> ToolResult:
        """Log email to file in dev mode when SMTP is not configured."""
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        subject_slug = re.sub(r"[^a-zA-Z0-9]+", "_", subject).strip("_").lower()[:50]

        log_dir = Path(EXPORT_DIR) / "sent_emails"
        log_dir.mkdir(parents=True, exist_ok=True)

        email_record = {
            "to": ", ".join(recipients),
            "subject": subject,
            "body": body,
            "format": fmt,
            "timestamp": now.isoformat(),
        }

        filepath = log_dir / f"{timestamp}_{subject_slug}.json"
        filepath.write_text(json.dumps(email_record, indent=2), encoding="utf-8")

        result = {
            "status": "logged",
            "recipients": recipients,
            "subject": subject,
            "format": fmt,
            "mode": "dev",
            "file": str(filepath),
        }
        return ToolResult(
            content=json.dumps(result, indent=2),
            metadata={"mode": "dev", "file": str(filepath)},
        )
