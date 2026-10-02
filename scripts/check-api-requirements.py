"""Fail when apps/api/requirements.txt lacks a dependency pyproject.toml declares.

The image installs from pyproject.toml and CI installs from requirements.txt,
so a package missing from the second passes locally and breaks CI.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def name(spec: str) -> str:
    return re.split(r"[<>=!~\[; ]", spec.strip(), maxsplit=1)[0].lower().replace("_", "-")


def main() -> int:
    deps = tomllib.loads((ROOT / "apps/api/pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    lines = (ROOT / "apps/api/requirements.txt").read_text(encoding="utf-8").splitlines()
    have = {name(line) for line in lines if line.strip() and not line.lstrip().startswith("#")}
    missing = [d for d in deps if name(d) not in have]
    if missing:
        print("apps/api/requirements.txt is missing: " + ", ".join(missing))
        return 1
    print("api requirements match pyproject")
    return 0


if __name__ == "__main__":
    sys.exit(main())
