"""transactional outbox for Temporal commands

Revision ID: 0003_temporal_transactional_outbox
Revises: 0002_operational_hardening
Create Date: 2026-07-14 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_temporal_transactional_outbox"
down_revision: Union[str, None] = "0002_operational_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # This historical revision identifier is 34 characters. PostgreSQL's
    # default Alembic version column is VARCHAR(32), so widen it before Alembic
    # persists the revision after this upgrade.
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=32),
            type_=sa.String(length=64),
            existing_nullable=False,
        )
    inspector = sa.inspect(bind)
    # Historical migrations import live metadata, so a freshly-created database
    # may already contain this table. Existing 0002 databases will not.
    if "temporal_command_outbox" in inspector.get_table_names():
        return
    op.create_table(
        "temporal_command_outbox",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("run_id", sa.String(), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("command_type", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("signal_name", sa.String(), nullable=False, server_default=""),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("deduplication_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("deduplication_key", name="uq_temporal_command_outbox_deduplication"),
    )
    op.create_index("ix_temporal_command_outbox_tenant_id", "temporal_command_outbox", ["tenant_id"])
    op.create_index("ix_temporal_command_outbox_run_id", "temporal_command_outbox", ["run_id"])
    op.create_index("ix_temporal_command_outbox_command_type", "temporal_command_outbox", ["command_type"])
    op.create_index("ix_temporal_command_outbox_workflow_id", "temporal_command_outbox", ["workflow_id"])
    op.create_index("ix_temporal_command_outbox_status", "temporal_command_outbox", ["status"])
    op.create_index("ix_temporal_command_outbox_lease_expires_at", "temporal_command_outbox", ["lease_expires_at"])
    op.create_index("ix_temporal_command_outbox_next_attempt_at", "temporal_command_outbox", ["next_attempt_at"])
    op.create_index("ix_temporal_command_outbox_created_at", "temporal_command_outbox", ["created_at"])
    op.create_index(
        "ix_temporal_command_outbox_dispatch",
        "temporal_command_outbox",
        ["status", "next_attempt_at", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "temporal_command_outbox" in sa.inspect(bind).get_table_names():
        op.drop_table("temporal_command_outbox")
