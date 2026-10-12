"""Picks the mode: an enrolled or enrolling Abenix Edge gateway, or the older agents-only runtime."""

import os
import sys
from pathlib import Path

data = Path(os.environ.get("ABENIX_EDGE_DATA", "/var/lib/abenix-edge"))
# the agents-only runtime is configured with PLATFORM_*, everything else is Abenix Edge
legacy = any(os.environ.get(k) for k in ("PLATFORM_TOKEN", "PLATFORM_URL")) and not any(
    os.environ.get(k) for k in ("ABENIX_URL", "ABENIX_ENROLL_TOKEN")
)
if legacy and not (data / "state.json").exists():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from runtime import main
else:
    from abenix_edge.app import main

main()
