"""Compare-and-swap columns for pipeline patch proposals."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "1100_f_patch_cas"
down_revision = "1100_d_dead_letter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_patch_proposals",
        sa.Column("dsl_before_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "pipeline_patch_proposals",
        sa.Column("applied_snapshot", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pipeline_patch_proposals", "applied_snapshot")
    op.drop_column("pipeline_patch_proposals", "dsl_before_sha256")
