"""Add permanent TV device authentication and metadata.

Revision ID: 20260606_0002
Revises: 20260606_0001
Create Date: 2026-06-06 02:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260606_0002"
down_revision: str | None = "20260606_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "tv_devices",
        "provisioning_token_hash",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.add_column("tv_devices", sa.Column("device_token_hash", sa.Text()))
    op.add_column("tv_devices", sa.Column("android_id", sa.Text()))
    op.add_column("tv_devices", sa.Column("model", sa.Text()))
    op.add_column("tv_devices", sa.Column("screen_mode", sa.Text()))
    op.add_column("tv_devices", sa.Column("foreground", sa.Boolean()))
    op.create_index(
        "uq_tv_devices_device_token_hash",
        "tv_devices",
        ["device_token_hash"],
        unique=True,
        postgresql_where=sa.text("device_token_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_tv_devices_device_token_hash", table_name="tv_devices")
    op.drop_column("tv_devices", "foreground")
    op.drop_column("tv_devices", "screen_mode")
    op.drop_column("tv_devices", "model")
    op.drop_column("tv_devices", "android_id")
    op.drop_column("tv_devices", "device_token_hash")
    op.execute(
        """
        UPDATE tv_devices
        SET provisioning_token_hash = repeat('0', 64)
        WHERE provisioning_token_hash IS NULL
        """
    )
    op.alter_column(
        "tv_devices",
        "provisioning_token_hash",
        existing_type=sa.Text(),
        nullable=False,
    )
