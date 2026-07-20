"""Provider cache telemetry and aggregate platform readiness evidence.

Revision ID: 0012_llmops_slo
Revises: 0011_global_learning_registry
Create Date: 2026-07-20 18:40:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models import Base


revision: str = "0012_llmops_slo"
down_revision: Union[str, None] = "0011_global_learning_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table: str, name: str, column: sa.Column) -> None:
    if name not in _columns(table):
        op.add_column(table, column)


def _drop_indexes_for(table: str, columns: set[str]) -> None:
    for index in sa.inspect(op.get_bind()).get_indexes(table):
        if columns.intersection(index.get("column_names") or []):
            op.drop_index(index["name"], table_name=table)


def upgrade() -> None:
    bind = op.get_bind()
    if "platform_readiness_evaluations" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["platform_readiness_evaluations"].create(bind=bind, checkfirst=True)

    _add("model_calls", "cache_eligible_tokens", sa.Column("cache_eligible_tokens", sa.Integer(), nullable=False, server_default="0"))
    _add("model_calls", "cache_write_tokens", sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"))
    _add("model_calls", "cache_savings_usd", sa.Column("cache_savings_usd", sa.Float(), nullable=False, server_default="0"))
    _add("model_calls", "prompt_cache_key", sa.Column("prompt_cache_key", sa.String(), nullable=False, server_default=""))

    _add("ai_invocations", "cache_eligible_tokens", sa.Column("cache_eligible_tokens", sa.Integer(), nullable=False, server_default="0"))
    _add("ai_invocations", "cache_write_tokens", sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"))
    _add("ai_invocations", "cache_savings_usd", sa.Column("cache_savings_usd", sa.Float(), nullable=False, server_default="0"))
    _add("ai_invocations", "trace_id", sa.Column("trace_id", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table, columns in (
        ("ai_invocations", ["trace_id", "cache_savings_usd", "cache_write_tokens", "cache_eligible_tokens"]),
        ("model_calls", ["prompt_cache_key", "cache_savings_usd", "cache_write_tokens", "cache_eligible_tokens"]),
    ):
        if table not in tables:
            continue
        _drop_indexes_for(table, set(columns))
        with op.batch_alter_table(table) as batch:
            for column in columns:
                if column in _columns(table):
                    batch.drop_column(column)
    if "platform_readiness_evaluations" in tables:
        op.drop_table("platform_readiness_evaluations")
