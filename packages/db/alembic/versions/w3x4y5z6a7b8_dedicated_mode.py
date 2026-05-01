"""Per-agent dedicated-mode flag for opt-in pod scaling."""
from alembic import op
import sqlalchemy as sa


revision = "w3x4y5z6a7b8"
down_revision = "v2w3x4y5z6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("agents")} if insp.has_table("agents") else set()
    if "dedicated_mode" not in cols:
        op.add_column(
            "agents",
            sa.Column("dedicated_mode", sa.Boolean(),
                      nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("agents")} if insp.has_table("agents") else set()
    if "dedicated_mode" in cols:
        op.drop_column("agents", "dedicated_mode")
