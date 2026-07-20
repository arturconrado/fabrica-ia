import hashlib
import json
import math
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AIInvocation, ModelCall


AI_SCOPE_TYPES = {
    "factory_run",
    "commercial",
    "opportunity",
    "engagement_plan",
    "service_deliverable",
    "rag_answer",
    "agent_candidate",
    "agent_evaluation",
    "knowledge",
    "system_validation",
}


class CostEnvelope(BaseModel):
    soft_budget_usd: float = Field(default=0.0, ge=0)
    hard_budget_usd: float = Field(default=0.0, ge=0)
    reserved_budget_usd: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_envelope(self) -> "CostEnvelope":
        if self.hard_budget_usd and self.soft_budget_usd > self.hard_budget_usd:
            raise ValueError("soft budget cannot exceed hard budget")
        if self.hard_budget_usd and self.reserved_budget_usd > self.hard_budget_usd:
            raise ValueError("reserved budget cannot exceed hard budget")
        return self


class AIInvocationScope(BaseModel):
    scope_type: Literal[
        "factory_run",
        "commercial",
        "opportunity",
        "engagement_plan",
        "service_deliverable",
        "rag_answer",
        "agent_candidate",
        "agent_evaluation",
        "knowledge",
        "system_validation",
    ]
    scope_id: str = Field(min_length=1, max_length=240)
    correlation_id: str = Field(default="", max_length=240)
    policy_version: str = Field(default="2.13.0", max_length=80)
    routing_reason: str = Field(default="policy_default", max_length=1000)
    retry_classification: str = Field(default="initial", max_length=80)
    attempt_number: int = Field(default=1, ge=1, le=20)
    invocation_id: str = Field(default="", max_length=128)
    envelope: CostEnvelope = Field(default_factory=CostEnvelope)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def logical_id(self, *, tenant_id: str, agent_name: str) -> str:
        if self.invocation_id:
            return self.invocation_id
        raw = json.dumps(
            {
                "tenant_id": tenant_id,
                "scope_type": self.scope_type,
                "scope_id": self.scope_id,
                "correlation_id": self.correlation_id,
                "agent_name": agent_name,
                "policy_version": self.policy_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode()).hexdigest()


class CostProjection(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    provenance: Literal["historical", "unpriced"] = "unpriced"


def estimate_message_tokens(messages: list[dict[str, Any]], schema: dict[str, Any], model_name: str) -> int:
    """Use the configured tokenizer when possible, with a conservative local fallback."""

    serialized = json.dumps({"messages": messages, "schema": schema}, ensure_ascii=False, separators=(",", ":"))
    try:
        from litellm import token_counter

        counted = int(token_counter(model=model_name, text=serialized) or 0)
        if counted > 0:
            return counted
    except Exception:
        pass
    return max(1, math.ceil(len(serialized.encode("utf-8")) / 4))


def _nearest_rank_p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def project_cost(
    db: Session,
    *,
    tenant_id: str,
    agent_name: str,
    model_name: str,
    model_role: str,
    input_tokens: int,
    output_ceiling: int,
) -> CostProjection:
    successful = (
        db.query(ModelCall)
        .filter(
            ModelCall.tenant_id == tenant_id,
            ModelCall.agent_name == agent_name,
            ModelCall.model_role == model_role,
            ModelCall.status == "success",
            ModelCall.prompt_tokens > 0,
            ModelCall.completion_tokens > 0,
        )
        .order_by(ModelCall.created_at.desc())
        .limit(100)
        .all()
    )
    p95 = _nearest_rank_p95([row.completion_tokens for row in successful])
    role_floor = {"fast": 256, "reasoning": 512, "code": 2048}.get(model_role, 256)
    projected_output = min(output_ceiling, max(role_floor, math.ceil(p95 * 1.2))) if p95 else output_ceiling
    priced = [row for row in successful if row.model_name == model_name and row.estimated_cost_usd > 0]
    priced_tokens = sum(row.prompt_tokens + row.completion_tokens for row in priced)
    if not priced_tokens:
        return CostProjection(input_tokens=input_tokens, output_tokens=projected_output)
    unit_cost = sum(row.estimated_cost_usd for row in priced) / priced_tokens
    return CostProjection(
        input_tokens=input_tokens,
        output_tokens=projected_output,
        cost_usd=round((input_tokens + projected_output) * unit_cost, 8),
        provenance="historical",
    )


def invocation_spend(db: Session, *, tenant_id: str, invocation_id: str) -> float:
    return float(
        db.query(func.coalesce(func.sum(ModelCall.estimated_cost_usd), 0.0))
        .filter(ModelCall.tenant_id == tenant_id, ModelCall.ai_invocation_id == invocation_id)
        .scalar()
        or 0.0
    )


def classify_retry(error: Exception | str) -> str:
    text = str(error).casefold()
    if any(term in text for term in ("budget", "tenant isolation", "cross-tenant", "forbidden", "permission")):
        return "budget_or_isolation"
    if any(term in text for term in ("json", "schema", "parse", "validation", "non-object response")):
        return "schema_repair"
    if any(term in text for term in ("timeout", "timed out", "429", "rate limit", "502", "503", "connection")):
        return "transient"
    if any(term in text for term in ("confidence", "citation", "required reference", "hallucination", "missing")):
        return "semantic_escalation"
    return "semantic_escalation"


def invocation_to_dict(invocation: AIInvocation) -> dict[str, Any]:
    return {
        "id": invocation.id,
        "scope_type": invocation.scope_type,
        "scope_id": invocation.scope_id,
        "correlation_id": invocation.correlation_id,
        "run_id": invocation.run_id or None,
        "agent_name": invocation.agent_name,
        "policy_version": invocation.policy_version,
        "routing_policy_version": invocation.routing_policy_version,
        "requested_model_role": invocation.requested_model_role,
        "resolved_model_name": invocation.resolved_model_name,
        "routing_reason": invocation.routing_reason,
        "retry_classification": invocation.retry_classification,
        "attempt_count": invocation.attempt_count,
        "status": invocation.status,
        "budget": {
            "soft_usd": invocation.soft_budget_usd,
            "hard_usd": invocation.hard_budget_usd,
            "reserved_usd": invocation.reserved_budget_usd,
        },
        "projected": {
            "input_tokens": invocation.projected_input_tokens,
            "output_tokens": invocation.projected_output_tokens,
            "cost_usd": invocation.projected_cost_usd,
        },
        "actual": {
            "prompt_tokens": invocation.prompt_tokens,
            "completion_tokens": invocation.completion_tokens,
            "cache_read_tokens": invocation.cache_read_tokens,
            "cache_eligible_tokens": invocation.cache_eligible_tokens,
            "cache_write_tokens": invocation.cache_write_tokens,
            "cache_savings_usd": invocation.cache_savings_usd,
            "cost_usd": invocation.actual_cost_usd,
        },
        "trace_id": invocation.trace_id or None,
        "metadata": invocation.metadata_json,
        "created_at": invocation.created_at.isoformat() if invocation.created_at else None,
        "updated_at": invocation.updated_at.isoformat() if invocation.updated_at else None,
    }
