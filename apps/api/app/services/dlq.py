"""Dead-letter queue writes, shared with the runtime through packages/db."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from dead_letters import (  # noqa: E402,F401
    _as_uuid,
    build_original_input,
    dead_letter,
    get_dead_letter,
    logger,
)
from models.dead_letter import DeadLetterExecution  # noqa: E402,F401
from models.execution import Execution  # noqa: E402,F401
