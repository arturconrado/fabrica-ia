"""Auditable compact context telemetry for segmented execution units.

Revision ID: 0014_compact_unit_context
Revises: 0013_aggregate_technical_metrics
Create Date: 2026-07-20 21:30:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0014_compact_unit_context"
down_revision: Union[str, None] = "0013_aggregate_technical_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    additions = (
        ("context_hash", sa.Column("context_hash", sa.String(), nullable=False, server_default="")),
        ("context_manifest_json", sa.Column("context_manifest_json", sa.JSON(), nullable=False, server_default="{}")),
        ("estimated_input_tokens", sa.Column("estimated_input_tokens", sa.Integer(), nullable=False, server_default="0")),
        ("source_input_tokens", sa.Column("source_input_tokens", sa.Integer(), nullable=False, server_default="0")),
        ("saved_input_tokens", sa.Column("saved_input_tokens", sa.Integer(), nullable=False, server_default="0")),
        ("optimization_policy_version", sa.Column("optimization_policy_version", sa.String(), nullable=False, server_default="")),
    )
    existing = _columns("execution_units")
    for name, column in additions:
        if name not in existing:
            op.add_column("execution_units", column)
    existing_indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("execution_units")}
    if "ix_execution_units_context_hash" not in existing_indexes:
        op.create_index("ix_execution_units_context_hash", "execution_units", ["context_hash"], unique=False)
    if "ix_execution_units_optimization_policy_version" not in existing_indexes:
        op.create_index(
            "ix_execution_units_optimization_policy_version",
            "execution_units",
            ["optimization_policy_version"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    dependent = bind.execute(
        sa.text("SELECT COUNT(*) FROM execution_units WHERE optimization_policy_version <> ''")
    ).scalar_one()
    if dependent:
        raise RuntimeError("Cannot downgrade while compact-context execution units exist")
    existing_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("execution_units")}
    for name in ("ix_execution_units_optimization_policy_version", "ix_execution_units_context_hash"):
        if name in existing_indexes:
            op.drop_index(name, table_name="execution_units")
    existing = _columns("execution_units")
    with op.batch_alter_table("execution_units") as batch:
        for name in (
            "optimization_policy_version",
            "saved_input_tokens",
            "source_input_tokens",
            "estimated_input_tokens",
            "context_manifest_json",
            "context_hash",
        ):
            if name in existing:
                batch.drop_column(name)
