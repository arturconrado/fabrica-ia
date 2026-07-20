"""AI-native workflow v2 provenance and budgets

Revision ID: 0006_ai_native_workflow_v2
Revises: 0005_operational_ui_contracts
Create Date: 2026-07-15 01:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_ai_native_workflow_v2"
down_revision: Union[str, None] = "0005_operational_ui_contracts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _create_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    _add_column("ai_activities", sa.Column("model_call_id", sa.String(), nullable=True))
    _create_index("ix_ai_activities_model_call_id", "ai_activities", ["model_call_id"])
    _add_column("workflow_runs", sa.Column("generation_mode", sa.String(), nullable=False, server_default="deterministic_v1"))
    _add_column("workflow_runs", sa.Column("context_manifest_json", sa.JSON(), nullable=False, server_default="{}"))
    _add_column("workflow_runs", sa.Column("ai_budget_usd", sa.Float(), nullable=False, server_default="15"))
    _add_column("workflow_runs", sa.Column("ai_cost_usd", sa.Float(), nullable=False, server_default="0"))
    _create_index("ix_workflow_runs_generation_mode", "workflow_runs", ["generation_mode"])

    _add_column("model_calls", sa.Column("workflow_node_state_id", sa.String(), nullable=True))
    _add_column("model_calls", sa.Column("prompt_version_id", sa.String(), nullable=True))
    _add_column("model_calls", sa.Column("model_role", sa.String(), nullable=False, server_default="default"))
    _add_column("model_calls", sa.Column("input_hash", sa.String(), nullable=False, server_default=""))
    _add_column("model_calls", sa.Column("output_hash", sa.String(), nullable=False, server_default=""))
    _add_column("model_calls", sa.Column("context_refs_json", sa.JSON(), nullable=False, server_default="[]"))
    _add_column("model_calls", sa.Column("output_refs_json", sa.JSON(), nullable=False, server_default="[]"))
    for column in ["workflow_node_state_id", "prompt_version_id", "model_role", "input_hash", "output_hash"]:
        _create_index(f"ix_model_calls_{column}", "model_calls", [column])

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "agent_step_executions" not in tables:
        op.create_table(
            "agent_step_executions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("run_id", sa.String(), sa.ForeignKey("workflow_runs.id"), nullable=False),
            sa.Column("workflow_node_state_id", sa.String(), sa.ForeignKey("workflow_node_states.id"), nullable=False),
            sa.Column("model_call_id", sa.String(), sa.ForeignKey("model_calls.id"), nullable=True, unique=True),
            sa.Column("prompt_version_id", sa.String(), sa.ForeignKey("prompt_versions.id"), nullable=True),
            sa.Column("node_id", sa.String(), nullable=False),
            sa.Column("phase", sa.String(), nullable=False),
            sa.Column("iteration", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(), nullable=False, server_default="running"),
            sa.Column("decision", sa.String(), nullable=False, server_default=""),
            sa.Column("input_hash", sa.String(), nullable=False),
            sa.Column("output_hash", sa.String(), nullable=False, server_default=""),
            sa.Column("input_manifest_json", sa.JSON(), nullable=False),
            sa.Column("output_manifest_json", sa.JSON(), nullable=False),
            sa.Column("output_refs_json", sa.JSON(), nullable=False),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("tenant_id", "run_id", "node_id", "iteration", "attempt", name="uq_agent_step_attempt"),
        )
        for column in ["tenant_id", "run_id", "workflow_node_state_id", "model_call_id", "prompt_version_id", "node_id", "phase", "status", "input_hash", "output_hash", "started_at"]:
            op.create_index(f"ix_agent_step_executions_{column}", "agent_step_executions", [column])

    _add_column("artifacts", sa.Column("model_call_id", sa.String(), nullable=True))
    _add_column("artifacts", sa.Column("step_execution_id", sa.String(), nullable=True))
    _add_column("file_changes", sa.Column("model_call_id", sa.String(), nullable=True))
    _add_column("file_changes", sa.Column("step_execution_id", sa.String(), nullable=True))
    for table in ["artifacts", "file_changes"]:
        _create_index(f"ix_{table}_model_call_id", table, ["model_call_id"])
        _create_index(f"ix_{table}_step_execution_id", table, ["step_execution_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute('ALTER TABLE "agent_step_executions" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "agent_step_executions" FORCE ROW LEVEL SECURITY')
        op.execute(
            sa.text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema() "
                "AND tablename = 'agent_step_executions' AND policyname = 'asf_tenant_isolation') THEN "
                'CREATE POLICY asf_tenant_isolation ON "agent_step_executions" '
                "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')) "
                "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')); "
                "END IF; END $$;"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    # Revision 0001 intentionally creates the current SQLAlchemy metadata for
    # fresh local SQLite databases. In that case these columns/tables already
    # predate revision 0006 and must be left for 0001 to remove at `base`.
    if bind.dialect.name == "sqlite":
        return
    tables = set(sa.inspect(bind).get_table_names())
    if "agent_step_executions" in tables:
        if bind.dialect.name == "postgresql":
            op.execute('DROP POLICY IF EXISTS asf_tenant_isolation ON "agent_step_executions"')
        op.drop_table("agent_step_executions")
    for table in ["file_changes", "artifacts"]:
        for column in ["step_execution_id", "model_call_id"]:
            if column in _columns(table):
                op.drop_column(table, column)
    for column in [
        "output_refs_json",
        "context_refs_json",
        "output_hash",
        "input_hash",
        "model_role",
        "prompt_version_id",
        "workflow_node_state_id",
    ]:
        if column in _columns("model_calls"):
            op.drop_column("model_calls", column)
    for column in ["ai_cost_usd", "ai_budget_usd", "context_manifest_json", "generation_mode"]:
        if column in _columns("workflow_runs"):
            op.drop_column("workflow_runs", column)
    if "model_call_id" in _columns("ai_activities"):
        op.drop_column("ai_activities", "model_call_id")
