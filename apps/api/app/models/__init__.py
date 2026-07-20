from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, JSON, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, text
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
    runtime_configuration_json: Mapped[dict] = mapped_column(JSON, default=dict)
    retention_policy_json: Mapped[dict] = mapped_column(JSON, default=dict)
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
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    permissions_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),)

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
    ledger_record_id: Mapped[str] = mapped_column(String, default="", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    sponsor: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    start_date: Mapped[str] = mapped_column(String, default="")
    target_end_date: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), default="local-dev", index=True)
    program_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("programs.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[str] = mapped_column(Text, default="")
    owner_user_id: Mapped[str] = mapped_column(String, default="", index=True)
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (UniqueConstraint("tenant_id", "contract_number", name="uq_contract_tenant_number"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    contract_number: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="draft", index=True)
    valid_from: Mapped[str] = mapped_column(String, default="")
    valid_until: Mapped[str] = mapped_column(String, default="")
    commercial_metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    scope_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ComponentDefinition(Base):
    __tablename__ = "component_definitions"
    __table_args__ = (UniqueConstraint("code", "version", name="uq_component_definition_code_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str] = mapped_column(String, default="1.0", index=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    prerequisites_json: Mapped[list] = mapped_column(JSON, default=list)
    default_blueprint_ref: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Entitlement(Base):
    __tablename__ = "entitlements"
    __table_args__ = (UniqueConstraint("tenant_id", "contract_id", "component_code", name="uq_entitlement_contract_component"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    contract_id: Mapped[str] = mapped_column(String, ForeignKey("contracts.id"), index=True)
    component_definition_id: Mapped[str] = mapped_column(String, ForeignKey("component_definitions.id"), index=True)
    component_code: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="granted", index=True)
    valid_from: Mapped[str] = mapped_column(String, default="")
    valid_until: Mapped[str] = mapped_column(String, default="")
    limits_json: Mapped[dict] = mapped_column(JSON, default=dict)
    capabilities_json: Mapped[list] = mapped_column(JSON, default=list)
    terms_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ComponentInstance(Base):
    __tablename__ = "component_instances"
    __table_args__ = (UniqueConstraint("tenant_id", "project_id", "component_code", name="uq_component_project_code"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), index=True)
    component_definition_id: Mapped[str] = mapped_column(String, ForeignKey("component_definitions.id"), index=True)
    entitlement_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("entitlements.id"), nullable=True, index=True)
    component_code: Mapped[str] = mapped_column(String, index=True)
    component_version: Mapped[str] = mapped_column(String, default="1.0")
    blueprint_ref: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="draft", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    health: Mapped[float] = mapped_column(Float, default=0.0)
    current_phase: Mapped[str] = mapped_column(String, default="")
    limits_consumed_json: Mapped[dict] = mapped_column(JSON, default=dict)
    milestones_json: Mapped[list] = mapped_column(JSON, default=list)
    tasks_json: Mapped[list] = mapped_column(JSON, default=list)
    blocked_reason: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(nullable=True)
    completed_at: Mapped[datetime] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String, index=True)
    resource_id: Mapped[str] = mapped_column(String, index=True)
    approver_user_id: Mapped[str] = mapped_column(String, default="", index=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    due_date: Mapped[str] = mapped_column(String, default="")
    decision: Mapped[str] = mapped_column(String, default="")
    comments: Mapped[str] = mapped_column(Text, default="")
    impact_json: Mapped[dict] = mapped_column(JSON, default=dict)
    decided_at: Mapped[datetime] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class LedgerRecord(Base):
    __tablename__ = "ledger_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "tenant_sequence", name="uq_ledger_tenant_sequence"),
        Index(
            "uq_ledger_tenant_idempotency",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key <> ''"),
            sqlite_where=text("idempotency_key <> ''"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    aggregate_type: Mapped[str] = mapped_column(String, index=True)
    aggregate_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    actor_user_id: Mapped[str] = mapped_column(String, default="", index=True)
    correlation_id: Mapped[str] = mapped_column(String, default="", index=True)
    causation_id: Mapped[str] = mapped_column(String, default="", index=True)
    idempotency_key: Mapped[str] = mapped_column(String, default="", index=True)
    tenant_sequence: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    previous_hash: Mapped[str] = mapped_column(String, default="")
    integrity_hash: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class LedgerHead(Base):
    __tablename__ = "ledger_heads"

    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_hash: Mapped[str] = mapped_column(String, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class CommandReceipt(Base):
    __tablename__ = "command_receipts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "command_name", "idempotency_key", name="uq_command_receipt"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    command_name: Mapped[str] = mapped_column(String, index=True)
    idempotency_key: Mapped[str] = mapped_column(String, index=True)
    request_hash: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="started", index=True)
    resource_type: Mapped[str] = mapped_column(String, default="")
    resource_id: Mapped[str] = mapped_column(String, default="", index=True)
    response_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    lease_expires_at: Mapped[datetime] = mapped_column(nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(nullable=True)


class WorkflowSlot(Base):
    __tablename__ = "workflow_slots"

    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), primary_key=True)
    slot_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    heartbeat_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    lease_expires_at: Mapped[datetime] = mapped_column(nullable=True, index=True)


class TemporalCommandOutbox(Base):
    """Global orchestration control record; customer content stays on WorkflowRun.

    This table intentionally has no PostgreSQL RLS policy so the shared Temporal
    dispatcher can claim commands across tenants. Dispatch then switches to the
    command tenant before loading the owning run or writing ledger evidence.
    """

    __tablename__ = "temporal_command_outbox"
    __table_args__ = (
        UniqueConstraint("deduplication_key", name="uq_temporal_command_outbox_deduplication"),
        Index("ix_temporal_command_outbox_dispatch", "status", "next_attempt_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    command_type: Mapped[str] = mapped_column(String, index=True)
    workflow_id: Mapped[str] = mapped_column(String, index=True)
    signal_name: Mapped[str] = mapped_column(String, default="")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    deduplication_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(nullable=True, index=True)
    next_attempt_at: Mapped[datetime] = mapped_column(nullable=True, index=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime] = mapped_column(nullable=True)


class AuditProjection(Base):
    __tablename__ = "audit_projections"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    ledger_record_id: Mapped[str] = mapped_column(String, ForeignKey("ledger_records.id"), index=True)
    actor_user_id: Mapped[str] = mapped_column(String, default="", index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    resource_type: Mapped[str] = mapped_column(String, default="")
    resource_id: Mapped[str] = mapped_column(String, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class GamificationEvent(Base):
    __tablename__ = "gamification_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "ledger_record_id",
            "event_type",
            "user_or_team",
            name="uq_gamification_ledger_event_beneficiary",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    program_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("programs.id"), nullable=True, index=True)
    component_instance_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("component_instances.id"), nullable=True, index=True)
    user_or_team: Mapped[str] = mapped_column(String, default="")
    event_type: Mapped[str] = mapped_column(String, index=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    ledger_record_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("ledger_records.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    scope_type: Mapped[str] = mapped_column(String, index=True)
    scope_id: Mapped[str] = mapped_column(String, index=True)
    metric: Mapped[str] = mapped_column(String, index=True)
    value: Mapped[float] = mapped_column(Float)
    formula_version: Mapped[str] = mapped_column(String, default="project_health@1.0")
    inputs_json: Mapped[dict] = mapped_column(JSON, default=dict)
    explanation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Prospect(Base):
    __tablename__ = "prospects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    company: Mapped[str] = mapped_column(String, default="", index=True)
    sector: Mapped[str] = mapped_column(String, default="")
    contact_email: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, default="manual")
    status: Mapped[str] = mapped_column(String, default="new", index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    prospect_id: Mapped[str] = mapped_column(String, ForeignKey("prospects.id"), index=True)
    program_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("programs.id"), nullable=True, index=True)
    project_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("projects.id"), nullable=True, index=True)
    component_instance_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("component_instances.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="intake", index=True)
    stage: Mapped[str] = mapped_column(String, default="briefing", index=True)
    value_potential: Mapped[float] = mapped_column(Float, default=0.0)
    validation_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String, default="medium")
    priority: Mapped[str] = mapped_column(String, default="medium")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Briefing(Base):
    __tablename__ = "briefings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    opportunity_id: Mapped[str] = mapped_column(String, ForeignKey("opportunities.id"), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    structured_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="structured", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class MvpSpec(Base):
    __tablename__ = "mvp_specs"
    __table_args__ = (UniqueConstraint("tenant_id", "opportunity_id", name="uq_mvp_spec_opportunity"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    opportunity_id: Mapped[str] = mapped_column(String, ForeignKey("opportunities.id"), index=True)
    blueprint_ref: Mapped[str] = mapped_column(String, default="enterprise_saas_crud@1.0")
    stack: Mapped[str] = mapped_column(String, default="FastAPI + Next.js")
    status: Mapped[str] = mapped_column(String, default="scoped", index=True)
    scope_json: Mapped[dict] = mapped_column(JSON, default=dict)
    acceptance_criteria_json: Mapped[list] = mapped_column(JSON, default=list)
    deliverables_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class MvpRun(Base):
    __tablename__ = "mvp_runs"
    __table_args__ = (UniqueConstraint("tenant_id", "opportunity_id", name="uq_mvp_run_opportunity"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    opportunity_id: Mapped[str] = mapped_column(String, ForeignKey("opportunities.id"), index=True)
    mvp_spec_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("mvp_specs.id"), nullable=True, index=True)
    component_instance_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("component_instances.id"), nullable=True, index=True)
    workflow_run_id: Mapped[str] = mapped_column(String, default="", index=True)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_phase: Mapped[str] = mapped_column(String, default="queued")
    preview_url: Mapped[str] = mapped_column(String, default="")
    package_json: Mapped[dict] = mapped_column(JSON, default=dict)
    test_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    quality_gates_json: Mapped[list] = mapped_column(JSON, default=list)
    approved_at: Mapped[datetime] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class AIActivity(Base):
    __tablename__ = "ai_activities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String, index=True)
    resource_id: Mapped[str] = mapped_column(String, index=True)
    agent_name: Mapped[str] = mapped_column(String, index=True)
    activity_type: Mapped[str] = mapped_column(String, index=True)
    prompt_code: Mapped[str] = mapped_column(String, index=True)
    prompt_version: Mapped[str] = mapped_column(String, default="1.0")
    status: Mapped[str] = mapped_column(String, default="completed", index=True)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    ledger_record_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("ledger_records.id"), nullable=True, index=True)
    model_call_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("model_calls.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class AgentRecommendation(Base):
    __tablename__ = "agent_recommendations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String, index=True)
    resource_id: Mapped[str] = mapped_column(String, index=True)
    ai_activity_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("ai_activities.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String)
    recommendation: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String, default="info", index=True)
    status: Mapped[str] = mapped_column(String, default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, default="global", index=True)
    code: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str] = mapped_column(String, default="1.0", index=True)
    name: Mapped[str] = mapped_column(String)
    system_prompt: Mapped[str] = mapped_column(Text)
    output_schema_json: Mapped[dict] = mapped_column(JSON, default=dict)
    examples_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class PromptEvaluation(Base):
    __tablename__ = "prompt_evaluations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, default="global", index=True)
    prompt_version_id: Mapped[str] = mapped_column(String, ForeignKey("prompt_versions.id"), index=True)
    fixture_name: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="passed", index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class CommercialProposal(Base):
    __tablename__ = "commercial_proposals"
    __table_args__ = (UniqueConstraint("tenant_id", "opportunity_id", name="uq_proposal_opportunity"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    opportunity_id: Mapped[str] = mapped_column(String, ForeignKey("opportunities.id"), index=True)
    mvp_run_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("mvp_runs.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, default="draft", index=True)
    scope_json: Mapped[dict] = mapped_column(JSON, default=dict)
    pricing_json: Mapped[dict] = mapped_column(JSON, default=dict)
    content: Mapped[str] = mapped_column(Text)
    next_steps_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
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
    generation_mode: Mapped[str] = mapped_column(String, default="deterministic_v1", index=True)
    executor_protocol_version: Mapped[str] = mapped_column(String, default="legacy", index=True)
    trace_id: Mapped[str] = mapped_column(String, default="", index=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    context_manifest_json: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_budget_usd: Mapped[float] = mapped_column(Float, default=15.0)
    ai_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
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
    run_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("workflow_runs.id"), nullable=True, index=True)
    mvp_run_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("mvp_runs.id"), nullable=True, index=True)
    node_id: Mapped[str] = mapped_column(String, default="")
    artifact_type: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(String, default="internal", index=True)
    evidence_classification: Mapped[str] = mapped_column(String, default="declared", index=True)
    source_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    model_call_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("model_calls.id"), nullable=True, index=True)
    step_execution_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("agent_step_executions.id"), nullable=True, index=True)
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
    model_call_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("model_calls.id"), nullable=True, index=True)
    step_execution_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("agent_step_executions.id"), nullable=True, index=True)
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


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_knowledge_base_tenant_name"),
        UniqueConstraint("tenant_id", "id", name="uq_knowledge_base_tenant_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    retrieval_version: Mapped[str] = mapped_column(String, default="hybrid-hashing-bm25-v1")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "knowledge_base_id",
            "checksum",
            name="uq_knowledge_document_tenant_base_checksum",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_knowledge_document_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_id"],
            ["knowledge_bases.tenant_id", "knowledge_bases.id"],
            name="fk_knowledge_document_tenant_base",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str] = mapped_column(String, default="operator")
    source_ref: Mapped[str] = mapped_column(String, default="")
    content: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String, index=True)
    storage_key: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="ready", index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_user_id: Mapped[str] = mapped_column(String, default="", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_document_index"),
        Index("ix_knowledge_chunk_tenant_base", "tenant_id", "knowledge_base_id"),
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_id"],
            ["knowledge_bases.tenant_id", "knowledge_bases.id"],
            name="fk_knowledge_chunk_tenant_base",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["knowledge_documents.tenant_id", "knowledge_documents.id"],
            name="fk_knowledge_chunk_tenant_document",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String, index=True)
    document_id: Mapped[str] = mapped_column(String, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class KnowledgeQuery(Base):
    __tablename__ = "knowledge_queries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_id"],
            ["knowledge_bases.tenant_id", "knowledge_bases.id"],
            name="fk_knowledge_query_tenant_base",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String, index=True)
    actor_user_id: Mapped[str] = mapped_column(String, default="", index=True)
    question: Mapped[str] = mapped_column(Text)
    question_hash: Mapped[str] = mapped_column(String, index=True)
    answer: Mapped[str] = mapped_column(Text, default="")
    answer_mode: Mapped[str] = mapped_column(String, default="extractive")
    top_k: Mapped[int] = mapped_column(Integer, default=5)
    result_refs_json: Mapped[list] = mapped_column(JSON, default=list)
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
    ai_invocation_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("ai_invocations.id"), nullable=True, index=True)
    # Logical link kept without a database FK to avoid a DDL cycle:
    # execution_units also records the producing model call.
    execution_unit_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    run_id: Mapped[str] = mapped_column(String, default="", index=True)
    agent_name: Mapped[str] = mapped_column(String, default="")
    workflow_node_state_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("workflow_node_states.id"), nullable=True, index=True)
    prompt_version_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("prompt_versions.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String, default="litellm")
    model_name: Mapped[str] = mapped_column(String)
    model_role: Mapped[str] = mapped_column(String, default="default", index=True)
    input_hash: Mapped[str] = mapped_column(String, default="", index=True)
    output_hash: Mapped[str] = mapped_column(String, default="", index=True)
    context_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    output_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    request_json: Mapped[dict] = mapped_column(JSON, default=dict)
    response_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="success")
    error: Mapped[str] = mapped_column(Text, default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_eligible_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_savings_usd: Mapped[float] = mapped_column(Float, default=0.0)
    prompt_cache_key: Mapped[str] = mapped_column(String, default="", index=True)
    provider_route: Mapped[str] = mapped_column(String, default="", index=True)
    provider_request_id: Mapped[str] = mapped_column(String, default="", index=True)
    finish_reason: Mapped[str] = mapped_column(String, default="", index=True)
    trace_id: Mapped[str] = mapped_column(String, default="", index=True)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    retry_classification: Mapped[str] = mapped_column(String, default="", index=True)
    routing_reason: Mapped[str] = mapped_column(Text, default="")
    projected_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AIInvocation(Base):
    """One tenant-scoped logical AI operation, including all provider attempts."""

    __tablename__ = "ai_invocations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_ai_invocation_idempotency"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String, index=True)
    scope_type: Mapped[str] = mapped_column(String, index=True)
    scope_id: Mapped[str] = mapped_column(String, index=True)
    correlation_id: Mapped[str] = mapped_column(String, default="", index=True)
    run_id: Mapped[str] = mapped_column(String, default="", index=True)
    agent_name: Mapped[str] = mapped_column(String, default="", index=True)
    policy_version: Mapped[str] = mapped_column(String, default="2.13.0", index=True)
    routing_policy_version: Mapped[str] = mapped_column(String, default="2.13.0", index=True)
    requested_model_role: Mapped[str] = mapped_column(String, default="default", index=True)
    resolved_model_name: Mapped[str] = mapped_column(String, default="")
    routing_reason: Mapped[str] = mapped_column(Text, default="")
    retry_classification: Mapped[str] = mapped_column(String, default="", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    soft_budget_usd: Mapped[float] = mapped_column(Float, default=0.0)
    hard_budget_usd: Mapped[float] = mapped_column(Float, default=0.0)
    reserved_budget_usd: Mapped[float] = mapped_column(Float, default=0.0)
    projected_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    projected_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    projected_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_eligible_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_savings_usd: Mapped[float] = mapped_column(Float, default=0.0)
    trace_id: Mapped[str] = mapped_column(String, default="", index=True)
    actual_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, index=True)


class AgentStepExecution(Base):
    __tablename__ = "agent_step_executions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "node_id", "iteration", "attempt", name="uq_agent_step_attempt"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    workflow_node_state_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_node_states.id"), index=True)
    model_call_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("model_calls.id"), nullable=True, unique=True, index=True)
    prompt_version_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("prompt_versions.id"), nullable=True, index=True)
    node_id: Mapped[str] = mapped_column(String, index=True)
    phase: Mapped[str] = mapped_column(String, index=True)
    iteration: Mapped[int] = mapped_column(Integer, default=1)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="running", index=True)
    decision: Mapped[str] = mapped_column(String, default="")
    input_hash: Mapped[str] = mapped_column(String, index=True)
    output_hash: Mapped[str] = mapped_column(String, default="", index=True)
    input_manifest_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_manifest_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    finished_at: Mapped[datetime] = mapped_column(nullable=True)


class ExecutionUnit(Base):
    """Smallest durable, idempotent unit of an AI-native node execution."""

    __tablename__ = "execution_units"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "run_id", "node_id", "iteration", "unit_key", "action",
            name="uq_execution_unit_identity",
        ),
        Index("ix_execution_units_run_status", "tenant_id", "run_id", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    workflow_node_state_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("workflow_node_states.id"), nullable=True, index=True
    )
    step_execution_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("agent_step_executions.id"), nullable=True, index=True
    )
    model_call_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("model_calls.id"), nullable=True, index=True)
    node_id: Mapped[str] = mapped_column(String, index=True)
    phase: Mapped[str] = mapped_column(String, default="", index=True)
    iteration: Mapped[int] = mapped_column(Integer, default=1)
    unit_key: Mapped[str] = mapped_column(String, index=True)
    unit_type: Mapped[str] = mapped_column(String, default="atomic", index=True)
    strategy: Mapped[str] = mapped_column(String, default="atomic", index=True)
    action: Mapped[str] = mapped_column(String, default="execute", index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    dependencies_json: Mapped[list] = mapped_column(JSON, default=list)
    targets_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    continuation_count: Mapped[int] = mapped_column(Integer, default=0)
    max_continuations: Mapped[int] = mapped_column(Integer, default=2)
    input_budget_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_budget_tokens: Mapped[int] = mapped_column(Integer, default=0)
    input_hash: Mapped[str] = mapped_column(String, default="", index=True)
    output_hash: Mapped[str] = mapped_column(String, default="", index=True)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    finish_reason: Mapped[str] = mapped_column(String, default="", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    trace_id: Mapped[str] = mapped_column(String, default="", index=True)
    temporal_activity_id: Mapped[str] = mapped_column(String, default="", index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, index=True)


class ArtifactFragment(Base):
    """Immutable model-produced section assembled into a persisted Artifact."""

    __tablename__ = "artifact_fragments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "run_id", "node_id", "iteration", "artifact_name", "section_key", "order_index",
            name="uq_artifact_fragment_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    artifact_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("artifacts.id"), nullable=True, index=True)
    execution_unit_id: Mapped[str] = mapped_column(String, ForeignKey("execution_units.id"), index=True)
    model_call_id: Mapped[str] = mapped_column(String, ForeignKey("model_calls.id"), index=True)
    node_id: Mapped[str] = mapped_column(String, index=True)
    iteration: Mapped[int] = mapped_column(Integer, default=1)
    artifact_name: Mapped[str] = mapped_column(String, index=True)
    artifact_type: Mapped[str] = mapped_column(String, default="markdown")
    audience: Mapped[str] = mapped_column(String, default="internal", index=True)
    section_key: Mapped[str] = mapped_column(String, index=True)
    section_title: Mapped[str] = mapped_column(String, default="")
    order_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[list] = mapped_column(JSON, default=list)
    checksum: Mapped[str] = mapped_column(String, index=True)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ContextBuild(Base):
    """Auditable record of what one agent received and what was discarded."""

    __tablename__ = "context_builds"
    __table_args__ = (
        UniqueConstraint("tenant_id", "step_execution_id", name="uq_context_build_step"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    ai_invocation_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("ai_invocations.id"), nullable=True, index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    step_execution_id: Mapped[str] = mapped_column(String, ForeignKey("agent_step_executions.id"), index=True)
    node_id: Mapped[str] = mapped_column(String, index=True)
    policy_version: Mapped[str] = mapped_column(String, index=True)
    input_budget_tokens: Mapped[int] = mapped_column(Integer)
    estimated_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    selected_tokens: Mapped[int] = mapped_column(Integer, default=0)
    discarded_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cited_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cited_references_json: Mapped[list] = mapped_column(JSON, default=list)
    selected_references_json: Mapped[list] = mapped_column(JSON, default=list)
    discarded_references_json: Mapped[list] = mapped_column(JSON, default=list)
    selection_reasons_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ContentDigest(Base):
    """Tenant-private checksum cache for stable summaries and digests."""

    __tablename__ = "content_digests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_kind", "checksum", name="uq_content_digest_tenant_checksum"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    source_kind: Mapped[str] = mapped_column(String, index=True)
    source_id: Mapped[str] = mapped_column(String, index=True)
    checksum: Mapped[str] = mapped_column(String, index=True)
    digest: Mapped[str] = mapped_column(Text)
    original_tokens: Mapped[int] = mapped_column(Integer, default=0)
    digest_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class GlobalLearningEvidence(Base):
    """Cross-tenant corroboration containing pseudonyms and hashes only."""

    __tablename__ = "global_learning_evidence"
    __table_args__ = (
        UniqueConstraint("pattern_fingerprint", "tenant_pseudonym", "run_fingerprint", name="uq_global_learning_evidence"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    pattern_fingerprint: Mapped[str] = mapped_column(String, index=True)
    tenant_pseudonym: Mapped[str] = mapped_column(String, index=True)
    run_fingerprint: Mapped[str] = mapped_column(String, index=True)
    critical_security: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class LearningSignal(Base):
    __tablename__ = "learning_signals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "signal_type", "source_type", "source_id", name="uq_learning_signal_source"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    run_id: Mapped[str] = mapped_column(String, default="", index=True)
    signal_type: Mapped[str] = mapped_column(String, index=True)
    source_type: Mapped[str] = mapped_column(String, index=True)
    source_id: Mapped[str] = mapped_column(String, index=True)
    agent_name: Mapped[str] = mapped_column(String, default="", index=True)
    prompt_version_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("prompt_versions.id"), nullable=True, index=True)
    model_call_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("model_calls.id"), nullable=True, index=True)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    eligible_for_global: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class LearningCandidate(Base):
    __tablename__ = "learning_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    source_lesson_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("learning_lessons.id"), nullable=True, index=True)
    candidate_type: Mapped[str] = mapped_column(String, default="lesson", index=True)
    scope: Mapped[str] = mapped_column(String, default="tenant", index=True)
    title: Mapped[str] = mapped_column(String)
    abstract_pattern: Mapped[str] = mapped_column(Text)
    target_agents_json: Mapped[list] = mapped_column(JSON, default=list)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    anonymization_json: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_run_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_tenant_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="candidate", index=True)
    evaluation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    decision_comment: Mapped[str] = mapped_column(Text, default="")
    decided_by_user_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class LearningEvaluation(Base):
    __tablename__ = "learning_evaluations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(String, ForeignKey("learning_candidates.id"), index=True)
    baseline_version: Mapped[str] = mapped_column(String, default="2.11.0")
    candidate_version: Mapped[str] = mapped_column(String, default="2.13.0")
    repetitions: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    baseline_metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    candidate_metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    gate_results_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class LearningPolicy(Base):
    __tablename__ = "learning_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "policy_type", "version", name="uq_learning_policy_version"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    candidate_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("learning_candidates.id"), nullable=True, index=True)
    policy_type: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="inactive", index=True)
    configuration_json: Mapped[dict] = mapped_column(JSON, default=dict)
    previous_policy_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("learning_policies.id"), nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    activated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    retired_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class GlobalLearningPolicy(Base):
    """Tenant-free registry containing approved abstract, sanitized patterns only."""

    __tablename__ = "global_learning_policies"
    __table_args__ = (
        UniqueConstraint("policy_type", "version", name="uq_global_learning_policy_version"),
        UniqueConstraint("pattern_fingerprint", name="uq_global_learning_pattern_fingerprint"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    policy_type: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    abstract_pattern: Mapped[str] = mapped_column(Text)
    pattern_fingerprint: Mapped[str] = mapped_column(String, index=True)
    target_agents_json: Mapped[list] = mapped_column(JSON, default=list)
    configuration_json: Mapped[dict] = mapped_column(JSON, default=dict)
    sanitization_evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    benchmark_evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_run_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_tenant_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="approved", index=True)
    source_candidate_fingerprint: Mapped[str] = mapped_column(String, default="", index=True)
    approved_by_user_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    retired_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class GlobalLearningDeployment(Base):
    __tablename__ = "global_learning_deployments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "policy_id", "deployment_version", name="uq_global_learning_deployment"),
        Index("ix_global_learning_active", "tenant_id", "policy_type", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    policy_id: Mapped[str] = mapped_column(String, ForeignKey("global_learning_policies.id"), index=True)
    policy_type: Mapped[str] = mapped_column(String, index=True)
    deployment_version: Mapped[int] = mapped_column(Integer, default=1)
    rollout_stage: Mapped[str] = mapped_column(String, default="shadow", index=True)
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    previous_deployment_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("global_learning_deployments.id"), nullable=True
    )
    record_version: Mapped[int] = mapped_column(Integer, default=1)
    deployed_by_user_id: Mapped[str] = mapped_column(String, default="")
    decision_comment: Mapped[str] = mapped_column(Text, default="")
    deployed_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    rolled_back_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class PlatformReadinessEvaluation(Base):
    """Aggregated readiness evidence; never stores tenant content or prompts."""

    __tablename__ = "platform_readiness_evaluations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    policy_version: Mapped[str] = mapped_column(String, index=True)
    protocol_version: Mapped[str] = mapped_column(String, index=True)
    evaluation_type: Mapped[str] = mapped_column(String, default="pilot_ready", index=True)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    window_started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    window_ended_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_hashes_json: Mapped[list] = mapped_column(JSON, default=list)
    blockers_json: Mapped[list] = mapped_column(JSON, default=list)
    approved_by_user_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


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


class ServiceOffering(Base):
    __tablename__ = "service_offerings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String, default="service", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class OfferingVersion(Base):
    __tablename__ = "offering_versions"
    __table_args__ = (UniqueConstraint("offering_id", "version", name="uq_offering_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    offering_id: Mapped[str] = mapped_column(String, ForeignKey("service_offerings.id"), index=True)
    version: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    duration_label: Mapped[str] = mapped_column(String, default="")
    cadence: Mapped[str] = mapped_column(String, default="one_off")
    definition_json: Mapped[dict] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Engagement(Base):
    __tablename__ = "engagements"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    contract_id: Mapped[str] = mapped_column(String, ForeignKey("contracts.id"), index=True)
    offering_version_id: Mapped[str] = mapped_column(String, ForeignKey("offering_versions.id"), index=True)
    program_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("programs.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    owner_user_id: Mapped[str] = mapped_column(String, default="", index=True)
    sponsor: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="draft", index=True)
    start_date: Mapped[str] = mapped_column(String, default="")
    target_end_date: Mapped[str] = mapped_column(String, default="")
    success_criteria_json: Mapped[list] = mapped_column(JSON, default=list)
    service_levels_json: Mapped[dict] = mapped_column(JSON, default=dict)
    health_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    record_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class EngagementPlan(Base):
    __tablename__ = "engagement_plans"
    __table_args__ = (UniqueConstraint("tenant_id", "engagement_id", "version", name="uq_engagement_plan_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    engagement_id: Mapped[str] = mapped_column(String, ForeignKey("engagements.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="draft", index=True)
    plan_json: Mapped[dict] = mapped_column(JSON, default=dict)
    context_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    model_call_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("model_calls.id"), nullable=True, index=True)
    approved_by_user_id: Mapped[str] = mapped_column(String, default="")
    approval_comment: Mapped[str] = mapped_column(Text, default="")
    approved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Workstream(Base):
    __tablename__ = "workstreams"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    engagement_id: Mapped[str] = mapped_column(String, ForeignKey("engagements.id"), index=True)
    project_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("projects.id"), nullable=True, index=True)
    key: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    objective: Mapped[str] = mapped_column(Text, default="")
    owner_user_id: Mapped[str] = mapped_column(String, default="", index=True)
    status: Mapped[str] = mapped_column(String, default="planned", index=True)
    start_date: Mapped[str] = mapped_column(String, default="")
    target_end_date: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ServiceWorkItem(Base):
    __tablename__ = "service_work_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    engagement_id: Mapped[str] = mapped_column(String, ForeignKey("engagements.id"), index=True)
    workstream_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("workstreams.id"), nullable=True, index=True)
    deliverable_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("service_deliverables.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    priority: Mapped[str] = mapped_column(String, default="normal", index=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    blocked_reason: Mapped[str] = mapped_column(Text, default="")
    estimated_effort: Mapped[float] = mapped_column(Float, default=1.0)
    wip_override: Mapped[bool] = mapped_column(Boolean, default=False)
    override_reason: Mapped[str] = mapped_column(Text, default="")
    owner_user_id: Mapped[str] = mapped_column(String, default="", index=True)
    record_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ServiceDeliverable(Base):
    __tablename__ = "service_deliverables"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    engagement_id: Mapped[str] = mapped_column(String, ForeignKey("engagements.id"), index=True)
    workstream_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("workstreams.id"), nullable=True, index=True)
    template_key: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    definition_of_done_json: Mapped[list] = mapped_column(JSON, default=list)
    acceptance_criteria_json: Mapped[list] = mapped_column(JSON, default=list)
    audience: Mapped[str] = mapped_column(String, default="internal", index=True)
    status: Mapped[str] = mapped_column(String, default="planned", index=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    current_revision: Mapped[int] = mapped_column(Integer, default=0)
    record_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    run_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("workflow_runs.id"), nullable=True, index=True)
    homologation_package_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("homologation_packages.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class DeliverableRevision(Base):
    __tablename__ = "deliverable_revisions"
    __table_args__ = (UniqueConstraint("tenant_id", "deliverable_id", "revision", name="uq_deliverable_revision"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    deliverable_id: Mapped[str] = mapped_column(String, ForeignKey("service_deliverables.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="draft", index=True)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    evidence_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    model_call_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("model_calls.id"), nullable=True, index=True)
    created_by_user_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class OutcomeMetric(Base):
    __tablename__ = "outcome_metrics"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    engagement_id: Mapped[str] = mapped_column(String, ForeignKey("engagements.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    unit: Mapped[str] = mapped_column(String, default="")
    baseline_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    provenance: Mapped[str] = mapped_column(String, default="real", index=True)
    source_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    observed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    record_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class AgentTemplate(Base):
    __tablename__ = "agent_templates"
    __table_args__ = (UniqueConstraint("code", "version", name="uq_agent_template_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    purpose: Mapped[str] = mapped_column(Text, default="")
    definition_json: Mapped[dict] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="approved", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AgentDefinition(Base):
    __tablename__ = "agent_definitions"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_agent_definition_tenant_code"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    template_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("agent_templates.id"), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    purpose: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[str] = mapped_column(String, default="tenant", index=True)
    status: Mapped[str] = mapped_column(String, default="approved", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "agent_definition_id", "version", name="uq_agent_definition_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    agent_definition_id: Mapped[str] = mapped_column(String, ForeignKey("agent_definitions.id"), index=True)
    version: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="approved", index=True)
    skill_yaml: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text)
    output_schema_json: Mapped[dict] = mapped_column(JSON, default=dict)
    context_policy_json: Mapped[dict] = mapped_column(JSON, default=dict)
    allowed_tools_json: Mapped[list] = mapped_column(JSON, default=list)
    model_role: Mapped[str] = mapped_column(String, default="reasoning")
    checksum: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class CapabilityGap(Base):
    __tablename__ = "capability_gaps"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    engagement_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("engagements.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String)
    capability: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    gap_type: Mapped[str] = mapped_column(String, default="agent", index=True)
    source_type: Mapped[str] = mapped_column(String, default="operator")
    source_id: Mapped[str] = mapped_column(String, default="", index=True)
    status: Mapped[str] = mapped_column(String, default="detected", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class AgentCandidate(Base):
    __tablename__ = "agent_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    capability_gap_id: Mapped[str] = mapped_column(String, ForeignKey("capability_gaps.id"), index=True)
    agent_definition_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("agent_definitions.id"), nullable=True, index=True)
    proposed_definition_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="draft", index=True)
    model_call_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("model_calls.id"), nullable=True, index=True)
    decision_comment: Mapped[str] = mapped_column(Text, default="")
    decided_by_user_id: Mapped[str] = mapped_column(String, default="")
    decided_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class AgentEvaluation(Base):
    __tablename__ = "agent_evaluations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(String, ForeignKey("agent_candidates.id"), index=True)
    repetitions: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    checks_json: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    results_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class AgentAssignment(Base):
    __tablename__ = "agent_assignments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True)
    engagement_id: Mapped[str] = mapped_column(String, ForeignKey("engagements.id"), index=True)
    workstream_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("workstreams.id"), nullable=True, index=True)
    agent_version_id: Mapped[str] = mapped_column(String, ForeignKey("agent_versions.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    knowledge_base_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    ai_budget_usd: Mapped[float] = mapped_column(Float, default=5.0)
    created_by_user_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
