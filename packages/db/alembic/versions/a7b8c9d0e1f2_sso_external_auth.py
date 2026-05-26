"""Add SSO/OIDC columns to users.

Enables Google / GitHub / Microsoft sign-in alongside the existing
email+password flow.

  - auth_provider: NULL for password-auth users; "google" / "github" /
    "microsoft" for SSO users (extensible — anything < 32 chars works).
  - external_id: the provider's stable user identifier (Google `sub`,
    GitHub numeric `id`, Microsoft `oid`). Indexed jointly with
    auth_provider so the OIDC callback can look users up in one query.
  - password_hash: now nullable, because SSO-provisioned users have no
    local password. Local-auth users still set this.

Revision ID: a7b8c9d0e1f2
Revises: z6a7b8c9d0e1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d0e1f2"
down_revision = "z6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("auth_provider", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "users", sa.Column("external_id", sa.String(length=255), nullable=True)
    )
    op.alter_column("users", "password_hash", nullable=True)
    op.create_index(
        "ix_users_provider_external",
        "users",
        ["auth_provider", "external_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_provider_external", table_name="users")
    op.alter_column("users", "password_hash", nullable=False)
    op.drop_column("users", "external_id")
    op.drop_column("users", "auth_provider")
