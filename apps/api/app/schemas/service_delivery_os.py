from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class OfferingView(BaseModel):
    id: str
    code: str
    name: str
    category: str
    description: str
    status: str
    version_id: str
    version: str
    duration_label: str
    cadence: str
    definition: dict[str, Any]
    checksum: str


class EngagementCreate(BaseModel):
    contract_id: str
    offering_version_id: str
    program_id: Optional[str] = None
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    sponsor: str = Field(default="", max_length=200)
    start_date: str = ""
    target_end_date: str = ""
    success_criteria: list[str] = Field(default_factory=list, max_length=50)
    service_levels: dict[str, Any] = Field(default_factory=dict)


class PlanGenerateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    adaptation_brief: str = Field(min_length=20, max_length=20_000)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=5)


class GeneratedWorkstream(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=2_000)


class GeneratedDeliverable(BaseModel):
    template_key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=4_000)
    workstream_key: str = Field(default="", max_length=80)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=30)
    definition_of_done: list[str] = Field(min_length=1, max_length=30)
    audience: Literal["internal", "reviewer", "client"] = "reviewer"
    due_offset_days: int = Field(default=14, ge=0, le=365)


class GeneratedEngagementPlan(BaseModel):
    summary: str = Field(min_length=1, max_length=5_000)
    objectives: list[str] = Field(min_length=1, max_length=20)
    stages: list[str] = Field(min_length=1, max_length=30)
    workstreams: list[GeneratedWorkstream] = Field(min_length=1, max_length=20)
    deliverables: list[GeneratedDeliverable] = Field(min_length=1, max_length=80)
    risks: list[str] = Field(default_factory=list, max_length=30)
    next_actions: list[str] = Field(default_factory=list, max_length=20)


class PlanApprovalRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=4_000)
    expected_version: int = Field(ge=1)


class EngagementActivationRequest(BaseModel):
    expected_version: int = Field(ge=1)
    comment: str = Field(min_length=1, max_length=4_000)


class WorkItemTransitionRequest(BaseModel):
    status: Literal["queued", "in_progress", "blocked", "completed", "cancelled"]
    expected_version: int = Field(ge=1)
    reason: str = Field(default="", max_length=4_000)
    override_reason: str = Field(default="", max_length=4_000)


class DeliverableRevisionCreate(BaseModel):
    content: dict[str, Any]
    artifact_refs: list[str] = Field(default_factory=list, max_length=100)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)


class DeliverableGenerateRequest(BaseModel):
    instructions: str = Field(default="", max_length=10_000)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=5)


class GeneratedDeliverableContent(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    executive_summary: str = Field(min_length=1, max_length=5_000)
    content_markdown: str = Field(min_length=1, max_length=80_000)
    evidence_claims: list[str] = Field(default_factory=list, max_length=50)
    risks: list[str] = Field(default_factory=list, max_length=30)
    next_actions: list[str] = Field(default_factory=list, max_length=30)


class DeliverableDecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "changes_requested"]
    comment: str = Field(default="", max_length=4_000)
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_comment(self):
        if self.decision in {"reject", "changes_requested"} and not self.comment.strip():
            raise ValueError("A comment is required for rejection or requested changes")
        return self


class DeliverableDeliveryRequest(BaseModel):
    expected_version: int = Field(ge=1)
    comment: str = Field(min_length=1, max_length=4_000)


class OutcomeMetricCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    unit: str = Field(min_length=1, max_length=80)
    baseline_value: Optional[float] = None
    target_value: Optional[float] = None
    current_value: Optional[float] = None
    provenance: Literal["real", "calculated", "estimated"] = "real"
    source_refs: list[str] = Field(default_factory=list, max_length=50)
    observed_at: Optional[datetime] = None


class OutcomeObservationRequest(BaseModel):
    expected_version: int = Field(ge=1)
    current_value: float
    provenance: Literal["real", "calculated", "estimated"] = "real"
    source_refs: list[str] = Field(default_factory=list, max_length=50)
    observed_at: Optional[datetime] = None
    comment: str = Field(min_length=1, max_length=4_000)


class CapabilityGapCreate(BaseModel):
    engagement_id: Optional[str] = None
    title: str = Field(min_length=1, max_length=240)
    capability: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=8_000)
    gap_type: Literal["agent", "tool"] = "agent"
    source_type: str = Field(default="operator", max_length=80)
    source_id: str = Field(default="", max_length=160)


class AgentCandidateProposal(BaseModel):
    constraints: str = Field(default="", max_length=8_000)


class GeneratedAgentCandidate(BaseModel):
    code: str = Field(min_length=3, max_length=80, pattern=r"^[a-z][a-z0-9_]+$")
    name: str = Field(min_length=3, max_length=160)
    purpose: str = Field(min_length=10, max_length=2_000)
    mission: str = Field(min_length=10, max_length=4_000)
    responsibilities: list[str] = Field(min_length=1, max_length=20)
    allowed_tools: list[str] = Field(default_factory=list, max_length=10)
    forbidden_actions: list[str] = Field(min_length=1, max_length=20)
    output_schema: dict[str, Any]
    context_policy: dict[str, Any]
    model_role: Literal["fast", "reasoning", "code"] = "reasoning"
    benchmark_scenarios: list[str] = Field(min_length=1, max_length=10)


class CandidateDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = Field(min_length=1, max_length=4_000)


class AgentAssignmentCreate(BaseModel):
    engagement_id: str
    workstream_id: Optional[str] = None
    agent_version_id: str
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=5)
    ai_budget_usd: float = Field(default=5.0, gt=0, le=15)


class ServicePortfolioClient(BaseModel):
    tenant_id: str
    tenant_name: str
    role: str
    active_engagements: int
    contracted_offerings: int
    deliverables_due: int
    deliverables_at_risk: int
    deliverables_in_review: int
    deliverables_completed: int
    active_work_items: int
    pending_approvals: int
    active_runs: int
    model_cost_usd: Optional[float] = None
    latest_hrs: Optional[float] = None
    next_commitment: Optional[dict[str, Any]] = None


class ServicePortfolioResponse(BaseModel):
    generated_at: datetime
    clients: list[ServicePortfolioClient]


class CapacityResponse(BaseModel):
    generated_at: datetime
    global_limit: int
    active_total: int
    available_slots: int
    over_capacity: bool
    per_tenant_limit: int
    tenants: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
