"""Add subject_policies table + market_alerts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "j0e1f2g3h4i5"
down_revision = "h8c9d0e1f2g3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Subject policies for RBAC delegation
    op.create_table(
        'subject_policies',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('api_key_id', UUID(as_uuid=True),
                  sa.ForeignKey('api_keys.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('subject_type', sa.String(50), nullable=False, index=True),
        sa.Column('subject_id', sa.String(255), nullable=False, index=True),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('rules', JSONB, default={}),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_subject_policies_lookup', 'subject_policies',
                    ['api_key_id', 'subject_type', 'subject_id'])

    # the example app Market Alerts
    op.create_table(
        'example_app_market_alerts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('contract_id', UUID(as_uuid=True),
                  sa.ForeignKey('example_app_contracts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('alert_type', sa.String(100), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('market_data_snapshot', JSONB, nullable=True),
        sa.Column('contract_field', sa.String(255), nullable=True),
        sa.Column('contract_value', sa.String(255), nullable=True),
        sa.Column('market_value', sa.String(255), nullable=True),
        sa.Column('delta_pct', sa.Float, nullable=True),
        sa.Column('is_acknowledged', sa.Boolean, default=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_example_app_alerts_contract', 'example_app_market_alerts', ['contract_id'])
    op.create_index('ix_example_app_alerts_severity', 'example_app_market_alerts', ['severity'])


def downgrade() -> None:
    op.drop_table('example_app_market_alerts')
    op.drop_table('subject_policies')
