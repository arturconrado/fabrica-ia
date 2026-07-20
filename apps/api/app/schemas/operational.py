from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


Provenance = Literal["real", "calculated", "estimated_from_real_usage"]


class MetricValue(BaseModel):
    value: Optional[float] = None
    unit: str
    provenance: Provenance
    as_of: str
    source_refs: list[str] = Field(default_factory=list)


class NextAction(BaseModel):
    kind: str
    title: str
    resource_id: str
    href: str


class TenantSummary(BaseModel):
    tenant_id: str
    tenant_name: str
    tenant_status: str
    role: str
    active_runs: int
    pending_approvals: int
    blocked_items: int
    knowledge_bases: int
    knowledge_documents: int
    hrs: MetricValue
    model_cost_usd: MetricValue
    maturity_level: str
    maturity_xp: int
    next_action: Optional[NextAction] = None
    last_event_at: Optional[str] = None


class PortfolioResponse(BaseModel):
    generated_at: str
    clients: list[TenantSummary]


class OverviewResponse(BaseModel):
    generated_at: str
    client: TenantSummary
    recent_events: list[dict]


class GamificationLevel(BaseModel):
    number: int
    name: str
    threshold: int
    next_threshold: Optional[int] = None
    progress_percent: float


class Achievement(BaseModel):
    code: str
    name: str
    unlocked: bool
    unlocked_at: Optional[str] = None


class GamificationProfileResponse(BaseModel):
    tenant_id: str
    xp_total: int
    level: GamificationLevel
    achievements: list[Achievement]
    recent_events: list[dict]


class ReviewDecision(BaseModel):
    decision: Literal["approve", "reject", "changes_requested"]
    comment: str = Field(default="", max_length=4000)


class ReviewInboxItem(BaseModel):
    id: str
    kind: Literal["run", "service"]
    title: str
    description: str
    status: str
    risk_level: str
    run_id: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    created_at: str
    resolved_at: Optional[str] = None


class ReviewInboxResponse(BaseModel):
    tenant_id: str
    items: list[ReviewInboxItem]


class ReviewRunSummary(BaseModel):
    id: str
    project_id: str
    status: str
    current_phase: str
    current_node: str
    homologation_readiness_score: Optional[float] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class ReviewArtifact(BaseModel):
    id: str
    run_id: Optional[str] = None
    name: str
    artifact_type: str
    content: str
    audience: Literal["reviewer", "client"]
    evidence_classification: str
    created_at: str


class ReviewPackage(BaseModel):
    id: str
    run_id: str
    status: str
    manifest_json: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ReviewBundle(BaseModel):
    run: ReviewRunSummary
    quality_gates: list[dict[str, Any]]
    traceability: list[dict[str, Any]]
    artifacts: list[ReviewArtifact]
    packages: list[ReviewPackage]
    reports: list[dict[str, Any]]


class ReviewItemResponse(BaseModel):
    approval: ReviewInboxItem
    review: Optional[ReviewBundle] = None


class WorkflowPhase(BaseModel):
    id: str
    label: str


class WorkflowNode(BaseModel):
    id: str
    type: str
    phase: str
    skill: Optional[str] = None


class WorkflowEdge(BaseModel):
    from_: str = Field(alias="from", serialization_alias="from")
    to: str
    condition: Any = ""
    max_iterations: Optional[int] = None

    model_config = {"populate_by_name": True}


class WorkflowTopologyResponse(BaseModel):
    workflow_id: str
    version: str
    name: str
    description: str
    ui: dict[str, Any] = Field(default_factory=dict)
    phases: list[WorkflowPhase]
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]


class RunWorkspaceResponse(BaseModel):
    run: dict[str, Any]
    topology: Optional[WorkflowTopologyResponse] = None
    nodes: list[dict[str, Any]]
    agent_states: list[dict[str, Any]]
    work_items: list[dict[str, Any]]
    recent_events: list[dict[str, Any]]
    gates: list[dict[str, Any]]
    homologation: dict[str, list[dict[str, Any]]]
    counts: dict[str, int]
    ai: dict[str, Any] = Field(default_factory=dict)
    step_executions: list[dict[str, Any]] = Field(default_factory=list)
    execution_units: list[dict[str, Any]] = Field(default_factory=list)
    artifact_fragments: list[dict[str, Any]] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)


class TokenReference(BaseModel):
    kind: str
    ref_id: str
    label: str
    checksum: str = ""
    estimated_tokens: int = 0
    reason: str = ""


class TokenContextAnalysis(BaseModel):
    policy_version: Optional[str] = None
    budget_tokens: Optional[int] = None
    selected_tokens: Optional[int] = None
    discarded_tokens: Optional[int] = None
    references: list[TokenReference] = Field(default_factory=list)
    discarded_references: list[dict[str, Any]] = Field(default_factory=list)
    cited_references: list[str] = Field(default_factory=list)
    cited_tokens: Optional[int] = None
    selected_not_cited_tokens: Optional[int] = None


class TokenNodeAnalysis(BaseModel):
    node_id: str
    iteration: int
    attempt: int
    status: str
    model: Optional[str] = None
    model_role: Optional[str] = None
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cache_eligible_tokens: int = 0
    cache_write_tokens: int = 0
    cache_savings_usd: float = 0.0
    max_output_tokens: int
    cost_usd: float
    latency_seconds: float
    ai_invocation_id: Optional[str] = None
    execution_unit_id: Optional[str] = None
    unit_key: Optional[str] = None
    finish_reason: str = ""
    provider_route: str = ""
    retry_classification: str
    routing_reason: str
    projected_cost_usd: float
    output_utilization: Optional[float] = None
    budget: Optional[dict[str, float]] = None
    context: TokenContextAnalysis


class TokenAnalysisResponse(BaseModel):
    run_id: str
    workflow_id: str
    totals: dict[str, int | float]
    provenance: dict[str, str]
    efficiency: dict[str, int | float | None]
    budget: dict[str, float]
    nodes: list[TokenNodeAnalysis]


class AICostGroup(BaseModel):
    key: str
    invocations: int
    attempts: int
    retries: int
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_eligible_tokens: int = 0
    cache_write_tokens: int = 0
    cache_savings_usd: float = 0.0
    projected_cost_usd: float
    actual_cost_usd: float


class AICostTotals(BaseModel):
    invocations: int
    attempts: int
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_eligible_tokens: Optional[int] = None
    cache_write_tokens: Optional[int] = None
    cache_savings_usd: Optional[float] = None
    actual_cost_usd: Optional[float] = None


class AICostAnalysisResponse(BaseModel):
    generated_at: str
    group_by: Literal["tenant", "journey", "operation", "agent", "model", "policy"]
    totals: AICostTotals
    groups: list[AICostGroup]
    provenance: dict[str, str]


class AIInvocationCall(BaseModel):
    id: str
    attempt: int
    status: str
    model: str
    model_role: str
    retry_classification: str
    routing_reason: str
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_eligible_tokens: int = 0
    cache_write_tokens: int = 0
    cache_savings_usd: float = 0.0
    provider_route: str = ""
    provider_request_id: Optional[str] = None
    finish_reason: str = ""
    execution_unit_id: Optional[str] = None
    projected_cost_usd: float
    actual_cost_usd: float
    duration_seconds: float
    context_refs: list[str] = Field(default_factory=list)
    created_at: str


class AIInvocationContext(BaseModel):
    node_id: str
    policy_version: str
    budget_tokens: int
    selected_tokens: int
    discarded_tokens: int
    cited_tokens: int
    selected_references: list[dict[str, Any]] = Field(default_factory=list)
    discarded_references: list[dict[str, Any]] = Field(default_factory=list)
    cited_references: list[str] = Field(default_factory=list)


class AIInvocationDetailResponse(BaseModel):
    id: str
    scope_type: str
    scope_id: str
    correlation_id: str
    run_id: Optional[str] = None
    agent_name: str
    policy_version: str
    routing_policy_version: str
    requested_model_role: str
    resolved_model_name: str
    routing_reason: str
    retry_classification: str
    attempt_count: int
    status: str
    trace_id: Optional[str] = None
    budget: dict[str, float]
    projected: dict[str, int | float]
    actual: dict[str, int | float]
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    calls: list[AIInvocationCall]
    contexts: list[AIInvocationContext]
    redactions: dict[str, str]
