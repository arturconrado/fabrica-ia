"""AI invocation attribution and v2.13 cost-governor telemetry.

Revision ID: 0009_ai_cost_governor
Revises: 0008_service_delivery_os
Create Date: 2026-07-20 16:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models import Base


revision: str = "0009_ai_cost_governor"
down_revision: Union[str, None] = "0008_service_delivery_os"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "ai_invocations" not in existing:
        Base.metadata.tables["ai_invocations"].create(bind=bind, checkfirst=True)

    model_columns = _columns("model_calls")
    additions = {
        "ai_invocation_id": sa.Column("ai_invocation_id", sa.String(), sa.ForeignKey("ai_invocations.id"), nullable=True),
        "attempt_number": sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        "retry_classification": sa.Column("retry_classification", sa.String(), nullable=False, server_default=""),
        "routing_reason": sa.Column("routing_reason", sa.Text(), nullable=False, server_default=""),
        "projected_cost_usd": sa.Column("projected_cost_usd", sa.Float(), nullable=False, server_default="0"),
    }
    for name, column in additions.items():
        if name not in model_columns:
            op.add_column("model_calls", column)
    _index("ix_model_calls_ai_invocation_id", "model_calls", ["ai_invocation_id"])
    _index("ix_model_calls_retry_classification", "model_calls", ["retry_classification"])

    context_columns = _columns("context_builds")
    context_additions = {
        "ai_invocation_id": sa.Column("ai_invocation_id", sa.String(), sa.ForeignKey("ai_invocations.id"), nullable=True),
        "cited_tokens": sa.Column("cited_tokens", sa.Integer(), nullable=False, server_default="0"),
        "cited_references_json": sa.Column("cited_references_json", sa.JSON(), nullable=False, server_default="[]"),
    }
    for name, column in context_additions.items():
        if name not in context_columns:
            op.add_column("context_builds", column)
    _index("ix_context_builds_ai_invocation_id", "context_builds", ["ai_invocation_id"])

    if bind.dialect.name == "postgresql":
        op.execute('ALTER TABLE "ai_invocations" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "ai_invocations" FORCE ROW LEVEL SECURITY')
        op.execute(
            sa.text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema() "
                "AND tablename = 'ai_invocations' AND policyname = 'asf_tenant_isolation') THEN "
                'CREATE POLICY asf_tenant_isolation ON "ai_invocations" '
                "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')) "
                "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')); "
                "END IF; END $$;"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "context_builds" in set(sa.inspect(bind).get_table_names()):
        context_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("context_builds")}
        if "ix_context_builds_ai_invocation_id" in context_indexes:
            op.drop_index("ix_context_builds_ai_invocation_id", table_name="context_builds")
        with op.batch_alter_table("context_builds") as batch:
            for name in ["cited_references_json", "cited_tokens", "ai_invocation_id"]:
                if name in _columns("context_builds"):
                    batch.drop_column(name)
    if "model_calls" in set(sa.inspect(bind).get_table_names()):
        model_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("model_calls")}
        for index_name in ["ix_model_calls_ai_invocation_id", "ix_model_calls_retry_classification"]:
            if index_name in model_indexes:
                op.drop_index(index_name, table_name="model_calls")
        with op.batch_alter_table("model_calls") as batch:
            for name in ["projected_cost_usd", "routing_reason", "retry_classification", "attempt_number", "ai_invocation_id"]:
                if name in _columns("model_calls"):
                    batch.drop_column(name)
    if "ai_invocations" in set(sa.inspect(bind).get_table_names()):
        if bind.dialect.name == "postgresql":
            op.execute('DROP POLICY IF EXISTS asf_tenant_isolation ON "ai_invocations"')
        op.drop_table("ai_invocations")
