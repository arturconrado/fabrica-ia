import json
import re
import threading
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.providers.object_storage import object_storage

router = APIRouter()
_started_at = time.time()
_request_counts = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
_request_lock = threading.Lock()


def _safe_label_value(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9_:.-]", "_", str(value or "unknown"))


def _direct_technical_metrics(db) -> dict:
    """SQLite/test fallback for the PostgreSQL RLS-safe aggregate function."""

    def by_status(table: str) -> dict[str, int]:
        return {
            str(status or "unknown"): int(count)
            for status, count in db.execute(text(f"SELECT status, COUNT(*) FROM {table} GROUP BY status")).all()
        }

    cache = db.execute(
        text(
            "SELECT COALESCE(SUM(cache_eligible_tokens), 0), COALESCE(SUM(cache_write_tokens), 0), "
            "COALESCE(SUM(cache_read_tokens), 0), COALESCE(SUM(cache_savings_usd), 0), "
            "COALESCE(SUM(prompt_tokens), 0), COALESCE(SUM(completion_tokens), 0), "
            "COALESCE(SUM(estimated_cost_usd), 0) FROM model_calls"
        )
    ).one()
    return {
        "workflow_runs_by_status": by_status("workflow_runs"),
        "execution_units_by_status": by_status("execution_units"),
        "model_calls_by_status": by_status("model_calls"),
        "quality_gates_by_status": by_status("quality_gates"),
        "cache_eligible_tokens": int(cache[0]),
        "cache_write_tokens": int(cache[1]),
        "cache_read_tokens": int(cache[2]),
        "cache_savings_usd": float(cache[3]),
        "prompt_tokens": int(cache[4]),
        "completion_tokens": int(cache[5]),
        "model_cost_usd": float(cache[6]),
        "model_call_errors": int(
            db.execute(text("SELECT COUNT(*) FROM model_calls WHERE status NOT IN ('success', 'completed')")).scalar_one()
        ),
        "model_call_timeouts": int(
            db.execute(text("SELECT COUNT(*) FROM model_calls WHERE lower(COALESCE(error, '')) LIKE '%timeout%'")).scalar_one()
        ),
        "schema_repairs": int(
            db.execute(text("SELECT COUNT(*) FROM model_calls WHERE retry_classification = 'schema_repair'")).scalar_one()
        ),
        "provider_retries": int(
            db.execute(text("SELECT COUNT(*) FROM model_calls WHERE attempt_number > 1")).scalar_one()
        ),
        "checkpoint_recoveries": int(
            db.execute(text("SELECT COUNT(*) FROM agent_events WHERE event_type = 'agent.checkpoint_recovered'")).scalar_one()
        ),
        "rework_events": int(
            db.execute(text("SELECT COUNT(*) FROM agent_events WHERE lower(event_type) LIKE '%rework%'")).scalar_one()
        ),
        "sandbox_timeouts": int(
            db.execute(text("SELECT COUNT(*) FROM sandbox_executions WHERE timed_out = true")).scalar_one()
        ),
        "hrs_average": float(
            db.execute(
                text(
                    "SELECT COALESCE(AVG(homologation_readiness_score), 0) "
                    "FROM workflow_runs WHERE homologation_readiness_score > 0"
                )
            ).scalar_one()
        ),
        "run_duration_p95_seconds": 0.0,
        "node_duration_p95_seconds": 0.0,
        "unit_duration_p95_seconds": 0.0,
        "model_duration_p95_seconds": 0.0,
    }


def _aggregate_technical_metrics(db) -> dict:
    if db.get_bind().dialect.name != "postgresql":
        return _direct_technical_metrics(db)
    value = db.execute(text("SELECT public.asf_aggregate_technical_metrics()")).scalar_one()
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError("Aggregate technical metrics function returned an invalid payload")
    return value


def observe_request(status_code: int) -> None:
    status_class = f"{max(2, min(5, status_code // 100))}xx"
    with _request_lock:
        _request_counts[status_class] = _request_counts.get(status_class, 0) + 1


@router.get("/live")
def live():
    return {"status": "ok", "service": "agentic-software-factory-api"}


@router.get("/ready")
def ready():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        object_storage.probe()
        return {"status": "ready", "database": "ok", "object_storage": "ok" if object_storage.enabled else "not_required"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready", "dependency": "database_or_object_storage"})
    finally:
        db.close()


@router.get("/health")
def health():
    return live()


@router.get("/health/operational")
def operational_status():
    settings = get_settings()
    return {
        "status": "controlled_pilot",
        "runtime_profile": settings.runtime_profile,
        "workflow_backend": settings.workflow_backend,
        "provider_mode": settings.agent_provider,
        "build_mode": "ai_native" if settings.generative_build_enabled else "prebuild_only",
        "generative_build_enabled": settings.generative_build_enabled,
        "regulated_data_allowed": False,
        "contractual_sla": False,
        "rpo_hours": 24,
        "rto_target_hours": 4,
        "limits": {
            "tenants": settings.pilot_max_tenants,
            "users_per_tenant": settings.pilot_max_users_per_tenant,
            "concurrent_workflows": settings.pilot_max_concurrent_workflows,
            "concurrent_workflows_per_tenant": settings.pilot_max_concurrent_workflows_per_tenant,
            "knowledge_bases_per_tenant": settings.knowledge_max_bases_per_tenant,
            "knowledge_documents_per_tenant": settings.knowledge_max_documents_per_tenant,
            "knowledge_chars_per_tenant": settings.knowledge_max_total_chars_per_tenant,
            "knowledge_query_results": settings.knowledge_max_query_results,
        },
    }


@router.get("/metrics", response_class=PlainTextResponse)
def metrics():
    with _request_lock:
        counts = dict(_request_counts)
    lines = [
        "# HELP asf_process_uptime_seconds API process uptime.",
        "# TYPE asf_process_uptime_seconds gauge",
        f"asf_process_uptime_seconds {time.time() - _started_at:.3f}",
        "# HELP asf_http_requests_total HTTP requests grouped by status class.",
        "# TYPE asf_http_requests_total counter",
    ]
    for status_class, value in sorted(counts.items()):
        lines.append(f'asf_http_requests_total{{status_class="{status_class}"}} {value}')
    db = SessionLocal()
    try:
        slot_count = int(db.execute(text("SELECT COUNT(*) FROM workflow_slots")).scalar_one())
        oldest_slot_age = float(
            db.execute(
                text(
                    "SELECT COALESCE(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - MIN(acquired_at))), 0) "
                    "FROM workflow_slots"
                )
            ).scalar_one()
        ) if db.get_bind().dialect.name == "postgresql" else 0.0
        lines.extend(
            [
                "# HELP asf_workflow_slots_in_use Global pilot workflow slots currently in use.",
                "# TYPE asf_workflow_slots_in_use gauge",
                f"asf_workflow_slots_in_use {slot_count}",
                "# HELP asf_oldest_workflow_slot_age_seconds Age of the oldest acquired workflow slot.",
                "# TYPE asf_oldest_workflow_slot_age_seconds gauge",
                f"asf_oldest_workflow_slot_age_seconds {oldest_slot_age:.3f}",
            ]
        )
        outbox_pending = int(
            db.execute(text("SELECT COUNT(*) FROM temporal_command_outbox WHERE status <> 'completed'")).scalar_one()
        )
        outbox_oldest_age = float(
            db.execute(
                text(
                    "SELECT COALESCE(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - MIN(created_at))), 0) "
                    "FROM temporal_command_outbox WHERE status <> 'completed'"
                )
            ).scalar_one()
        ) if db.get_bind().dialect.name == "postgresql" else 0.0
        outbox_max_attempts = int(
            db.execute(
                text("SELECT COALESCE(MAX(attempt_count), 0) FROM temporal_command_outbox WHERE status <> 'completed'")
            ).scalar_one()
        )
        lines.extend(
            [
                "# HELP asf_temporal_outbox_pending Durable Temporal commands waiting for dispatch.",
                "# TYPE asf_temporal_outbox_pending gauge",
                f"asf_temporal_outbox_pending {outbox_pending}",
                "# HELP asf_temporal_outbox_oldest_age_seconds Age of the oldest undispatched Temporal command.",
                "# TYPE asf_temporal_outbox_oldest_age_seconds gauge",
                f"asf_temporal_outbox_oldest_age_seconds {outbox_oldest_age:.3f}",
                "# HELP asf_temporal_outbox_max_attempts Highest attempt count among undispatched Temporal commands.",
                "# TYPE asf_temporal_outbox_max_attempts gauge",
                f"asf_temporal_outbox_max_attempts {outbox_max_attempts}",
            ]
        )
        aggregate = _aggregate_technical_metrics(db)
        aggregate_specs = [
            ("workflow_runs_by_status", "asf_workflow_runs_total", "Persisted workflow runs by status."),
            ("execution_units_by_status", "asf_execution_units_total", "Durable output units by status."),
            ("model_calls_by_status", "asf_model_calls_total", "Persisted provider calls by status."),
            ("quality_gates_by_status", "asf_quality_gates_total", "Deterministic quality gates by status."),
        ]
        for aggregate_key, metric_name, help_text in aggregate_specs:
            lines.extend([f"# HELP {metric_name} {help_text}", f"# TYPE {metric_name} gauge"])
            for status, value in sorted((aggregate.get(aggregate_key) or {}).items()):
                safe_status = _safe_label_value(status)
                lines.append(f'{metric_name}{{status="{safe_status}"}} {int(value)}')
        lines.extend(
            [
                "# HELP asf_prompt_cache_tokens_total Provider-reported prompt cache token telemetry.",
                "# TYPE asf_prompt_cache_tokens_total gauge",
                f'asf_prompt_cache_tokens_total{{kind="eligible"}} {int(aggregate.get("cache_eligible_tokens") or 0)}',
                f'asf_prompt_cache_tokens_total{{kind="write"}} {int(aggregate.get("cache_write_tokens") or 0)}',
                f'asf_prompt_cache_tokens_total{{kind="read"}} {int(aggregate.get("cache_read_tokens") or 0)}',
                "# HELP asf_prompt_cache_savings_usd Provider-reported prompt cache savings.",
                "# TYPE asf_prompt_cache_savings_usd gauge",
                f'asf_prompt_cache_savings_usd {float(aggregate.get("cache_savings_usd") or 0):.8f}',
                "# HELP asf_model_tokens_total Persisted model tokens without tenant labels.",
                "# TYPE asf_model_tokens_total gauge",
                f'asf_model_tokens_total{{kind="prompt"}} {int(aggregate.get("prompt_tokens") or 0)}',
                f'asf_model_tokens_total{{kind="completion"}} {int(aggregate.get("completion_tokens") or 0)}',
                "# HELP asf_model_cost_usd_total Persisted model cost without tenant labels.",
                "# TYPE asf_model_cost_usd_total gauge",
                f'asf_model_cost_usd_total {float(aggregate.get("model_cost_usd") or 0):.8f}',
                "# HELP asf_ai_runtime_events_total Aggregate failures, repairs, retries and recoveries.",
                "# TYPE asf_ai_runtime_events_total gauge",
                f'asf_ai_runtime_events_total{{kind="model_error"}} {int(aggregate.get("model_call_errors") or 0)}',
                f'asf_ai_runtime_events_total{{kind="timeout"}} {int(aggregate.get("model_call_timeouts") or 0)}',
                f'asf_ai_runtime_events_total{{kind="schema_repair"}} {int(aggregate.get("schema_repairs") or 0)}',
                f'asf_ai_runtime_events_total{{kind="provider_retry"}} {int(aggregate.get("provider_retries") or 0)}',
                f'asf_ai_runtime_events_total{{kind="checkpoint_recovery"}} {int(aggregate.get("checkpoint_recoveries") or 0)}',
                f'asf_ai_runtime_events_total{{kind="rework"}} {int(aggregate.get("rework_events") or 0)}',
                f'asf_ai_runtime_events_total{{kind="sandbox_timeout"}} {int(aggregate.get("sandbox_timeouts") or 0)}',
                "# HELP asf_operation_duration_p95_seconds Persisted p95 operation duration.",
                "# TYPE asf_operation_duration_p95_seconds gauge",
                f'asf_operation_duration_p95_seconds{{scope="run"}} {float(aggregate.get("run_duration_p95_seconds") or 0):.4f}',
                f'asf_operation_duration_p95_seconds{{scope="node"}} {float(aggregate.get("node_duration_p95_seconds") or 0):.4f}',
                f'asf_operation_duration_p95_seconds{{scope="unit"}} {float(aggregate.get("unit_duration_p95_seconds") or 0):.4f}',
                f'asf_operation_duration_p95_seconds{{scope="model_call"}} {float(aggregate.get("model_duration_p95_seconds") or 0):.4f}',
            ]
        )
        lines.extend(
            [
                "# HELP asf_homologation_readiness_score_average Average persisted HRS without tenant labels.",
                "# TYPE asf_homologation_readiness_score_average gauge",
                f'asf_homologation_readiness_score_average {float(aggregate.get("hrs_average") or 0):.4f}',
            ]
        )
    finally:
        db.close()
    backup_dir = get_settings().backup_dir
    if backup_dir:
        root = Path(backup_dir)
        datasets = {
            "factory": list(root.glob("factory-*.dump")),
            "temporal": list((root / "temporal").glob("temporal-*.dump")),
            "keycloak": list((root / "keycloak").glob("keycloak-*.dump")),
            "filesystem": list((root / "filesystem").glob("api-*.tar.gz")),
            "minio": [path for path in (root / "minio").glob("*") if path.is_dir()],
            "offsite": [root / ".offsite-last-success"] if (root / ".offsite-last-success").exists() else [],
        }
        lines.extend(
            [
                "# HELP asf_backup_newest_age_seconds Age of the newest validated local or offsite backup marker.",
                "# TYPE asf_backup_newest_age_seconds gauge",
            ]
        )
        now = time.time()
        for dataset, paths in datasets.items():
            age = now - max((path.stat().st_mtime for path in paths), default=0.0) if paths else -1.0
            lines.append(f'asf_backup_newest_age_seconds{{dataset="{dataset}"}} {age:.3f}')
    return "\n".join(lines) + "\n"
