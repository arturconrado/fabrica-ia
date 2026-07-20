"""Auditable SLO calculations from persisted provider, unit, gate and run evidence."""

from __future__ import annotations

import math
import statistics
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AgentEvent, ExecutionUnit, ModelCall, QualityGate, WorkflowRun, utcnow


def _p95(values: list[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return round(float(ordered[index]), 4)


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    return round(numerator / denominator, 4) if denominator else None


class SLOCalculator:
    WINDOW_DAYS = 30

    def calculate(self, db: Session, *, tenant_id: str) -> dict:
        window_start = utcnow() - timedelta(days=self.WINDOW_DAYS)
        runs = (
            db.query(WorkflowRun)
            .filter(WorkflowRun.tenant_id == tenant_id, WorkflowRun.created_at >= window_start)
            .all()
        )
        run_ids = [run.id for run in runs]
        calls = (
            db.query(ModelCall).filter(ModelCall.tenant_id == tenant_id, ModelCall.run_id.in_(run_ids)).all()
            if run_ids
            else []
        )
        units = (
            db.query(ExecutionUnit).filter(ExecutionUnit.tenant_id == tenant_id, ExecutionUnit.run_id.in_(run_ids)).all()
            if run_ids
            else []
        )
        gates = (
            db.query(QualityGate).filter(QualityGate.tenant_id == tenant_id, QualityGate.run_id.in_(run_ids)).all()
            if run_ids
            else []
        )
        ready_events = (
            db.query(AgentEvent)
            .filter(
                AgentEvent.tenant_id == tenant_id,
                AgentEvent.run_id.in_(run_ids),
                AgentEvent.event_type == "homologation.ready_for_human",
            )
            .all()
            if run_ids
            else []
        )
        ready_by_run = {event.run_id: event for event in ready_events}
        reached_review = [run for run in runs if run.id in ready_by_run or run.status in {"waiting_for_human", "approved", "delivered"}]
        no_intervention = [
            run
            for run in reached_review
            if not any(unit.run_id == run.id and unit.attempt_count > 1 for unit in units)
        ]
        recovered_runs = {
            unit.run_id for unit in units if unit.status == "completed" and unit.attempt_count > 1
        }
        review_durations = [
            (ready_by_run[run.id].created_at - run.started_at).total_seconds()
            for run in reached_review
            if run.id in ready_by_run and run.started_at and ready_by_run[run.id].created_at
        ]
        recovery_durations = [
            (unit.finished_at - unit.started_at).total_seconds()
            for unit in units
            if unit.status == "completed" and unit.attempt_count > 1 and unit.finished_at and unit.started_at
        ]
        per_run_cost = [sum(call.estimated_cost_usd for call in calls if call.run_id == run.id) for run in runs]
        segmented = [run for run in runs if run.executor_protocol_version == "segmented-output-v1"]
        segmented_gates_ok = all(
            len([gate for gate in gates if gate.run_id == run.id]) == 17
            and all(gate.status in {"passed", "pass", "approved"} for gate in gates if gate.run_id == run.id)
            for run in segmented
        ) if segmented else False
        schema_invalid = sum(call.status == "invalid_response" for call in calls)
        model_errors = sum(call.status not in {"success", "invalid_response"} for call in calls)
        timeouts = sum("timeout" in (call.error or "").casefold() for call in calls)
        cache_eligible_calls = [
            call for call in calls if (call.request_json or {}).get("cache_scope") == "global_static"
        ]
        cache_read = sum(call.cache_read_tokens for call in cache_eligible_calls)
        cache_savings = sum(call.cache_savings_usd for call in cache_eligible_calls)
        hrs_values = [float(run.homologation_readiness_score or 0) for run in segmented if run.status in {"waiting_for_human", "approved", "delivered"}]
        confirmed = [unit for unit in units if unit.status == "completed"]
        criteria = {
            "mission_review_without_intervention_gte_90": (_ratio(len(no_intervention), len(runs)) or 0) >= 0.90,
            "mission_review_after_recovery_gte_95": (_ratio(len(reached_review), len(runs)) or 0) >= 0.95,
            "rpo_zero_confirmed_outputs": bool(confirmed) and all(unit.output_hash and unit.model_call_id for unit in confirmed),
            "rto_recovery_p95_lte_300_seconds": (_p95(recovery_durations) or float("inf")) <= 300,
            "review_time_p95_lte_7200_seconds": (_p95(review_durations) or float("inf")) <= 7200,
            "schema_invalid_zero": bool(calls) and schema_invalid == 0,
            "model_call_error_lte_5_percent": bool(calls) and (_ratio(model_errors, len(calls)) or 0) <= 0.05,
            "timeout_lte_3_percent": bool(calls) and (_ratio(timeouts, len(calls)) or 0) <= 0.03,
            "mission_cost_p95_lte_15_usd": (_p95(per_run_cost) or float("inf")) <= 15,
            "all_17_gates_passed": segmented_gates_ok,
            "hrs_minimum_90": bool(hrs_values) and min(hrs_values) >= 90,
            "cache_telemetry_coverage_100_percent": bool(cache_eligible_calls) and all(
                call.cache_eligible_tokens > 0
                and bool(call.prompt_cache_key)
                and "cache_eligible_tokens" in (call.request_json or {})
                for call in cache_eligible_calls
            ),
            "warmed_cache_read_positive": cache_read > 0,
            "reported_cache_savings_positive": cache_savings > 0,
        }
        enough_evidence = len(segmented) >= 1 and bool(calls) and bool(confirmed)
        return {
            "window": {"days": self.WINDOW_DAYS, "started_at": window_start.isoformat(), "as_of": utcnow().isoformat()},
            "status": "meeting_target" if enough_evidence and all(criteria.values()) else "not_meeting_target" if enough_evidence else "insufficient_evidence",
            "metrics": {
                "runs": len(runs),
                "segmented_runs": len(segmented),
                "review_without_intervention_rate": _ratio(len(no_intervention), len(runs)),
                "review_after_recovery_rate": _ratio(len(reached_review), len(runs)),
                "recovered_runs": len(recovered_runs),
                "recovery_p95_seconds": _p95(recovery_durations),
                "time_to_review_p95_seconds": _p95(review_durations),
                "model_calls": len(calls),
                "schema_invalid_rate": _ratio(schema_invalid, len(calls)),
                "model_error_rate": _ratio(model_errors, len(calls)),
                "timeout_rate": _ratio(timeouts, len(calls)),
                "mission_cost_p95_usd": _p95(per_run_cost),
                "mission_cost_median_usd": round(statistics.median(per_run_cost), 8) if per_run_cost else None,
                "hrs_minimum": min(hrs_values) if hrs_values else None,
                "cache_eligible_calls": len(cache_eligible_calls),
                "cache_read_tokens": cache_read,
                "cache_write_tokens": sum(call.cache_write_tokens for call in cache_eligible_calls),
                "cache_savings_usd": round(cache_savings, 8),
            },
            "criteria": criteria,
            "provenance": "calculated_from_tenant_scoped_persisted_technical_evidence",
            "unavailable": {"control_plane_monthly_availability": "requires external uptime time series"},
        }
