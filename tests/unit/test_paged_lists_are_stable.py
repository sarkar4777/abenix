"""Every offset-paged list orders by a unique column last, so rows sharing a timestamp never repeat across pages.

Rows inserted in one transaction share now(), so ordering by created_at alone let
Postgres return the same agent on two pages and skip another.
"""

from __future__ import annotations

import re
from pathlib import Path

ROUTERS = Path(__file__).resolve().parents[2] / "apps" / "api" / "app" / "routers"


def test_offset_queries_have_a_unique_tie_breaker():
    bad = []
    for f in sorted(ROUTERS.glob("*.py")):
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if ".offset(" not in line:
                continue
            window = "\n".join(lines[max(0, i - 45) : i + 1])
            orders = re.findall(r"order_by\((.*?)\)\s*(?:\n|\.)", window, re.S)
            if not orders:
                continue
            last = window[window.rfind("order_by(") :]
            if not re.search(r"\b\w+\.id\b", last.split(".offset(")[0]):
                bad.append(f"{f.name}:{i + 1}")
    assert not bad, f"paged queries ordered without an id tie-breaker: {bad}"
