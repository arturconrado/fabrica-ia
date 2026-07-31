"""Versioned service portfolio, durable executions and acceptance evidence.

Revision ID: 0016_service_portfolio_v2
Revises: 0015_production_plugin_runtime
Create Date: 2026-07-21 10:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models import Base


revision: str = "0016_service_portfolio_v2"
down_revision: Union[str, None] = "0015_production_plugin_runtime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_TABLES = [
    "service_cycles",
    "service_executions",
    "service_acceptance_checks",
    "engagement_dependencies",
]


def _column_names(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _drop_index_if_exists(bind, table: str, name: str) -> None:
    if name in {index["name"] for index in sa.inspect(bind).get_indexes(table)}:
        op.drop_index(name, table_name=table)


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "service_cycles" not in existing:
        Base.metadata.tables["service_cycles"].create(bind=bind, checkfirst=True)

    additions = {
        "offering_versions": [
            sa.Column("display_name", sa.String(), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
        ],
        "engagement_plans": [
            sa.Column("created_by_user_id", sa.String(), nullable=False, server_default=""),
        ],
        "service_work_items": [
            sa.Column("cycle_id", sa.String(), sa.ForeignKey("service_cycles.id"), nullable=True),
            sa.Column("execution_mode", sa.String(), nullable=False, server_default="agent"),
        ],
        "service_deliverables": [
            sa.Column("cycle_id", sa.String(), sa.ForeignKey("service_cycles.id"), nullable=True),
        ],
        "temporal_command_outbox": [
            sa.Column("aggregate_type", sa.String(), nullable=False, server_default="workflow_run"),
            sa.Column("aggregate_id", sa.String(), nullable=False, server_default=""),
        ],
    }
    for table, columns in additions.items():
        names = _column_names(bind, table)
        with op.batch_alter_table(table) as batch:
            for column in columns:
                if column.name not in names:
                    batch.add_column(column)

    for name, table, columns in (
        ("ix_engagement_plans_created_by_user_id", "engagement_plans", ["created_by_user_id"]),
        ("ix_service_work_items_cycle_id", "service_work_items", ["cycle_id"]),
        ("ix_service_work_items_execution_mode", "service_work_items", ["execution_mode"]),
        ("ix_service_deliverables_cycle_id", "service_deliverables", ["cycle_id"]),
        ("ix_temporal_command_outbox_aggregate_type", "temporal_command_outbox", ["aggregate_type"]),
        ("ix_temporal_command_outbox_aggregate_id", "temporal_command_outbox", ["aggregate_id"]),
    ):
        if name not in {item["name"] for item in sa.inspect(bind).get_indexes(table)}:
            op.create_index(name, table, columns)

    with op.batch_alter_table("temporal_command_outbox") as batch:
        batch.alter_column("run_id", existing_type=sa.String(), nullable=True)

    bind.execute(
        sa.text(
            "UPDATE offering_versions SET display_name = COALESCE(("
            "SELECT name FROM service_offerings WHERE service_offerings.id = offering_versions.offering_id"
            "), ''), description = COALESCE(("
            "SELECT description FROM service_offerings WHERE service_offerings.id = offering_versions.offering_id"
            "), '') WHERE display_name = ''"
        )
    )

    existing = set(sa.inspect(bind).get_table_names())
    for table in TENANT_TABLES[1:]:
        if table not in existing:
            Base.metadata.tables[table].create(bind=bind, checkfirst=True)

    if bind.dialect.name != "postgresql":
        return
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            sa.text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema() "
                f"AND tablename = '{table}' AND policyname = 'asf_tenant_isolation') THEN "
                f'CREATE POLICY asf_tenant_isolation ON "{table}" '
                "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')) "
                "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')); "
                "END IF; END $$;"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table in TENANT_TABLES:
        if table in existing and bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError(f"Cannot downgrade while {table} contains portfolio v2 evidence")
    if "temporal_command_outbox" in existing and bind.execute(
        sa.text("SELECT COUNT(*) FROM temporal_command_outbox WHERE aggregate_type = 'service_execution'")
    ).scalar_one():
        raise RuntimeError("Cannot downgrade while service execution Temporal commands exist")

    for table, index in (
        ("temporal_command_outbox", "ix_temporal_command_outbox_aggregate_id"),
        ("temporal_command_outbox", "ix_temporal_command_outbox_aggregate_type"),
        ("service_deliverables", "ix_service_deliverables_cycle_id"),
        ("service_work_items", "ix_service_work_items_cycle_id"),
        ("service_work_items", "ix_service_work_items_execution_mode"),
        ("engagement_plans", "ix_engagement_plans_created_by_user_id"),
    ):
        _drop_index_if_exists(bind, table, index)

    with op.batch_alter_table("temporal_command_outbox") as batch:
        batch.alter_column("run_id", existing_type=sa.String(), nullable=False)
        for name in ("aggregate_id", "aggregate_type"):
            if name in _column_names(bind, "temporal_command_outbox"):
                batch.drop_column(name)
    for table, columns in (
        ("service_deliverables", ("cycle_id",)),
        ("service_work_items", ("execution_mode", "cycle_id")),
        ("engagement_plans", ("created_by_user_id",)),
        ("offering_versions", ("description", "display_name")),
    ):
        names = _column_names(bind, table)
        with op.batch_alter_table(table) as batch:
            for name in columns:
                if name in names:
                    batch.drop_column(name)

    # Remove the foreign keys from existing service tables before dropping the
    # cycle table they reference. This ordering is required by SQLite as well
    # as PostgreSQL and keeps a fresh upgrade/downgrade reproducible.
    for table in reversed(TENANT_TABLES):
        if table in existing:
            if bind.dialect.name == "postgresql":
                op.execute(f'DROP POLICY IF EXISTS asf_tenant_isolation ON "{table}"')
            op.drop_table(table)
