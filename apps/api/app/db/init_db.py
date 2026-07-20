from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.auth.dependencies import ensure_tenant
from app.db.session import engine
from app.models import Base


TENANT_TABLES = [
    "programs",
    "projects",
    "contracts",
    "entitlements",
    "component_instances",
    "approvals",
    "ledger_records",
    "audit_projections",
    "gamification_events",
    "scores",
    "prospects",
    "opportunities",
    "briefings",
    "mvp_specs",
    "mvp_runs",
    "ai_activities",
    "agent_recommendations",
    "prompt_versions",
    "prompt_evaluations",
    "commercial_proposals",
    "workflow_definitions",
    "workflow_runs",
    "workflow_node_states",
    "agent_step_executions",
    "execution_units",
    "artifact_fragments",
    "context_builds",
    "content_digests",
    "agent_events",
    "agent_messages",
    "agent_work_items",
    "agent_run_states",
    "artifacts",
    "file_changes",
    "test_reports",
    "requirements",
    "acceptance_criteria",
    "requirement_traces",
    "quality_gates",
    "quality_scores",
    "risk_items",
    "decision_records",
    "homologation_packages",
    "homologation_reports",
    "approval_requests",
    "human_feedback",
    "reward_signals",
    "learning_lessons",
    "learning_signals",
    "learning_candidates",
    "learning_evaluations",
    "learning_policies",
    "global_learning_deployments",
    "agent_memory",
    "batches",
    "batch_items",
    "batch_metrics",
    "workflow_candidates",
    "reusable_templates",
    "knowledge_bases",
    "knowledge_documents",
    "knowledge_chunks",
    "knowledge_queries",
    "model_calls",
    "engagements",
    "engagement_plans",
    "workstreams",
    "service_work_items",
    "service_deliverables",
    "deliverable_revisions",
    "outcome_metrics",
    "agent_definitions",
    "agent_versions",
    "capability_gaps",
    "agent_candidates",
    "agent_evaluations",
    "agent_assignments",
]
PRODUCTION_SCHEMA_REVISION = "0013_aggregate_technical_metrics"


def _add_column_if_missing(table_name: str, column_name: str, ddl: str) -> None:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in columns:
        return
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))


def _upgrade_legacy_schema() -> None:
    for table_name in TENANT_TABLES:
        _add_column_if_missing(table_name, "tenant_id", "VARCHAR DEFAULT 'local-dev'")
    _add_column_if_missing("tenants", "runtime_configuration_json", "JSON DEFAULT '{}'")
    _add_column_if_missing("tenants", "retention_policy_json", "JSON DEFAULT '{}'")
    _add_column_if_missing("audit_logs", "ledger_record_id", "VARCHAR DEFAULT ''")
    _add_column_if_missing("projects", "program_id", "VARCHAR")
    _add_column_if_missing("projects", "scope", "TEXT DEFAULT ''")
    _add_column_if_missing("projects", "owner_user_id", "VARCHAR DEFAULT ''")
    _add_column_if_missing("projects", "status", "VARCHAR DEFAULT 'active'")
    for column_name in ["temporal_workflow_id", "temporal_run_id", "provider"]:
        default = "production-litellm" if column_name == "provider" else ""
        _add_column_if_missing("workflow_runs", column_name, f"VARCHAR DEFAULT '{default}'")
    _add_column_if_missing("workflow_runs", "generation_mode", "VARCHAR DEFAULT 'deterministic_v1' NOT NULL")
    _add_column_if_missing("workflow_runs", "executor_protocol_version", "VARCHAR DEFAULT 'legacy' NOT NULL")
    _add_column_if_missing("workflow_runs", "trace_id", "VARCHAR DEFAULT '' NOT NULL")
    _add_column_if_missing("workflow_runs", "last_heartbeat_at", "DATETIME")
    _add_column_if_missing("workflow_runs", "context_manifest_json", "JSON DEFAULT '{}'")
    _add_column_if_missing("workflow_runs", "ai_budget_usd", "FLOAT DEFAULT 15 NOT NULL")
    _add_column_if_missing("workflow_runs", "ai_cost_usd", "FLOAT DEFAULT 0 NOT NULL")
    _add_column_if_missing("ai_activities", "model_call_id", "VARCHAR")
    _add_column_if_missing("artifacts", "model_call_id", "VARCHAR")
    _add_column_if_missing("artifacts", "step_execution_id", "VARCHAR")
    _add_column_if_missing("file_changes", "model_call_id", "VARCHAR")
    _add_column_if_missing("file_changes", "step_execution_id", "VARCHAR")
    _add_column_if_missing("model_calls", "workflow_node_state_id", "VARCHAR")
    _add_column_if_missing("model_calls", "prompt_version_id", "VARCHAR")
    _add_column_if_missing("model_calls", "model_role", "VARCHAR DEFAULT 'default' NOT NULL")
    _add_column_if_missing("model_calls", "input_hash", "VARCHAR DEFAULT '' NOT NULL")
    _add_column_if_missing("model_calls", "output_hash", "VARCHAR DEFAULT '' NOT NULL")
    _add_column_if_missing("model_calls", "context_refs_json", "JSON DEFAULT '[]' NOT NULL")
    _add_column_if_missing("model_calls", "output_refs_json", "JSON DEFAULT '[]' NOT NULL")
    _add_column_if_missing("model_calls", "cache_read_tokens", "INTEGER DEFAULT 0 NOT NULL")
    _add_column_if_missing("model_calls", "cache_creation_tokens", "INTEGER DEFAULT 0 NOT NULL")
    _add_column_if_missing("model_calls", "execution_unit_id", "VARCHAR")
    _add_column_if_missing("model_calls", "cache_eligible_tokens", "INTEGER DEFAULT 0 NOT NULL")
    _add_column_if_missing("model_calls", "cache_write_tokens", "INTEGER DEFAULT 0 NOT NULL")
    _add_column_if_missing("model_calls", "cache_savings_usd", "FLOAT DEFAULT 0 NOT NULL")
    _add_column_if_missing("model_calls", "prompt_cache_key", "VARCHAR DEFAULT '' NOT NULL")
    _add_column_if_missing("model_calls", "provider_route", "VARCHAR DEFAULT '' NOT NULL")
    _add_column_if_missing("model_calls", "provider_request_id", "VARCHAR DEFAULT '' NOT NULL")
    _add_column_if_missing("model_calls", "finish_reason", "VARCHAR DEFAULT '' NOT NULL")
    _add_column_if_missing("model_calls", "trace_id", "VARCHAR DEFAULT '' NOT NULL")
    _add_column_if_missing("ai_invocations", "cache_eligible_tokens", "INTEGER DEFAULT 0 NOT NULL")
    _add_column_if_missing("ai_invocations", "cache_write_tokens", "INTEGER DEFAULT 0 NOT NULL")
    _add_column_if_missing("ai_invocations", "cache_savings_usd", "FLOAT DEFAULT 0 NOT NULL")
    _add_column_if_missing("ai_invocations", "trace_id", "VARCHAR DEFAULT '' NOT NULL")
    _add_column_if_missing("model_calls", "max_output_tokens", "INTEGER DEFAULT 0 NOT NULL")
    for column_name in ["workflow_id", "activity_id", "model_call_id", "tool_call_id"]:
        _add_column_if_missing("agent_events", column_name, "VARCHAR DEFAULT ''")
    _add_column_if_missing("test_reports", "sandbox_execution_id", "VARCHAR DEFAULT ''")
    _add_column_if_missing("artifacts", "audience", "VARCHAR DEFAULT 'internal' NOT NULL")
    _add_column_if_missing("ledger_records", "tenant_sequence", "INTEGER DEFAULT 0 NOT NULL")
    _backfill_ledger_sequences()


def _backfill_ledger_sequences() -> None:
    inspector = inspect(engine)
    if "ledger_records" not in inspector.get_table_names():
        return
    with engine.begin() as connection:
        tenants = connection.execute(text("SELECT DISTINCT tenant_id FROM ledger_records")).scalars().all()
        for tenant_id in tenants:
            legacy_count = connection.execute(
                text("SELECT COUNT(*) FROM ledger_records WHERE tenant_id = :tenant_id AND tenant_sequence = 0"),
                {"tenant_id": tenant_id},
            ).scalar_one()
            if not legacy_count:
                continue
            rows = connection.execute(
                text(
                    "SELECT id FROM ledger_records WHERE tenant_id = :tenant_id "
                    "ORDER BY created_at ASC, id ASC"
                ),
                {"tenant_id": tenant_id},
            ).scalars().all()
            for sequence, record_id in enumerate(rows, start=1):
                connection.execute(
                    text("UPDATE ledger_records SET tenant_sequence = :sequence WHERE id = :record_id"),
                    {"sequence": sequence, "record_id": record_id},
                )


def init_db() -> None:
    settings = get_settings()
    if settings.runtime_profile == "production":
        required = {
            "tenants",
            "memberships",
            "ledger_records",
            "ledger_heads",
            "command_receipts",
            "workflow_slots",
            "temporal_command_outbox",
            "knowledge_bases",
            "knowledge_documents",
            "knowledge_chunks",
            "knowledge_queries",
            "service_offerings",
            "offering_versions",
            "engagements",
            "service_deliverables",
            "agent_definitions",
        }
        missing = required.difference(inspect(engine).get_table_names())
        if missing:
            raise RuntimeError(f"Database migrations are required; missing tables: {', '.join(sorted(missing))}")
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        if revision != PRODUCTION_SCHEMA_REVISION:
            raise RuntimeError(
                f"Database migration revision {revision or 'missing'} is not supported; expected {PRODUCTION_SCHEMA_REVISION}"
            )
        return

    Base.metadata.create_all(bind=engine)
    _upgrade_legacy_schema()
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        ensure_tenant(db, settings.default_tenant_id, settings.default_tenant_name)
        db.commit()
    finally:
        db.close()
