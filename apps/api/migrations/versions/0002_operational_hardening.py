"""operational hardening for the assisted ten-tenant pilot

Revision ID: 0002_operational_hardening
Revises: 0001_initial_production_schema
Create Date: 2026-07-14 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models import Base


revision: str = "0002_operational_hardening"
down_revision: Union[str, None] = "0001_initial_production_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TENANT_TABLES = [
    "roles", "memberships", "api_keys", "secret_references", "tool_policies", "model_policies",
    "audit_logs", "programs", "projects", "contracts", "entitlements", "component_instances",
    "approvals", "ledger_records", "audit_projections", "gamification_events", "scores", "prospects",
    "opportunities", "briefings", "mvp_specs", "mvp_runs", "ai_activities", "agent_recommendations",
    "commercial_proposals", "workflow_definitions", "workflow_runs", "workflow_node_states", "agent_events",
    "agent_messages", "agent_work_items", "agent_run_states", "artifacts", "file_changes", "test_reports",
    "requirements", "acceptance_criteria", "requirement_traces", "quality_gates", "quality_scores",
    "risk_items", "decision_records", "homologation_packages", "homologation_reports", "approval_requests",
    "human_feedback", "reward_signals", "learning_lessons", "agent_memory", "batches", "batch_items",
    "batch_metrics", "workflow_candidates", "reusable_templates", "model_calls", "mcp_servers",
    "mcp_tool_invocations", "sandbox_executions", "ledger_heads", "command_receipts",
]


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return _has_table(inspector, table) and column in {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    # The original 0001 imported live metadata. Existing 0001 installations
    # therefore lack tables added later; install them before hardening.
    Base.metadata.create_all(bind=bind)
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "ledger_records", "tenant_sequence"):
        op.add_column("ledger_records", sa.Column("tenant_sequence", sa.Integer(), nullable=True))
        bind.execute(
            sa.text(
                "WITH ranked AS ("
                " SELECT id, ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY created_at, id) AS seq"
                " FROM ledger_records"
                ") UPDATE ledger_records SET tenant_sequence = ranked.seq FROM ranked "
                "WHERE ledger_records.id = ranked.id"
            )
        )
        op.alter_column("ledger_records", "tenant_sequence", nullable=False)

    if not _has_column(inspector, "artifacts", "mvp_run_id"):
        op.add_column("artifacts", sa.Column("mvp_run_id", sa.String(), nullable=True))
        op.create_foreign_key("fk_artifacts_mvp_run", "artifacts", "mvp_runs", ["mvp_run_id"], ["id"])
        op.create_index("ix_artifacts_mvp_run_id", "artifacts", ["mvp_run_id"])
    if not _has_column(inspector, "artifacts", "evidence_classification"):
        op.add_column(
            "artifacts",
            sa.Column("evidence_classification", sa.String(), nullable=False, server_default="declared"),
        )
        op.create_index("ix_artifacts_evidence_classification", "artifacts", ["evidence_classification"])
    if not _has_column(inspector, "artifacts", "source_refs_json"):
        op.add_column("artifacts", sa.Column("source_refs_json", sa.JSON(), nullable=False, server_default="[]"))
    if _has_column(inspector, "artifacts", "run_id"):
        run_id_column = next(item for item in inspector.get_columns("artifacts") if item["name"] == "run_id")
        if not run_id_column.get("nullable", True):
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("artifacts") as batch_op:
                    batch_op.alter_column("run_id", existing_type=sa.String(), nullable=True)
            else:
                op.alter_column("artifacts", "run_id", existing_type=sa.String(), nullable=True)

    inspector = sa.inspect(bind)
    if not _has_table(inspector, "ledger_heads"):
        op.create_table(
            "ledger_heads",
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), primary_key=True),
            sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_hash", sa.String(), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not _has_table(inspector, "command_receipts"):
        op.create_table(
            "command_receipts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("command_name", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("request_hash", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="started"),
            sa.Column("resource_type", sa.String(), nullable=False, server_default=""),
            sa.Column("resource_id", sa.String(), nullable=False, server_default=""),
            sa.Column("response_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("tenant_id", "command_name", "idempotency_key", name="uq_command_receipt"),
        )
    if not _has_table(inspector, "workflow_slots"):
        op.create_table(
            "workflow_slots",
            sa.Column("run_id", sa.String(), sa.ForeignKey("workflow_runs.id"), primary_key=True),
            sa.Column("slot_number", sa.Integer(), nullable=False, unique=True),
            sa.Column("acquired_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_workflow_slots_acquired_at", "workflow_slots", ["acquired_at"])

    inspector = sa.inspect(bind)
    if not _has_column(inspector, "command_receipts", "lease_expires_at"):
        op.add_column("command_receipts", sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
        op.create_index("ix_command_receipts_lease_expires_at", "command_receipts", ["lease_expires_at"])
    if not _has_column(inspector, "command_receipts", "attempt_count"):
        op.add_column(
            "command_receipts",
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        )
    if not _has_column(inspector, "workflow_slots", "heartbeat_at"):
        op.add_column("workflow_slots", sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
        op.create_index("ix_workflow_slots_heartbeat_at", "workflow_slots", ["heartbeat_at"])
    if not _has_column(inspector, "workflow_slots", "lease_expires_at"):
        op.add_column("workflow_slots", sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
        op.create_index("ix_workflow_slots_lease_expires_at", "workflow_slots", ["lease_expires_at"])

    if bind.dialect.name != "postgresql":
        return

    op.execute('ALTER TABLE "tenants" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "tenants" FORCE ROW LEVEL SECURITY')
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema() "
            "AND tablename = 'tenants' AND policyname = 'asf_tenant_membership_isolation') THEN "
            "CREATE POLICY asf_tenant_membership_isolation ON tenants "
            "USING (id = NULLIF(current_setting('app.tenant_id', true), '') OR EXISTS ("
            "SELECT 1 FROM memberships m WHERE m.tenant_id = tenants.id "
            "AND m.user_id = NULLIF(current_setting('app.user_id', true), '') AND m.status = 'active')) "
            "WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')); "
            "END IF; END $$;"
        )
    )

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_tenant_sequence "
        "ON ledger_records (tenant_id, tenant_sequence)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_tenant_idempotency "
        "ON ledger_records (tenant_id, idempotency_key) WHERE idempotency_key <> ''"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_memberships_tenant_user "
        "ON memberships (tenant_id, user_id)"
    )
    for name, table, columns in [
        ("uq_contract_tenant_number", "contracts", "tenant_id, contract_number"),
        ("uq_entitlement_contract_component", "entitlements", "tenant_id, contract_id, component_code"),
        ("uq_component_project_code", "component_instances", "tenant_id, project_id, component_code"),
        ("uq_mvp_spec_opportunity", "mvp_specs", "tenant_id, opportunity_id"),
        ("uq_mvp_run_opportunity", "mvp_runs", "tenant_id, opportunity_id"),
        ("uq_proposal_opportunity", "commercial_proposals", "tenant_id, opportunity_id"),
    ]:
        op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({columns})")

    inspector = sa.inspect(bind)
    for table in TENANT_TABLES:
        if not _has_column(inspector, table, "tenant_id"):
            continue
        using = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')"
        if table == "memberships":
            using = (
                f"({using}) OR user_id = NULLIF(current_setting('app.user_id', true), '')"
            )
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            sa.text(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema() "
                f"AND tablename = '{table}' AND policyname = 'asf_tenant_isolation') THEN "
                f"CREATE POLICY asf_tenant_isolation ON \"{table}\" USING ({using}) "
                "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')); "
                "END IF; END $$;"
            )
        )

    for table in ["prompt_versions", "prompt_evaluations"]:
        if not _has_column(inspector, table, "tenant_id"):
            continue
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            sa.text(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema() "
                f"AND tablename = '{table}' AND policyname = 'asf_tenant_or_global') THEN "
                f"CREATE POLICY asf_tenant_or_global ON \"{table}\" "
                "USING (tenant_id = 'global' OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')) "
                "WITH CHECK (tenant_id = 'global' OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')); "
                "END IF; END $$;"
            )
        )

    op.execute(
        "CREATE OR REPLACE FUNCTION reject_ledger_mutation() RETURNS trigger AS $$ "
        "BEGIN RAISE EXCEPTION 'ledger_records is append-only'; END; $$ LANGUAGE plpgsql"
    )
    op.execute("DROP TRIGGER IF EXISTS ledger_records_append_only ON ledger_records")
    op.execute(
        "CREATE TRIGGER ledger_records_append_only BEFORE UPDATE OR DELETE ON ledger_records "
        "FOR EACH ROW EXECUTE FUNCTION reject_ledger_mutation()"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS ledger_records_append_only ON ledger_records")
    op.execute("DROP FUNCTION IF EXISTS reject_ledger_mutation()")
    op.execute('DROP POLICY IF EXISTS asf_tenant_membership_isolation ON "tenants"')
    op.execute('ALTER TABLE "tenants" NO FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "tenants" DISABLE ROW LEVEL SECURITY')
    inspector = sa.inspect(bind)
    for table in TENANT_TABLES:
        if _has_column(inspector, table, "tenant_id"):
            op.execute(f'DROP POLICY IF EXISTS asf_tenant_isolation ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    for table in ["prompt_versions", "prompt_evaluations"]:
        if _has_column(inspector, table, "tenant_id"):
            op.execute(f'DROP POLICY IF EXISTS asf_tenant_or_global ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
