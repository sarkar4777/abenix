"""Tests for the email sender pipeline tool."""

from __future__ import annotations

import json
import os

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from engine.tools.email_sender import EmailSenderTool


@pytest.fixture
def tool() -> EmailSenderTool:
    return EmailSenderTool()


class TestEmailSenderTool:
    @pytest.mark.asyncio
    async def test_dev_mode_logs_to_file(
        self, tool: EmailSenderTool, tmp_path: pytest.TempPathFactory
    ) -> None:
        """In dev mode (no SMTP_HOST), the tool logs the email to a JSON file."""
        with patch.dict(
            os.environ,
            {"SMTP_HOST": "", "EXPORT_DIR": str(tmp_path)},
        ), patch("engine.tools.email_sender.SMTP_HOST", ""), patch(
            "engine.tools.email_sender.EXPORT_DIR", str(tmp_path)
        ):
            result = await tool.execute(
                {
                    "to": "user@example.com",
                    "subject": "Test email",
                    "body": "Hello from the pipeline.",
                }
            )

        assert result.is_error is False
        parsed = json.loads(result.content)
        assert parsed["mode"] == "dev"

        # Verify the file was actually created in the temp directory
        sent_dir = tmp_path / "sent_emails"
        files = list(sent_dir.glob("*.json"))
        assert len(files) == 1

        logged = json.loads(files[0].read_text(encoding="utf-8"))
        assert logged["subject"] == "Test email"
        assert logged["body"] == "Hello from the pipeline."

    @pytest.mark.asyncio
    async def test_missing_to_returns_error(self, tool: EmailSenderTool) -> None:
        """An empty 'to' field returns an error."""
        result = await tool.execute(
            {"to": "", "subject": "Hi", "body": "Test"}
        )

        assert result.is_error is True
        assert "to" in result.content.lower()

    @pytest.mark.asyncio
    async def test_missing_subject_returns_error(
        self, tool: EmailSenderTool
    ) -> None:
        """An empty 'subject' field returns an error."""
        result = await tool.execute(
            {"to": "a@b.com", "subject": "", "body": "Test"}
        )

        assert result.is_error is True
        assert "subject" in result.content.lower()

    @pytest.mark.asyncio
    async def test_html_format_support(
        self, tool: EmailSenderTool, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Sending with format='html' succeeds and records the format."""
        with patch("engine.tools.email_sender.SMTP_HOST", ""), patch(
            "engine.tools.email_sender.EXPORT_DIR", str(tmp_path)
        ):
            result = await tool.execute(
                {
                    "to": "user@example.com",
                    "subject": "HTML email",
                    "body": "<h1>Hello</h1>",
                    "format": "html",
                }
            )

        assert result.is_error is False

        # Read the logged file and verify format
        sent_dir = tmp_path / "sent_emails"
        files = list(sent_dir.glob("*.json"))
        assert len(files) == 1
        logged = json.loads(files[0].read_text(encoding="utf-8"))
        assert logged["format"] == "html"

    @pytest.mark.asyncio
    async def test_multiple_recipients(
        self, tool: EmailSenderTool, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Comma-separated recipients are split into a list."""
        with patch("engine.tools.email_sender.SMTP_HOST", ""), patch(
            "engine.tools.email_sender.EXPORT_DIR", str(tmp_path)
        ):
            result = await tool.execute(
                {
                    "to": "a@b.com,c@d.com",
                    "subject": "Multi",
                    "body": "Test body",
                }
            )

        assert result.is_error is False
        parsed = json.loads(result.content)
        assert len(parsed["recipients"]) == 2
        assert "a@b.com" in parsed["recipients"]
        assert "c@d.com" in parsed["recipients"]

    @pytest.mark.asyncio
    async def test_result_structure(
        self, tool: EmailSenderTool, tmp_path: pytest.TempPathFactory
    ) -> None:
        """The JSON output contains the required keys: status, recipients, subject, mode."""
        with patch("engine.tools.email_sender.SMTP_HOST", ""), patch(
            "engine.tools.email_sender.EXPORT_DIR", str(tmp_path)
        ):
            result = await tool.execute(
                {
                    "to": "user@example.com",
                    "subject": "Structure test",
                    "body": "Checking keys.",
                }
            )

        assert result.is_error is False
        parsed = json.loads(result.content)
        assert "status" in parsed
        assert "recipients" in parsed
        assert "subject" in parsed
        assert "mode" in parsed


class TestEmailSenderSmtp:
    """Tests for SMTP delivery path using mocked aiosmtplib."""

    @pytest.fixture
    def tool(self) -> EmailSenderTool:
        return EmailSenderTool()

    @pytest.mark.asyncio
    async def test_smtp_send_success(self, tool: EmailSenderTool) -> None:
        """SMTP send succeeds with mocked aiosmtplib."""
        with patch.dict(os.environ, {
            "SMTP_HOST": "smtp.test.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "user@test.com",
            "SMTP_PASS": "password123",
            "SMTP_FROM": "noreply@test.com",
        }), patch("engine.tools.email_sender.SMTP_HOST", "smtp.test.com"), \
             patch("engine.tools.email_sender.SMTP_PORT", 587), \
             patch("engine.tools.email_sender.SMTP_USER", "user@test.com"), \
             patch("engine.tools.email_sender.SMTP_PASS", "password123"), \
             patch("engine.tools.email_sender.SMTP_FROM", "noreply@test.com"), \
             patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = ({}, "OK")
            result = await tool.execute({
                "to": "recipient@example.com",
                "subject": "Test",
                "body": "Hello",
            })

        assert not result.is_error
        mock_send.assert_called_once()
        parsed = json.loads(result.content)
        assert parsed["mode"] == "smtp"
        assert parsed["status"] == "sent"
        assert "recipient@example.com" in parsed["recipients"]

    @pytest.mark.asyncio
    async def test_smtp_auth_failure(self, tool: EmailSenderTool) -> None:
        """SMTP authentication failure returns an error."""
        with patch.dict(os.environ, {
            "SMTP_HOST": "smtp.test.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "bad_user",
            "SMTP_PASS": "bad_pass",
            "SMTP_FROM": "noreply@test.com",
        }), patch("engine.tools.email_sender.SMTP_HOST", "smtp.test.com"), \
             patch("engine.tools.email_sender.SMTP_PORT", 587), \
             patch("engine.tools.email_sender.SMTP_USER", "bad_user"), \
             patch("engine.tools.email_sender.SMTP_PASS", "bad_pass"), \
             patch("engine.tools.email_sender.SMTP_FROM", "noreply@test.com"), \
             patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = Exception(
                "SMTP Authentication failed: (535, 'Authentication credentials invalid')"
            )
            result = await tool.execute({
                "to": "user@example.com",
                "subject": "Auth test",
                "body": "This should fail",
            })

        assert result.is_error
        assert "failed" in result.content.lower() or "authentication" in result.content.lower()

    @pytest.mark.asyncio
    async def test_smtp_connection_failure(
        self, tool: EmailSenderTool
    ) -> None:
        """SMTP connection refused returns an error."""
        with patch.dict(os.environ, {
            "SMTP_HOST": "smtp.unreachable.com",
            "SMTP_PORT": "587",
        }), patch("engine.tools.email_sender.SMTP_HOST", "smtp.unreachable.com"), \
             patch("engine.tools.email_sender.SMTP_PORT", 587), \
             patch("engine.tools.email_sender.SMTP_USER", ""), \
             patch("engine.tools.email_sender.SMTP_PASS", ""), \
             patch("engine.tools.email_sender.SMTP_FROM", "noreply@test.com"), \
             patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = ConnectionRefusedError(
                "Connection refused by smtp.unreachable.com:587"
            )
            result = await tool.execute({
                "to": "user@example.com",
                "subject": "Connection test",
                "body": "This should fail too",
            })

        assert result.is_error
        assert "failed" in result.content.lower() or "connection" in result.content.lower()

    @pytest.mark.asyncio
    async def test_smtp_html_email(self, tool: EmailSenderTool) -> None:
        """HTML email is sent with correct content type via SMTP."""
        with patch.dict(os.environ, {
            "SMTP_HOST": "smtp.test.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "user@test.com",
            "SMTP_PASS": "password123",
            "SMTP_FROM": "noreply@test.com",
        }), patch("engine.tools.email_sender.SMTP_HOST", "smtp.test.com"), \
             patch("engine.tools.email_sender.SMTP_PORT", 587), \
             patch("engine.tools.email_sender.SMTP_USER", "user@test.com"), \
             patch("engine.tools.email_sender.SMTP_PASS", "password123"), \
             patch("engine.tools.email_sender.SMTP_FROM", "noreply@test.com"), \
             patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = ({}, "OK")
            result = await tool.execute({
                "to": "recipient@example.com",
                "subject": "HTML Report",
                "body": "<h1>Report</h1><p>Data analysis complete.</p>",
                "format": "html",
            })

        assert not result.is_error
        mock_send.assert_called_once()

        # Inspect the EmailMessage that was passed to aiosmtplib.send
        sent_message = mock_send.call_args.args[0]
        assert sent_message["Subject"] == "HTML Report"
        assert sent_message["To"] == "recipient@example.com"
        assert sent_message["From"] == "noreply@test.com"

        parsed = json.loads(result.content)
        assert parsed["format"] == "html"
        assert parsed["mode"] == "smtp"
