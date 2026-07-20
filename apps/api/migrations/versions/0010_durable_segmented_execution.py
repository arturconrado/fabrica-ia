"""Durable segmented AI-native execution and fragment provenance.

Revision ID: 0010_durable_segmented_execution
Revises: 0009_ai_cost_governor
Create Date: 2026-07-20 18:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models import Base


revision: str = "0010_durable_segmented_execution"
down_revision: Union[str, None] = "0009_ai_cost_governor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table: str, name: str, column: sa.Column) -> None:
    if name not in _columns(table):
        op.add_column(table, column)


def _tenant_rls(table: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
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


def _drop_indexes_for(table: str, columns: set[str]) -> None:
    for index in sa.inspect(op.get_bind()).get_indexes(table):
        if columns.intersection(index.get("column_names") or []):
            op.drop_index(index["name"], table_name=table)


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables()
    for table_name in ("execution_units", "artifact_fragments"):
        if table_name not in existing:
            Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)

    _add("workflow_runs", "executor_protocol_version", sa.Column("executor_protocol_version", sa.String(), nullable=False, server_default="legacy"))
    _add("workflow_runs", "trace_id", sa.Column("trace_id", sa.String(), nullable=False, server_default=""))
    _add("workflow_runs", "last_heartbeat_at", sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True))

    _add("model_calls", "execution_unit_id", sa.Column("execution_unit_id", sa.String(), nullable=True))
    _add("model_calls", "provider_request_id", sa.Column("provider_request_id", sa.String(), nullable=False, server_default=""))
    _add("model_calls", "provider_route", sa.Column("provider_route", sa.String(), nullable=False, server_default=""))
    _add("model_calls", "finish_reason", sa.Column("finish_reason", sa.String(), nullable=False, server_default=""))
    _add("model_calls", "trace_id", sa.Column("trace_id", sa.String(), nullable=False, server_default=""))

    for table_name in ("execution_units", "artifact_fragments"):
        _tenant_rls(table_name)


def downgrade() -> None:
    bind = op.get_bind()
    if "workflow_runs" in _tables():
        protocol_column = "executor_protocol_version" in _columns("workflow_runs")
        dependent = bind.execute(
            sa.text("SELECT COUNT(*) FROM workflow_runs WHERE executor_protocol_version = 'segmented-output-v1'")
        ).scalar_one() if protocol_column else 0
        if dependent:
            raise RuntimeError("Cannot downgrade while segmented-output-v1 runs exist")

    for table, columns in (
        ("model_calls", ["trace_id", "finish_reason", "provider_route", "provider_request_id", "execution_unit_id"]),
        ("workflow_runs", ["last_heartbeat_at", "trace_id", "executor_protocol_version"]),
    ):
        if table not in _tables():
            continue
        _drop_indexes_for(table, set(columns))
        with op.batch_alter_table(table) as batch:
            for column in columns:
                if column in _columns(table):
                    batch.drop_column(column)
    for table in ("artifact_fragments", "execution_units"):
        if table in _tables():
            if bind.dialect.name == "postgresql":
                op.execute(f'DROP POLICY IF EXISTS asf_tenant_isolation ON "{table}"')
            op.drop_table(table)
