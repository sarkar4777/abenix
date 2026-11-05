"""A collection being deleted disappears from every ORM read at once."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))

from models.knowledge_base import KnowledgeBase

INCLUDE_TOMBSTONED = "include_tombstoned"


def _hide_tombstoned(state) -> None:
    if not state.is_select or state.execution_options.get(INCLUDE_TOMBSTONED):
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            KnowledgeBase, KnowledgeBase.deleted_at.is_(None), include_aliases=True
        )
    )


def install() -> None:
    if not event.contains(Session, "do_orm_execute", _hide_tombstoned):
        event.listen(Session, "do_orm_execute", _hide_tombstoned)
