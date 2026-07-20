"""Context telemetry and curated learning controls.

Revision ID: 0007_context_learning_optimization
Revises: 0006_ai_native_workflow_v2
Create Date: 2026-07-16 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_context_learning_optimization"
down_revision: Union[str, None] = "0006_ai_native_workflow_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TENANT_TABLES = [
    "context_builds",
    "content_digests",
    "learning_signals",
    "learning_candidates",
    "learning_evaluations",
    "learning_policies",
]


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def _tenant_indexes(table: str, extra: list[str]) -> None:
    for column in ["tenant_id", *extra]:
        _index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    for name in ["cache_read_tokens", "cache_creation_tokens", "max_output_tokens"]:
        if name not in _columns("model_calls"):
            op.add_column("model_calls", sa.Column(name, sa.Integer(), nullable=False, server_default="0"))

    tables = _tables()
    if "context_builds" not in tables:
        op.create_table(
            "context_builds",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("run_id", sa.String(), sa.ForeignKey("workflow_runs.id"), nullable=False),
            sa.Column("step_execution_id", sa.String(), sa.ForeignKey("agent_step_executions.id"), nullable=False),
            sa.Column("node_id", sa.String(), nullable=False),
            sa.Column("policy_version", sa.String(), nullable=False),
            sa.Column("input_budget_tokens", sa.Integer(), nullable=False),
            sa.Column("estimated_input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("selected_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("discarded_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("selected_references_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("discarded_references_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("selection_reasons_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tenant_id", "step_execution_id", name="uq_context_build_step"),
        )
        _tenant_indexes("context_builds", ["run_id", "step_execution_id", "node_id", "policy_version", "created_at"])

    if "content_digests" not in tables:
        op.create_table(
            "content_digests",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("source_kind", sa.String(), nullable=False),
            sa.Column("source_id", sa.String(), nullable=False),
            sa.Column("checksum", sa.String(), nullable=False),
            sa.Column("digest", sa.Text(), nullable=False),
            sa.Column("original_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("digest_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tenant_id", "source_kind", "checksum", name="uq_content_digest_tenant_checksum"),
        )
        _tenant_indexes("content_digests", ["source_kind", "source_id", "checksum", "created_at"])

    if "learning_signals" not in tables:
        op.create_table(
            "learning_signals",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("run_id", sa.String(), nullable=False, server_default=""),
            sa.Column("signal_type", sa.String(), nullable=False),
            sa.Column("source_type", sa.String(), nullable=False),
            sa.Column("source_id", sa.String(), nullable=False),
            sa.Column("agent_name", sa.String(), nullable=False, server_default=""),
            sa.Column("prompt_version_id", sa.String(), sa.ForeignKey("prompt_versions.id"), nullable=True),
            sa.Column("model_call_id", sa.String(), sa.ForeignKey("model_calls.id"), nullable=True),
            sa.Column("value", sa.Float(), nullable=False, server_default="0"),
            sa.Column("evidence_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("eligible_for_global", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tenant_id", "signal_type", "source_type", "source_id", name="uq_learning_signal_source"),
        )
        _tenant_indexes("learning_signals", ["run_id", "signal_type", "source_type", "source_id", "agent_name", "prompt_version_id", "model_call_id", "eligible_for_global", "created_at"])

    if "global_learning_evidence" not in tables:
        op.create_table(
            "global_learning_evidence",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("pattern_fingerprint", sa.String(), nullable=False),
            sa.Column("tenant_pseudonym", sa.String(), nullable=False),
            sa.Column("run_fingerprint", sa.String(), nullable=False),
            sa.Column("critical_security", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("pattern_fingerprint", "tenant_pseudonym", "run_fingerprint", name="uq_global_learning_evidence"),
        )
        for column in ["pattern_fingerprint", "tenant_pseudonym", "run_fingerprint", "created_at"]:
            _index(f"ix_global_learning_evidence_{column}", "global_learning_evidence", [column])

    if "learning_candidates" not in tables:
        op.create_table(
            "learning_candidates",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("source_lesson_id", sa.String(), sa.ForeignKey("learning_lessons.id"), nullable=True),
            sa.Column("candidate_type", sa.String(), nullable=False, server_default="lesson"),
            sa.Column("scope", sa.String(), nullable=False, server_default="tenant"),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("abstract_pattern", sa.Text(), nullable=False),
            sa.Column("target_agents_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("evidence_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("anonymization_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("evidence_run_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("evidence_tenant_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(), nullable=False, server_default="candidate"),
            sa.Column("evaluation_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("decision_comment", sa.Text(), nullable=False, server_default=""),
            sa.Column("decided_by_user_id", sa.String(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
        )
        _tenant_indexes("learning_candidates", ["source_lesson_id", "candidate_type", "scope", "status", "created_at"])

    if "learning_evaluations" not in tables:
        op.create_table(
            "learning_evaluations",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("candidate_id", sa.String(), sa.ForeignKey("learning_candidates.id"), nullable=False),
            sa.Column("baseline_version", sa.String(), nullable=False, server_default="2.11.0"),
            sa.Column("candidate_version", sa.String(), nullable=False, server_default="2.12.0"),
            sa.Column("repetitions", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("baseline_metrics_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("candidate_metrics_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("gate_results_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )
        _tenant_indexes("learning_evaluations", ["candidate_id", "status", "created_at"])

    if "learning_policies" not in tables:
        op.create_table(
            "learning_policies",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("candidate_id", sa.String(), sa.ForeignKey("learning_candidates.id"), nullable=True),
            sa.Column("policy_type", sa.String(), nullable=False),
            sa.Column("version", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="inactive"),
            sa.Column("configuration_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("previous_policy_id", sa.String(), sa.ForeignKey("learning_policies.id"), nullable=True),
            sa.Column("created_by_user_id", sa.String(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("activated_at", sa.DateTime(), nullable=True),
            sa.Column("retired_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("tenant_id", "policy_type", "version", name="uq_learning_policy_version"),
        )
        _tenant_indexes("learning_policies", ["candidate_id", "policy_type", "version", "status", "created_at"])

    bind = op.get_bind()
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
    if bind.dialect.name == "sqlite":
        return
    if "global_learning_evidence" in _tables():
        op.drop_table("global_learning_evidence")
    for table in reversed(TENANT_TABLES):
        if table in _tables():
            if bind.dialect.name == "postgresql":
                op.execute(f'DROP POLICY IF EXISTS asf_tenant_isolation ON "{table}"')
            op.drop_table(table)
    for name in ["max_output_tokens", "cache_creation_tokens", "cache_read_tokens"]:
        if name in _columns("model_calls"):
            op.drop_column("model_calls", name)
