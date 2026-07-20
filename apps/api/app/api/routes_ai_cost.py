from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, require_roles
from app.db.session import SessionLocal, get_db, set_tenant_context
from app.models import AIInvocation, ContextBuild, Membership, ModelCall, utcnow
from app.providers.cost_governor import invocation_to_dict
from app.schemas.operational import AICostAnalysisResponse, AIInvocationDetailResponse


OPERATIONAL_ROLES = (
    "owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator",
)
router = APIRouter(prefix="/api/v1", tags=["ai-cost"])


def _query_invocations(
    db: Session,
    *,
    tenant_id: str,
    date_from: Optional[datetime],
    date_to: Optional[datetime],
) -> list[AIInvocation]:
    query = db.query(AIInvocation).filter(AIInvocation.tenant_id == tenant_id)
    if date_from:
        query = query.filter(AIInvocation.created_at >= date_from)
    if date_to:
        query = query.filter(AIInvocation.created_at <= date_to)
    return query.order_by(AIInvocation.created_at.desc()).limit(5000).all()


def _group(invocations: list[AIInvocation], group_by: str) -> list[dict]:
    values: dict[str, list[AIInvocation]] = {}
    for invocation in invocations:
        key = {
            "tenant": invocation.tenant_id,
            "journey": invocation.scope_type,
            "operation": f"{invocation.scope_type}:{invocation.scope_id}",
            "agent": invocation.agent_name,
            "model": invocation.resolved_model_name,
            "policy": invocation.policy_version,
        }[group_by]
        values.setdefault(key or "unattributed", []).append(invocation)
    return [
        {
            "key": key,
            "invocations": len(rows),
            "attempts": sum(row.attempt_count for row in rows),
            "retries": sum(max(0, row.attempt_count - 1) for row in rows),
            "prompt_tokens": sum(row.prompt_tokens for row in rows),
            "completion_tokens": sum(row.completion_tokens for row in rows),
            "cache_read_tokens": sum(row.cache_read_tokens for row in rows),
            "cache_eligible_tokens": sum(row.cache_eligible_tokens for row in rows),
            "cache_write_tokens": sum(row.cache_write_tokens for row in rows),
            "cache_savings_usd": round(sum(row.cache_savings_usd for row in rows), 8),
            "projected_cost_usd": round(sum(row.projected_cost_usd for row in rows), 8),
            "actual_cost_usd": round(sum(row.actual_cost_usd for row in rows), 8),
        }
        for key, rows in sorted(values.items(), key=lambda item: sum(row.actual_cost_usd for row in item[1]), reverse=True)
    ]


@router.get("/operator/ai-cost-analysis", response_model=AICostAnalysisResponse)
def ai_cost_analysis(
    group_by: Literal["tenant", "journey", "operation", "agent", "model", "policy"] = Query(default="journey"),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    invocations: list[AIInvocation] = []
    if group_by == "tenant":
        memberships = (
            db.query(Membership)
            .filter(Membership.user_id == principal.user_id, Membership.status == "active")
            .execution_options(include_all_tenants=True)
            .all()
        )
        for membership in memberships:
            if membership.role not in OPERATIONAL_ROLES:
                continue
            tenant_db = SessionLocal()
            try:
                set_tenant_context(tenant_db, membership.tenant_id, principal.user_id)
                invocations.extend(
                    _query_invocations(
                        tenant_db,
                        tenant_id=membership.tenant_id,
                        date_from=date_from,
                        date_to=date_to,
                    )
                )
            finally:
                tenant_db.close()
    else:
        invocations = _query_invocations(
            db,
            tenant_id=principal.tenant_id,
            date_from=date_from,
            date_to=date_to,
        )
    return {
        "generated_at": utcnow().isoformat(),
        "group_by": group_by,
        "totals": {
            "invocations": len(invocations),
            "attempts": sum(row.attempt_count for row in invocations),
            "prompt_tokens": sum(row.prompt_tokens for row in invocations) if invocations else None,
            "completion_tokens": sum(row.completion_tokens for row in invocations) if invocations else None,
            "cache_read_tokens": sum(row.cache_read_tokens for row in invocations) if invocations else None,
            "cache_eligible_tokens": sum(row.cache_eligible_tokens for row in invocations) if invocations else None,
            "cache_write_tokens": sum(row.cache_write_tokens for row in invocations) if invocations else None,
            "cache_savings_usd": round(sum(row.cache_savings_usd for row in invocations), 8) if invocations else None,
            "actual_cost_usd": round(sum(row.actual_cost_usd for row in invocations), 8) if invocations else None,
        },
        "groups": _group(invocations, group_by),
        "provenance": {
            "tokens": "real_provider_usage",
            "cost": "real_provider_usage",
            "cache": "real_provider_usage",
            "routing": "persisted_policy_decision",
        },
    }


@router.get("/ai-invocations/{invocation_id}", response_model=AIInvocationDetailResponse)
def ai_invocation_detail(
    invocation_id: str,
    principal: Principal = Depends(require_roles(*OPERATIONAL_ROLES)),
    db: Session = Depends(get_db),
):
    invocation = db.query(AIInvocation).filter_by(id=invocation_id, tenant_id=principal.tenant_id).first()
    if not invocation:
        raise HTTPException(status_code=404, detail="AI invocation not found")
    calls = (
        db.query(ModelCall)
        .filter_by(tenant_id=principal.tenant_id, ai_invocation_id=invocation.id)
        .order_by(ModelCall.created_at.asc())
        .all()
    )
    contexts = db.query(ContextBuild).filter_by(tenant_id=principal.tenant_id, ai_invocation_id=invocation.id).all()
    return {
        **invocation_to_dict(invocation),
        "calls": [
            {
                "id": call.id,
                "attempt": call.attempt_number,
                "status": call.status,
                "model": call.model_name,
                "model_role": call.model_role,
                "retry_classification": call.retry_classification,
                "routing_reason": call.routing_reason,
                "prompt_tokens": call.prompt_tokens,
                "completion_tokens": call.completion_tokens,
                "cache_read_tokens": call.cache_read_tokens,
                "cache_eligible_tokens": call.cache_eligible_tokens,
                "cache_write_tokens": call.cache_write_tokens,
                "cache_savings_usd": call.cache_savings_usd,
                "provider_route": call.provider_route,
                "provider_request_id": call.provider_request_id or None,
                "finish_reason": call.finish_reason,
                "execution_unit_id": call.execution_unit_id,
                "projected_cost_usd": call.projected_cost_usd,
                "actual_cost_usd": call.estimated_cost_usd,
                "duration_seconds": call.duration_seconds,
                "context_refs": call.context_refs_json,
                "created_at": call.created_at.isoformat(),
            }
            for call in calls
        ],
        "contexts": [
            {
                "node_id": context.node_id,
                "policy_version": context.policy_version,
                "budget_tokens": context.input_budget_tokens,
                "selected_tokens": context.selected_tokens,
                "discarded_tokens": context.discarded_tokens,
                "cited_tokens": context.cited_tokens,
                "selected_references": context.selected_references_json,
                "discarded_references": context.discarded_references_json,
                "cited_references": context.cited_references_json,
            }
            for context in contexts
        ],
        "redactions": {"prompts": "not_returned", "responses": "not_returned", "chain_of_thought": "not_stored"},
    }
