"""Operator profiles and shared technical operation keys.

Revision ID: 0018_operator_profiles_groups
Revises: 0017_rls_safe_service_scheduler
Create Date: 2026-07-31 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0018_operator_profiles_groups"
down_revision: Union[str, None] = "0017_rls_safe_service_scheduler"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    membership_columns = {item["name"] for item in inspector.get_columns("memberships")}
    work_item_columns = {item["name"] for item in inspector.get_columns("service_work_items")}
    if "operator_profile" not in membership_columns:
        op.add_column(
            "memberships",
            sa.Column("operator_profile", sa.String(), nullable=False, server_default="generalist"),
        )
    if "operation_key" not in work_item_columns:
        op.add_column(
            "service_work_items",
            sa.Column("operation_key", sa.String(), nullable=False, server_default=""),
        )

    inspector = sa.inspect(bind)
    constraints = {item["name"] for item in inspector.get_check_constraints("memberships")}
    if "ck_memberships_operator_profile" not in constraints:
        with op.batch_alter_table("memberships") as batch:
            batch.create_check_constraint(
                "ck_memberships_operator_profile",
                "operator_profile IN ('generalist', 'business_analyst', 'software_engineer', 'qa_quality', 'governance_risk')",
            )
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("service_work_items")}
    if "ix_service_work_items_operation_key" not in indexes:
        op.create_index(
            "ix_service_work_items_operation_key",
            "service_work_items",
            ["tenant_id", "engagement_id", "operation_key"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("service_work_items")}
    if "ix_service_work_items_operation_key" in indexes:
        op.drop_index("ix_service_work_items_operation_key", table_name="service_work_items")
    if "operation_key" in {item["name"] for item in sa.inspect(bind).get_columns("service_work_items")}:
        op.drop_column("service_work_items", "operation_key")
    constraints = {item["name"] for item in sa.inspect(bind).get_check_constraints("memberships")}
    if "ck_memberships_operator_profile" in constraints:
        with op.batch_alter_table("memberships") as batch:
            batch.drop_constraint("ck_memberships_operator_profile", type_="check")
    if "operator_profile" in {item["name"] for item in sa.inspect(bind).get_columns("memberships")}:
        op.drop_column("memberships", "operator_profile")
