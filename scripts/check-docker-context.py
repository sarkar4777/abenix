"""Every COPY in every Dockerfile names a file git tracks, so a fresh clone builds.

A path that exists only on the author's disk, for example under a gitignored
data/ folder, builds fine for them and fails for everyone who clones the repo.
The build contexts mirror the ones scripts/deploy.sh passes to docker build.
"""

from __future__ import annotations

import posixpath
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def tracked() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def context_for(df: str) -> str:
    if re.fullmatch(
        r"apps/(api|web|worker|agent-runtime)/Dockerfile", df
    ) or df.startswith("docker/"):
        return ""
    if df.startswith("apps/code-runner/"):
        return "apps/code-runner"
    if df.startswith("claimsiq/"):
        return "claimsiq"
    if df == "mideasttourism/api/Dockerfile":
        return "mideasttourism"
    return str(Path(df).parent).replace("\\", "/")


def exists(files: set[str], path: str) -> bool:
    path = path.strip("/")
    if path in ("", "."):
        return True
    return path in files or any(f.startswith(path + "/") for f in files)


def main() -> int:
    files = tracked()
    problems = []
    for df in sorted(f for f in files if re.search(r"(^|/)Dockerfile[^/]*$", f)):
        if "node_modules" in df:
            continue
        ctx = context_for(df)
        lines = (ROOT / df).read_text(encoding="utf-8", errors="ignore").splitlines()
        for n, line in enumerate(lines, 1):
            m = re.match(r"\s*(COPY|ADD)\s+(.*)", line)
            if not m or "--from" in line:
                continue
            parts = [p for p in m.group(2).split() if not p.startswith("--")]
            for src in parts[:-1]:
                if any(c in src for c in "*$?[") or src.startswith(
                    ("http://", "https://")
                ):
                    continue
                full = posixpath.normpath(f"{ctx}/{src}" if ctx else src)
                if not exists(files, full):
                    problems.append(
                        f"{df}:{n} copies {src}, which git does not track ({full})"
                    )
    if problems:
        print("A fresh clone cannot build these images:")
        print("\n".join(f"  {p}" for p in problems))
        print("Commit the files, or un-ignore them in .gitignore.")
        return 1
    print("Every Dockerfile COPY source is tracked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
