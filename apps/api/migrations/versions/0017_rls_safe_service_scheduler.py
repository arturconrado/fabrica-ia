"""RLS-safe tenant discovery for the service scheduler.

Revision ID: 0017_rls_safe_service_scheduler
Revises: 0016_service_portfolio_v2
Create Date: 2026-07-21 21:30:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0017_rls_safe_service_scheduler"
down_revision: Union[str, None] = "0016_service_portfolio_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FUNCTION_NAME = "public.asf_active_tenant_ids"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # The function exposes only opaque scheduling identities. Tenant data is
    # still read and changed exclusively after set_tenant_context applies RLS.
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION {FUNCTION_NAME}()
            RETURNS TABLE (tenant_id text)
            LANGUAGE sql
            STABLE
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $function$
                SELECT tenant.id::text
                FROM public.tenants AS tenant
                WHERE tenant.status = 'active'
            $function$
            """
        )
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_NAME}() FROM PUBLIC")
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'factory_app') THEN "
            f"GRANT EXECUTE ON FUNCTION {FUNCTION_NAME}() TO factory_app; "
            "END IF; END $$;"
        )
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_NAME}()")
