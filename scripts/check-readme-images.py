#!/usr/bin/env python3
"""Every local image the README embeds must exist and be tracked by git.

A `**/screenshots/` line in .gitignore quietly swallowed docs/screenshots/, so
three PharmaVigil captures were written, never committed, and the public repo
rendered a broken image under a caption describing it. The file was on disk the
whole time, which is why nothing local ever complained.

Existence alone is not enough — the file has to be tracked, because the public
repo is built by rsync and commit, and an ignored file reaches neither.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ["README.md"]

# <img src="..."> and ![alt](...) — skip anything remote or a data URI.
SRC = re.compile(r'<img[^>]+src="([^"]+)"', re.I)
MD = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")


def tracked() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return {line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()}


def main() -> int:
    known = tracked()
    problems: list[str] = []
    checked = 0

    for doc in DOCS:
        p = ROOT / doc
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        refs = SRC.findall(text) + MD.findall(text)
        for ref in refs:
            if ref.startswith(("http://", "https://", "data:", "#", "mailto:")):
                continue
            rel = ref.lstrip("./").replace("\\", "/")
            checked += 1
            target = ROOT / rel
            if not target.exists():
                problems.append(f"{doc}: missing file -> {rel}")
            elif rel not in known:
                problems.append(
                    f"{doc}: {rel} exists but git does not track it "
                    "(it will render broken once published)"
                )

    if problems:
        print(f"[check-readme-images] FAIL: {len(problems)} of {checked} refs broken")
        for line in problems:
            print(f"  - {line}")
        return 1

    print(f"[check-readme-images] OK: {checked} local image refs exist and are tracked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
