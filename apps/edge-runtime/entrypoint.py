"""Picks the mode: an enrolled or enrolling Abenix Edge gateway, or the older agents-only runtime."""

import os
import sys
from pathlib import Path

data = Path(os.environ.get("ABENIX_EDGE_DATA", "/var/lib/abenix-edge"))
mode = os.environ.get("EDGE_MODE", "").strip().lower()
if mode not in ("", "legacy", "gateway"):
    sys.exit(f"EDGE_MODE must be legacy or gateway, got {mode}")
if mode:
    legacy = mode == "legacy"
else:
    # no explicit mode, the agents-only runtime is configured with PLATFORM_*, everything else is Abenix Edge
    legacy = (
        any(os.environ.get(k) for k in ("PLATFORM_TOKEN", "PLATFORM_URL"))
        and not any(os.environ.get(k) for k in ("ABENIX_URL", "ABENIX_ENROLL_TOKEN"))
        and not (data / "state.json").exists()
    )
if legacy:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from runtime import main
else:
    from abenix_edge.app import main

main()
