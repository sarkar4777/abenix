"""Merge the healing branch and the main branch into one head for 2.5.0.

Revision ID: c5d6e7f8a9b0
Revises: 1100_f_patch_cas, a3c4d5e6f7a8
"""

from __future__ import annotations

revision = "c5d6e7f8a9b0"
down_revision = ("1100_f_patch_cas", "a3c4d5e6f7a8")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
