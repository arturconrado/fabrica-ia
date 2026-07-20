"""Service Delivery OS catalog, engagements, deliverables and governed agents.

Revision ID: 0008_service_delivery_os
Revises: 0007_context_learning_optimization
Create Date: 2026-07-20 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models import Base


revision: str = "0008_service_delivery_os"
down_revision: Union[str, None] = "0007_context_learning_optimization"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


GLOBAL_TABLES = ["service_offerings", "offering_versions", "agent_templates"]
TENANT_TABLES = [
    "engagements",
    "engagement_plans",
    "workstreams",
    "service_deliverables",
    "deliverable_revisions",
    "service_work_items",
    "outcome_metrics",
    "agent_definitions",
    "agent_versions",
    "capability_gaps",
    "agent_candidates",
    "agent_evaluations",
    "agent_assignments",
]


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for name in [*GLOBAL_TABLES, *TENANT_TABLES]:
        if name not in existing:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)

    if bind.dialect.name == "postgresql":
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
    for table in reversed(TENANT_TABLES):
        if table in existing:
            if bind.dialect.name == "postgresql":
                op.execute(f'DROP POLICY IF EXISTS asf_tenant_isolation ON "{table}"')
            op.drop_table(table)
    for table in reversed(GLOBAL_TABLES):
        if table in existing:
            op.drop_table(table)
