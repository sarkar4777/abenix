"""Background reconciler for stuck ContractIQ extractions."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.core.deps import SessionLocal
from app.models.contractiq_models import ContractIQContract, ContractStatus

logger = logging.getLogger("contractiq.reconciler")

STUCK_THRESHOLD_SEC = 600  # 10 minutes
SWEEP_INTERVAL_SEC = 300   # 5 minutes


async def _sweep_once() -> int:
    """One reconciliation sweep. Returns number of rows fixed."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STUCK_THRESHOLD_SEC)
    fixed = 0
    async with SessionLocal() as db:
        result = await db.execute(
            select(ContractIQContract).where(
                ContractIQContract.status == ContractStatus.EXTRACTING,
                ContractIQContract.updated_at < cutoff,
            )
        )
        stuck = result.scalars().all()
        for c in stuck:
            # Snapshot ORM attrs BEFORE the update — after `await db.execute(update(...))`
            # the attributes get expired and touching them outside the greenlet raises
            # sqlalchemy.exc.MissingGreenlet, crashing the whole sweep.
            cid = c.id
            ctitle = c.title
            cupd = c.updated_at
            prev_summary = c.extraction_summary or {}
            new_summary = {
                **prev_summary,
                "extraction_error": "stuck_extraction_timeout",
                "extraction_error_detail": (
                    f"Extraction was in 'extracting' state longer than "
                    f"{STUCK_THRESHOLD_SEC}s without finishing (likely a torn SSE "
                    f"stream or pod restart). Marked as error so the user can retry."
                ),
                "stuck_cleared_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.execute(
                update(ContractIQContract)
                .where(ContractIQContract.id == cid)
                .values(
                    status=ContractStatus.ERROR,
                    extraction_summary=new_summary,
                )
            )
            fixed += 1
            logger.warning(
                "Reclaimed stuck extraction: contract_id=%s title=%r (last_updated=%s)",
                cid, ctitle, cupd,
            )
        if fixed:
            await db.commit()
    return fixed


async def reconcile_stuck_extractions_once() -> int:
    """Single-shot sweep used at startup."""
    try:
        fixed = await _sweep_once()
        if fixed:
            logger.info("Startup reconciliation fixed %d stuck extraction(s)", fixed)
        else:
            logger.info("Startup reconciliation found no stuck extractions")
        return fixed
    except Exception:
        logger.exception("Startup reconciliation sweep failed")
        return 0


async def reconciler_loop() -> None:
    """Periodic background sweep. Runs until cancelled."""
    while True:
        try:
            await asyncio.sleep(SWEEP_INTERVAL_SEC)
            await _sweep_once()
        except asyncio.CancelledError:
            logger.info("Reconciler loop cancelled")
            return
        except Exception:
            logger.exception("Reconciler loop iteration failed")
