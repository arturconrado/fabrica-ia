import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect


def _alembic(database_url: str, *arguments: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url, "ASF_DATABASE_URL": database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_fresh_migration_upgrade_and_downgrade(tmp_path):
    database = tmp_path / "fresh-migrations.db"
    database_url = f"sqlite:///{database}"
    _alembic(database_url, "upgrade", "head")
    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert {
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
        "ai_invocations",
    }.issubset(tables)
    assert "record_version" in {column["name"] for column in inspect(create_engine(database_url)).get_columns("outcome_metrics")}
    assert {"ai_invocation_id", "attempt_number", "retry_classification", "routing_reason", "projected_cost_usd"}.issubset(
        {column["name"] for column in inspect(create_engine(database_url)).get_columns("model_calls")}
    )

    _alembic(database_url, "downgrade", "base")
    remaining = set(inspect(create_engine(database_url)).get_table_names())
    assert "tenants" not in remaining
    assert "ledger_records" not in remaining


def test_upgrade_from_historical_0001_stamp_installs_missing_tables(tmp_path):
    database = tmp_path / "historical-0001.db"
    database_url = f"sqlite:///{database}"
    _alembic(database_url, "stamp", "0001_initial_production_schema")
    _alembic(database_url, "upgrade", "head")
    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert {
        "ledger_records",
        "artifacts",
        "ledger_heads",
        "command_receipts",
        "workflow_slots",
        "temporal_command_outbox",
        "knowledge_bases",
        "knowledge_documents",
        "knowledge_chunks",
        "knowledge_queries",
        "service_offerings",
        "engagements",
        "service_deliverables",
        "agent_definitions",
    }.issubset(tables)


def test_upgrade_from_operational_0002_adds_temporal_outbox(tmp_path):
    database = tmp_path / "historical-0002.db"
    database_url = f"sqlite:///{database}"
    _alembic(database_url, "upgrade", "0002_operational_hardening")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE temporal_command_outbox")
    _alembic(database_url, "upgrade", "head")
    assert "temporal_command_outbox" in set(inspect(engine).get_table_names())


def test_upgrade_from_temporal_0003_adds_tenant_knowledge_tables(tmp_path):
    database = tmp_path / "historical-0003.db"
    database_url = f"sqlite:///{database}"
    _alembic(database_url, "upgrade", "0003_temporal_transactional_outbox")
    engine = create_engine(database_url)
    for table in ["knowledge_queries", "knowledge_chunks", "knowledge_documents", "knowledge_bases"]:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
    _alembic(database_url, "upgrade", "head")
    assert {
        "knowledge_bases",
        "knowledge_documents",
        "knowledge_chunks",
        "knowledge_queries",
    }.issubset(set(inspect(engine).get_table_names()))
