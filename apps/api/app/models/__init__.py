from datetime import datetime

from sqlalchemy import Boolean, JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.utcnow()


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class UserAccount(Base):
    __tablename__ = "user_accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, default="", index=True)
    name: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    permissions_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("user_accounts.id"), index=True)
    role: Mapped[str] = mapped_column(String, default="operator")
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    key_hash: Mapped[str] = mapped_column(String)
    scopes_json: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(nullable=True)


class SecretReference(Base):
    __tablename__ = "secret_references"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String, default="env")
    reference: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ToolPolicy(Base):
    __tablename__ = "tool_policies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String, index=True)
    transport: Mapped[str] = mapped_column(String, default="http")
    server_name: Mapped[str] = mapped_column(String, default="")
    allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    constraints_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ModelPolicy(Base):
    __tablename__ = "model_policies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    provider: Mapped[str] = mapped_column(String, default="litellm")
    model_name: Mapped[str] = mapped_column(String)
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    monthly_budget_usd: Mapped[float] = mapped_column(Float, default=0.0)
    constraints_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    actor_user_id: Mapped[str] = mapped_column(String, default="", index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    resource_type: Mapped[str] = mapped_column(String, default="")
    resource_id: Mapped[str] = mapped_column(String, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    workflow_id: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str] = mapped_column(String, default="0.1.0")
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    yaml_path: Mapped[str] = mapped_column(String, default="")
    yaml_content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"))
    workflow_id: Mapped[str] = mapped_column(String)
    demand: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, index=True)
    current_phase: Mapped[str] = mapped_column(String, default="")
    current_node: Mapped[str] = mapped_column(String, default="")
    temporal_workflow_id: Mapped[str] = mapped_column(String, default="", index=True)
    temporal_run_id: Mapped[str] = mapped_column(String, default="")
    provider: Mapped[str] = mapped_column(String, default="production-litellm")
    homologation_readiness_score: Mapped[float] = mapped_column(Float, default=0.0)
    cost_estimate: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class WorkflowNodeState(Base):
    __tablename__ = "workflow_node_states"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    node_id: Mapped[str] = mapped_column(String, index=True)
    phase: Mapped[str] = mapped_column(String)
    agent_name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    iteration: Mapped[int] = mapped_column(Integer, default=1)
    max_iterations: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime] = mapped_column(nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    node_id: Mapped[str] = mapped_column(String, default="", index=True)
    phase: Mapped[str] = mapped_column(String, default="")
    agent_name: Mapped[str] = mapped_column(String, default="")
    event_type: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="success")
    severity: Mapped[str] = mapped_column(String, default="info")
    summary: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    workflow_id: Mapped[str] = mapped_column(String, default="", index=True)
    activity_id: Mapped[str] = mapped_column(String, default="", index=True)
    model_call_id: Mapped[str] = mapped_column(String, default="", index=True)
    tool_call_id: Mapped[str] = mapped_column(String, default="", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    from_agent: Mapped[str] = mapped_column(String, default="", index=True)
    to_agent: Mapped[str] = mapped_column(String, default="", index=True)
    message_type: Mapped[str] = mapped_column(String, default="handoff")
    content: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class AgentWorkItem(Base):
    __tablename__ = "agent_work_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String, index=True)
    node_id: Mapped[str] = mapped_column(String, default="", index=True)
    phase: Mapped[str] = mapped_column(String, default="")
    sop_step: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    blockers_json: Mapped[list] = mapped_column(JSON, default=list)
    input_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    output_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(nullable=True)
    finished_at: Mapped[datetime] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class AgentRunState(Base):
    __tablename__ = "agent_run_states"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="idle", index=True)
    current_sop_step: Mapped[str] = mapped_column(String, default="")
    objective: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    inputs_json: Mapped[list] = mapped_column(JSON, default=list)
    outputs_json: Mapped[list] = mapped_column(JSON, default=list)
    tools_json: Mapped[list] = mapped_column(JSON, default=list)
    last_event_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    node_id: Mapped[str] = mapped_column(String, default="")
    artifact_type: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FileChange(Base):
    __tablename__ = "file_changes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    node_id: Mapped[str] = mapped_column(String, default="")
    file_path: Mapped[str] = mapped_column(String)
    change_type: Mapped[str] = mapped_column(String)
    before_content: Mapped[str] = mapped_column(Text, default="")
    after_content: Mapped[str] = mapped_column(Text, default="")
    diff: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TestReport(Base):
    __tablename__ = "test_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    sandbox_execution_id: Mapped[str] = mapped_column(String, default="", index=True)
    command: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    passed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    timed_out: Mapped[bool] = mapped_column(default=False)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    requirement_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String, default="autonomous")
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AcceptanceCriterion(Base):
    __tablename__ = "acceptance_criteria"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    criterion_id: Mapped[str] = mapped_column(String)
    requirement_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    gherkin: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class RequirementTrace(Base):
    __tablename__ = "requirement_traces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    requirement_id: Mapped[str] = mapped_column(String, index=True)
    file_path: Mapped[str] = mapped_column(String)
    test_name: Mapped[str] = mapped_column(String)
    evidence: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pass")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class QualityGate(Base):
    __tablename__ = "quality_gates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    gate_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    blockers_json: Mapped[list] = mapped_column(JSON, default=list)
    warnings_json: Mapped[list] = mapped_column(JSON, default=list)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class QualityScore(Base):
    __tablename__ = "quality_scores"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    category: Mapped[str] = mapped_column(String)
    score: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float)
    weighted_score: Mapped[float] = mapped_column(Float)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class RiskItem(Base):
    __tablename__ = "risk_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String)
    mitigation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="open")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class DecisionRecord(Base):
    __tablename__ = "decision_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    node_id: Mapped[str] = mapped_column(String, default="")
    title: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    alternatives_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class HomologationPackage(Base):
    __tablename__ = "homologation_packages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    path: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    manifest_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class HomologationReport(Base):
    __tablename__ = "homologation_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    status: Mapped[str] = mapped_column(String)
    score: Mapped[float] = mapped_column(Float)
    blockers_json: Mapped[list] = mapped_column(JSON, default=list)
    risks_json: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    node_id: Mapped[str] = mapped_column(String, default="")
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")
    requested_action: Mapped[str] = mapped_column(String)
    risk_level: Mapped[str] = mapped_column(String, default="medium")
    human_comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    resolved_at: Mapped[datetime] = mapped_column(nullable=True)


class HumanFeedback(Base):
    __tablename__ = "human_feedback"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    event_id: Mapped[str] = mapped_column(String, default="")
    artifact_id: Mapped[str] = mapped_column(String, default="")
    node_id: Mapped[str] = mapped_column(String, default="")
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    feedback_type: Mapped[str] = mapped_column(String, default="general")
    labels_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class RewardSignal(Base):
    __tablename__ = "reward_signals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    feedback_id: Mapped[str] = mapped_column(String, ForeignKey("human_feedback.id"))
    reward_value: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    applies_to: Mapped[str] = mapped_column(String, default="run")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class LearningLesson(Base):
    __tablename__ = "learning_lessons"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    scope: Mapped[str] = mapped_column(String, default="project")
    agent_name: Mapped[str] = mapped_column(String, default="Learning Curator")
    lesson: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="candidate")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    approved_at: Mapped[datetime] = mapped_column(nullable=True)


class AgentMemory(Base):
    __tablename__ = "agent_memory"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    scope: Mapped[str] = mapped_column(String, default="project")
    agent_name: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, default=0)
    average_hrs: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class BatchItem(Base):
    __tablename__ = "batch_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    batch_id: Mapped[str] = mapped_column(String, ForeignKey("batches.id"), index=True)
    project_id: Mapped[str] = mapped_column(String, default="")
    run_id: Mapped[str] = mapped_column(String, default="")
    demand: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String)
    complexity: Mapped[str] = mapped_column(String, default="medium")
    current_phase: Mapped[str] = mapped_column(String, default="")
    hrs: Mapped[float] = mapped_column(Float, default=0.0)
    error_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class BatchMetric(Base):
    __tablename__ = "batch_metrics"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    batch_id: Mapped[str] = mapped_column(String, ForeignKey("batches.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Float)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class WorkflowCandidate(Base):
    __tablename__ = "workflow_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    source_workflow_id: Mapped[str] = mapped_column(String)
    candidate_workflow_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="candidate")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    modification_summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ReusableTemplate(Base):
    __tablename__ = "reusable_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ModelCall(Base):
    __tablename__ = "model_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, default="", index=True)
    agent_name: Mapped[str] = mapped_column(String, default="")
    provider: Mapped[str] = mapped_column(String, default="litellm")
    model_name: Mapped[str] = mapped_column(String)
    request_json: Mapped[dict] = mapped_column(JSON, default=dict)
    response_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="success")
    error: Mapped[str] = mapped_column(Text, default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class McpServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    transport: Mapped[str] = mapped_column(String)
    endpoint: Mapped[str] = mapped_column(String, default="")
    command: Mapped[str] = mapped_column(String, default="")
    args_json: Mapped[list] = mapped_column(JSON, default=list)
    env_json: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class McpToolInvocation(Base):
    __tablename__ = "mcp_tool_invocations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, default="", index=True)
    server_name: Mapped[str] = mapped_column(String, default="")
    tool_name: Mapped[str] = mapped_column(String, index=True)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="success")
    error: Mapped[str] = mapped_column(Text, default="")
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SandboxExecution(Base):
    __tablename__ = "sandbox_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    run_id: Mapped[str] = mapped_column(String, default="", index=True)
    backend: Mapped[str] = mapped_column(String, default="local")
    workspace_ref: Mapped[str] = mapped_column(String)
    command: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    exit_code: Mapped[int] = mapped_column(Integer, default=-1)
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    limits_json: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
