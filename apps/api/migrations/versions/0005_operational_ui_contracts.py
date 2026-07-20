"""operational UI contracts and auditable gamification

Revision ID: 0005_operational_ui_contracts
Revises: 0004_tenant_knowledge_rag
Create Date: 2026-07-15 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_operational_ui_contracts"
down_revision: Union[str, None] = "0004_tenant_knowledge_rag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    artifact_columns = {column["name"] for column in inspector.get_columns("artifacts")}
    if "audience" not in artifact_columns:
        op.add_column(
            "artifacts",
            sa.Column("audience", sa.String(), nullable=False, server_default="internal"),
        )
        op.create_index("ix_artifacts_audience", "artifacts", ["audience"])

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("gamification_events")}
    if "uq_gamification_ledger_event_beneficiary" not in indexes:
        op.create_index(
            "uq_gamification_ledger_event_beneficiary",
            "gamification_events",
            ["tenant_id", "ledger_record_id", "event_type", "user_or_team"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("gamification_events")}
    if "uq_gamification_ledger_event_beneficiary" in indexes:
        op.drop_index("uq_gamification_ledger_event_beneficiary", table_name="gamification_events")
    artifact_columns = {column["name"] for column in sa.inspect(bind).get_columns("artifacts")}
    if "audience" in artifact_columns:
        op.drop_index("ix_artifacts_audience", table_name="artifacts")
        op.drop_column("artifacts", "audience")
