"""Sanitized global learning registry and tenant-scoped deployments.

Revision ID: 0011_global_learning_registry
Revises: 0010_durable_segmented_execution
Create Date: 2026-07-20 18:20:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models import Base


revision: str = "0011_global_learning_registry"
down_revision: Union[str, None] = "0010_durable_segmented_execution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table_name in ("global_learning_policies", "global_learning_deployments"):
        if table_name not in existing:
            Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        table = "global_learning_deployments"
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            sa.text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema() "
                "AND tablename = 'global_learning_deployments' AND policyname = 'asf_tenant_isolation') THEN "
                'CREATE POLICY asf_tenant_isolation ON "global_learning_deployments" '
                "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')) "
                "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')); "
                "END IF; END $$;"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "global_learning_deployments" in tables:
        active = bind.execute(sa.text("SELECT COUNT(*) FROM global_learning_deployments WHERE status = 'active'")).scalar_one()
        if active:
            raise RuntimeError("Cannot downgrade while global learning deployments are active")
        if bind.dialect.name == "postgresql":
            op.execute('DROP POLICY IF EXISTS asf_tenant_isolation ON "global_learning_deployments"')
        op.drop_table("global_learning_deployments")
    if "global_learning_policies" in tables:
        op.drop_table("global_learning_policies")
