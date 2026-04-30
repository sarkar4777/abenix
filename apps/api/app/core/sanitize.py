from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_EVENT_RE = re.compile(r"\bon\w+\s*=", re.IGNORECASE)


def strip_html(text: str) -> str:
    """Remove HTML tags and script blocks from input text."""
    text = _SCRIPT_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    return text.strip()


def sanitize_input(text: str | None) -> str:
    """Sanitize user input by stripping HTML and dangerous patterns."""
    if not text:
        return ""
    text = _SCRIPT_RE.sub("", text)
    text = _EVENT_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    return text.strip()


def is_safe_url(url: str) -> bool:
    """Check that a URL doesn't contain javascript: or data: schemes."""
    lower = url.lower().strip()
    if lower.startswith(("javascript:", "data:", "vbscript:")):
        return False
    return True
