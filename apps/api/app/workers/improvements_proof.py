"""Proof worker for the improvements pool: claims queued proposals and proves them, apart from live traffic.

Run with `python -m app.workers.improvements_proof`. API pods stop draining when
IMPROVEMENTS_PROOF_DRAIN=pool, so proofs only run here.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

logger = logging.getLogger("abenix.improvements.worker")

POLL_SECONDS = float(os.environ.get("IMPROVEMENTS_PROOF_POLL_SECONDS", "5"))


async def main() -> None:
    os.environ["IMPROVEMENTS_PROOF_WORKER"] = "1"
    from app.services import improvements

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    logger.info("improvement proof worker started")
    while not stop.is_set():
        try:
            await improvements.drain_once()
        except Exception:  # noqa: BLE001
            logger.exception("proof drain failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
    # let proofs in flight finish their current step, claims expire for the rest
    pending = [t for t in improvements._tasks if not t.done()]  # noqa: SLF001
    if pending:
        await asyncio.wait(pending, timeout=60)


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
    asyncio.run(main())
