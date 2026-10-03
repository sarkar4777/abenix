"""Every request header the web app sends must survive the browser's CORS preflight."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _allowed() -> set[str]:
    src = (ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")
    block = re.search(r"allow_headers=\[(.*?)\]", src, re.S).group(1)
    return {h.lower() for h in re.findall(r'"([^"]+)"', block)}


def test_web_request_headers_are_allowed() -> None:
    sent: set[str] = set()
    for f in (ROOT / "apps/web/src").rglob("*.ts*"):
        for m in re.finditer(
            r"['\"]((?:If|X)-[A-Za-z-]+)['\"]\s*:",
            f.read_text(encoding="utf-8", errors="ignore"),
        ):
            sent.add(m.group(1).lower())
    missing = sent - _allowed()
    assert not missing, f"add to allow_headers in main.py: {sorted(missing)}"
