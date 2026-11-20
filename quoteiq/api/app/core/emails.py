"""The example inbox: RFQ emails shipped as text files.

There is no mailbox. Each file in test-data/emails is one email, its name
(without .txt) is the email's id, and the files' order is the queue order.

The sender's address and the subject are read from the headers here, by the
app, and passed to the pipeline in its context. Text in angle brackets does
not survive a run's input, so an address like <name@company> would never
reach the extractor otherwise.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_FROM = re.compile(r"^From:\s*(?P<name>[^<\n]*?)\s*<(?P<email>[^>\s]+)>\s*$", re.M)
_SUBJECT = re.compile(r"^Subject:\s*(?P<subject>.*?)\s*$", re.M)


def emails_dir() -> Path:
    """Where the example emails live.

    QQ_EMAILS_DIR wins. In the image they sit at /app/test-data/emails; run
    from a clone they are in quoteiq/test-data/emails.
    """
    configured = os.environ.get("QQ_EMAILS_DIR")
    if configured:
        return Path(configured)
    here = Path(__file__).resolve()
    for base in (here.parents[2], here.parents[3]):
        candidate = base / "test-data" / "emails"
        if candidate.is_dir():
            return candidate
    return here.parents[3] / "test-data" / "emails"


def parse_email(email_id: str, text: str) -> dict[str, Any]:
    """The fields the app needs from one email file.

    from_name is the display part of the From header, which for these emails
    is "<person or company>, <company or team>".
    """
    sender = _FROM.search(text)
    subject = _SUBJECT.search(text)
    if sender is None or subject is None:
        raise ValueError(f"{email_id}: needs a 'From: Name <address>' and a 'Subject:' header")
    return {
        "id": email_id,
        "from_name": sender.group("name").strip().rstrip(","),
        "from_email": sender.group("email").strip(),
        "subject": subject.group("subject"),
        "received_text": text,
    }


def load_emails(directory: Path | None = None) -> list[dict[str, Any]]:
    """Every example email, in queue order."""
    directory = directory or emails_dir()
    if not directory.is_dir():
        raise FileNotFoundError(f"no example emails at {directory}")
    return [
        parse_email(path.stem, path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.txt"))
    ]
