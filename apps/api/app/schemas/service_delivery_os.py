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
    version_status: Literal["candidate", "active", "superseded", "rejected"]
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
    dependency_engagement_ids: list[str] = Field(default_factory=list, max_length=20)


class PlanGenerateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    adaptation_brief: str = Field(min_length=20, max_length=20_000)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=5)


class GeneratedWorkstream(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=2_000)


class GeneratedGuidance(BaseModel):
    why_now: str = Field(min_length=1, max_length=400)
    checks: list[str] = Field(default_factory=list, max_length=3)
    risks: list[str] = Field(default_factory=list, max_length=3)
    draft: str = Field(default="", max_length=500)
    confidence: float = Field(default=0.75, ge=0, le=1)


class GeneratedDeliverable(BaseModel):
    template_key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=4_000)
    workstream_key: str = Field(default="", max_length=80)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=30)
    definition_of_done: list[str] = Field(min_length=1, max_length=30)
    audience: Literal["internal", "reviewer", "client"] = "reviewer"
    due_offset_days: int = Field(default=14, ge=0, le=365)
    execution_mode: Literal["agent", "technical_run", "human", "integration"] = "agent"


class GeneratedEngagementPlan(BaseModel):
    summary: str = Field(min_length=1, max_length=5_000)
    objectives: list[str] = Field(min_length=1, max_length=20)
    stages: list[str] = Field(min_length=1, max_length=30)
    workstreams: list[GeneratedWorkstream] = Field(min_length=1, max_length=20)
    deliverables: list[GeneratedDeliverable] = Field(min_length=1, max_length=80)
    risks: list[str] = Field(default_factory=list, max_length=30)
    next_actions: list[str] = Field(default_factory=list, max_length=20)
    guidance: Optional[GeneratedGuidance] = None


class PlanApprovalRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=4_000)
    expected_version: int = Field(ge=1)
    validation_mode: Literal["real", "synthetic"] = "real"


class EngagementActivationRequest(BaseModel):
    expected_version: int = Field(ge=1)
    comment: str = Field(min_length=1, max_length=4_000)


class OfferingVersionDecisionRequest(BaseModel):
    decision: Literal["activate", "reject"]
    comment: str = Field(min_length=1, max_length=4_000)


class PortfolioEvidenceArtifact(BaseModel):
    ref: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mime_type: str = Field(min_length=3, max_length=120)
    size_bytes: int = Field(ge=0)


class PortfolioEvidenceCheck(BaseModel):
    key: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9_]+$")
    passed: bool
    evidence_refs: list[str] = Field(min_length=1, max_length=100)


class PortfolioValidationManifest(BaseModel):
    schema_version: Literal["portfolio-validation-v2"] = "portfolio-validation-v2"
    validation_mode: Literal["real", "synthetic"] = "real"
    environment: Literal["local", "staging", "production"]
    started_at: datetime
    finished_at: datetime
    scenario_ids: list[str] = Field(min_length=1, max_length=200)
    artifacts: list[PortfolioEvidenceArtifact] = Field(min_length=1, max_length=200)
    checks: list[PortfolioEvidenceCheck] = Field(min_length=1, max_length=200)
    metrics: dict[str, Any] = Field(default_factory=dict)
    validator_user_ids: list[str] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_window_and_unique_keys(self):
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        if len(set(self.scenario_ids)) != len(self.scenario_ids):
            raise ValueError("scenario_ids must be unique")
        check_keys = [item.key for item in self.checks]
        if len(set(check_keys)) != len(check_keys):
            raise ValueError("check keys must be unique")
        artifact_refs = [item.ref for item in self.artifacts]
        if len(set(artifact_refs)) != len(artifact_refs):
            raise ValueError("artifact refs must be unique")
        if len(set(self.validator_user_ids)) != len(self.validator_user_ids):
            raise ValueError("validator user ids must be unique")
        return self


class PortfolioValidationEvidenceRequest(BaseModel):
    report_kind: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9_]+$")
    # Retained for wire compatibility. Portfolio 2.0 derives the persisted
    # result from manifest checks and server-side thresholds.
    status: Literal["passed", "failed"]
    content_markdown: str = Field(min_length=20, max_length=100_000)
    evidence_refs: list[str] = Field(min_length=1, max_length=200)
    metrics: dict[str, Any] = Field(default_factory=dict)
    manifest: Optional[PortfolioValidationManifest] = None


class PlatformReadinessEvaluationRequest(BaseModel):
    evaluation_type: Literal["internal_assisted_pilot_ready", "market_ready"]
    portfolio_version: Literal["2.0", "2.1"] = "2.1"
    comment: str = Field(min_length=10, max_length=4_000)


class EngagementDependencyCreate(BaseModel):
    depends_on_engagement_id: str
    dependency_type: Literal["finish_to_start", "shared_output"] = "finish_to_start"
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)


class WorkItemTransitionRequest(BaseModel):
    status: Literal["queued", "in_progress", "blocked", "completed", "cancelled"]
    expected_version: int = Field(ge=1)
    reason: str = Field(default="", max_length=4_000)
    override_reason: str = Field(default="", max_length=4_000)


class ServiceExecutionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    instructions: str = Field(default="", max_length=10_000)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=5)


class ServiceExecutionRetryRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=4_000)


class ServiceExecutionCancelRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=4_000)


class ServiceCycleCreate(BaseModel):
    expected_version: int = Field(ge=1)
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    comment: str = Field(min_length=1, max_length=4_000)


class AcceptanceEvidenceRequest(BaseModel):
    expected_version: int = Field(ge=1)
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    external_constraint: bool = False
    impact: str = Field(default="", max_length=8_000)
    mitigation: str = Field(default="", max_length=8_000)

    @model_validator(mode="after")
    def require_constraint_context(self):
        if self.external_constraint and (not self.impact.strip() or not self.mitigation.strip()):
            raise ValueError("External constraints require impact and mitigation")
        return self


class AcceptanceDecisionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    decision: Literal["approve", "reject", "external_constraint"]
    comment: str = Field(min_length=1, max_length=4_000)
    validation_mode: Literal["real", "synthetic"] = "real"


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
    guidance: Optional[GeneratedGuidance] = None


class DeliverableDecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "changes_requested"]
    comment: str = Field(min_length=1, max_length=4_000)
    expected_version: int = Field(ge=1)
    validation_mode: Literal["real", "synthetic"] = "real"

    @model_validator(mode="after")
    def require_comment(self):
        if self.decision in {"reject", "changes_requested"} and not self.comment.strip():
            raise ValueError("A comment is required for rejection or requested changes")
        return self


class DeliverableDeliveryRequest(BaseModel):
    expected_version: int = Field(ge=1)
    comment: str = Field(min_length=1, max_length=4_000)
    validation_mode: Literal["real", "synthetic"] = "real"


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
