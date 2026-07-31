"""Tenant-isolated audit records for pinned production plugins.

Revision ID: 0015_production_plugin_runtime
Revises: 0014_compact_unit_context
Create Date: 2026-07-20 22:30:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models import Base


revision: str = "0015_production_plugin_runtime"
down_revision: Union[str, None] = "0014_compact_unit_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "plugin_invocations" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["plugin_invocations"].create(bind=bind, checkfirst=True)
    additions = {
        "file_changes": [
            ("spec_refs_json", sa.Column("spec_refs_json", sa.JSON(), nullable=False, server_default="[]")),
        ],
        "test_reports": [
            ("spec_refs_json", sa.Column("spec_refs_json", sa.JSON(), nullable=False, server_default="[]")),
        ],
        "requirement_traces": [
            ("criterion_ids_json", sa.Column("criterion_ids_json", sa.JSON(), nullable=False, server_default="[]")),
            ("invariant_ids_json", sa.Column("invariant_ids_json", sa.JSON(), nullable=False, server_default="[]")),
            ("test_report_id", sa.Column("test_report_id", sa.String(), sa.ForeignKey("test_reports.id"), nullable=True)),
            ("provenance", sa.Column("provenance", sa.String(), nullable=False, server_default="declared")),
        ],
    }
    inspector = sa.inspect(bind)
    for table, columns in additions.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, column in columns:
            if name not in existing:
                op.add_column(table, column)
    trace_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("requirement_traces")}
    if "ix_requirement_traces_test_report_id" not in trace_indexes:
        op.create_index("ix_requirement_traces_test_report_id", "requirement_traces", ["test_report_id"])
    if "ix_requirement_traces_provenance" not in trace_indexes:
        op.create_index("ix_requirement_traces_provenance", "requirement_traces", ["provenance"])
    if bind.dialect.name != "postgresql":
        return
    op.execute('ALTER TABLE "plugin_invocations" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "plugin_invocations" FORCE ROW LEVEL SECURITY')
    op.execute(
        sa.text(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema() "
            "AND tablename = 'plugin_invocations' AND policyname = 'asf_tenant_isolation') THEN "
            'CREATE POLICY asf_tenant_isolation ON "plugin_invocations" '
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')); "
            "END IF; END $$;"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "plugin_invocations" in set(sa.inspect(bind).get_table_names()):
        dependent = bind.execute(sa.text("SELECT COUNT(*) FROM plugin_invocations")).scalar_one()
        if dependent:
            raise RuntimeError("Cannot downgrade while production plugin invocations exist")
        if bind.dialect.name == "postgresql":
            op.execute('DROP POLICY IF EXISTS asf_tenant_isolation ON "plugin_invocations"')
        op.drop_table("plugin_invocations")
    trace_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("requirement_traces")}
    for name in ("ix_requirement_traces_test_report_id", "ix_requirement_traces_provenance"):
        if name in trace_indexes:
            op.drop_index(name, table_name="requirement_traces")
    for table, columns in (
        ("requirement_traces", ["provenance", "test_report_id", "invariant_ids_json", "criterion_ids_json"]),
        ("test_reports", ["spec_refs_json"]),
        ("file_changes", ["spec_refs_json"]),
    ):
        existing = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        with op.batch_alter_table(table) as batch:
            for column in columns:
                if column in existing:
                    batch.drop_column(column)
