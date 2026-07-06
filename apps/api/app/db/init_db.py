from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.auth.dependencies import ensure_tenant
from app.db.session import engine
from app.models import Base


TENANT_TABLES = [
    "projects",
    "workflow_definitions",
    "workflow_runs",
    "workflow_node_states",
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
    "agent_memory",
    "batches",
    "batch_items",
    "batch_metrics",
    "workflow_candidates",
    "reusable_templates",
]


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
    for column_name in ["temporal_workflow_id", "temporal_run_id", "provider"]:
        default = "production-litellm" if column_name == "provider" else ""
        _add_column_if_missing("workflow_runs", column_name, f"VARCHAR DEFAULT '{default}'")
    for column_name in ["workflow_id", "activity_id", "model_call_id", "tool_call_id"]:
        _add_column_if_missing("agent_events", column_name, "VARCHAR DEFAULT ''")
    _add_column_if_missing("test_reports", "sandbox_execution_id", "VARCHAR DEFAULT ''")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _upgrade_legacy_schema()
    from app.db.session import SessionLocal

    settings = get_settings()
    db = SessionLocal()
    try:
        ensure_tenant(db, settings.default_tenant_id, settings.default_tenant_name)
        db.commit()
    finally:
        db.close()
