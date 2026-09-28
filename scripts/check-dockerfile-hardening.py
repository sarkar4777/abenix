#!/usr/bin/env python3
"""Assert every Dockerfile we ship patches its base image.

There are two sets of Dockerfiles and they are built by different things:

  apps/*/Dockerfile     built by CI, which is what Trivy and the code-scanning
                        alerts look at
  docker/Dockerfile.*   built by scripts/deploy.sh and scripts/deploy-azure.sh,
                        which is what actually serves traffic

Both sets were patched for the same CVE wave, but only after the second set was
noticed. CI had gone green on images nobody runs while the running images still
carried every finding. Nothing compared them, so nothing said so.

Three rules, each one a bug that happened:

  1. Base tags stay unpinned to a patch level. A pinned `python:3.12.8-slim`
     stops receiving Debian security updates the day it is cut.
  2. A stage that ships to production upgrades its OS packages. The base tags
     trail the patched builds by weeks.
  3. pip is upgraded in the stage whose site-packages survives. Upgrading it in
     a runtime stage that later does `COPY --from=deps site-packages` puts the
     old pip straight back, and the build still goes green.

Run:  python scripts/check-dockerfile-hardening.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Fixture and sample images are not part of the product and are not served.
SKIP = {"e2e", "node_modules", ".git", "test-results", "playwright-report"}

PINNED_BASE = re.compile(r"^FROM\s+(python:3\.\d+\.\d+|node:\d+\.\d+)[-\w.]*", re.M)
OS_UPGRADE = re.compile(r"apt-get\s+upgrade|apk\s+upgrade", re.M)
PIP_UPGRADE = re.compile(r"pip\s+install[^\n]*--upgrade\s+pip", re.M)
SITE_PACKAGES_COPY = re.compile(r"^COPY\s+--from=\S+\s+\S*site-packages", re.M)
PYTHON_BASE = re.compile(r"^FROM\s+python:", re.M)


def dockerfiles() -> list[Path]:
    found = []
    for p in ROOT.rglob("Dockerfile*"):
        if any(part in SKIP for part in p.relative_to(ROOT).parts):
            continue
        if p.is_file():
            found.append(p)
    return sorted(found)


def stages(text: str) -> list[str]:
    """Split a Dockerfile into its stages, each starting at its FROM."""
    parts = re.split(r"^(FROM\s+.*)$", text, flags=re.M)
    out, i = [], 1
    while i < len(parts):
        out.append(parts[i] + parts[i + 1] if i + 1 < len(parts) else parts[i])
        i += 2
    return out


def check(path: Path) -> list[str]:
    rel = path.relative_to(ROOT).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    problems = []

    for m in PINNED_BASE.finditer(text):
        problems.append(
            f"{rel}: base pinned to a patch level ({m.group(1)}). "
            f"Drop the patch component so security updates land."
        )

    # The last stage is what ships. Anything earlier is a build stage.
    all_stages = stages(text)
    if not all_stages:
        return problems
    final = all_stages[-1]

    # `FROM base AS runtime` inherits its base from an earlier stage, so look
    # at the whole file to decide whether this is a python or node image.
    if not (PYTHON_BASE.search(text) or "node:" in text):
        return problems

    if not OS_UPGRADE.search(final):
        problems.append(
            f"{rel}: the final stage never upgrades OS packages. "
            f"Add `apt-get update && apt-get upgrade -y` (or `apk upgrade`)."
        )

    if PYTHON_BASE.search(text):
        if not PIP_UPGRADE.search(text):
            problems.append(f"{rel}: pip is never upgraded.")
        elif SITE_PACKAGES_COPY.search(final) and PIP_UPGRADE.search(final):
            problems.append(
                f"{rel}: pip is upgraded in the same stage that copies "
                f"site-packages from another stage. The COPY undoes it."
            )

    return problems


def main() -> int:
    files = dockerfiles()
    if not files:
        print("no Dockerfiles found — check the paths")
        return 1

    problems = [p for f in files for p in check(f)]

    for p in problems:
        print(f"  {p}")

    print(f"\n{len(files)} Dockerfiles checked, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
