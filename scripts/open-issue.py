"""Open one issue on the public repo and record it in an issues file.

    python scripts/open-issue.py issues/2026-10-02-ui-journey.json --title T --problem P [--area A] [--label L]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--title", required=True)
    ap.add_argument("--problem", required=True)
    ap.add_argument("--fix", default="")
    ap.add_argument("--area", default="")
    ap.add_argument("--label", action="append", default=[])
    a = ap.parse_args()
    cmd = [
        sys.executable,
        str(Path(__file__).with_name("log-fixed-issues.py")),
        "open",
        "--title",
        a.title,
        "--problem",
        a.problem,
        "--area",
        a.area,
    ]
    for lab in a.label:
        cmd += ["--label", lab]
    out = subprocess.run(cmd, capture_output=True, text=True)
    print(out.stdout.strip() or out.stderr.strip()[-300:])
    m = re.search(r"#(\d+)", out.stdout)
    if not m:
        sys.exit(1)
    path = Path(a.file)
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    if not any(e.get("number") == int(m.group(1)) for e in entries):
        entries.append(
            {
                "title": a.title,
                "area": a.area,
                "problem": a.problem,
                "fix": a.fix,
                "fixed_in": "PENDING",
                "labels": a.label or ["bug"],
                "number": int(m.group(1)),
            }
        )
        path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
