from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""


class TenantCreate(BaseModel):
    id: Optional[str] = None
    name: str = Field(min_length=1, max_length=160)


class MemberCreate(BaseModel):
    subject: str
    email: str = ""
    name: str = ""
    role: str = "operator"


class ToolPolicyCreate(BaseModel):
    tool_name: str
    server_name: str = ""
    transport: str = "http"
    allowed: bool = True
    constraints: dict = Field(default_factory=dict)


class McpToolCallCreate(BaseModel):
    run_id: str = ""
    arguments: dict = Field(default_factory=dict)


class RunCreate(BaseModel):
    demand: str = Field(min_length=10, max_length=20_000)
    project_id: str = Field(min_length=1)


class EnterpriseRunCreate(BaseModel):
    prompt: str = Field(min_length=10, max_length=20_000)
    project_name: str = Field(min_length=1, max_length=160)
    template: str = "enterprise-saas"
    industry: str = "financial_services"
    quality_profile: str = "regulated_enterprise"
    compliance: List[str] = Field(default_factory=lambda: ["SOC2", "LGPD", "ISO27001"])
    integrations: List[str] = Field(default_factory=lambda: ["SSO/OIDC", "ERP", "Data Warehouse"])
    data_sensitivity: str = "confidential"


class FeedbackCreate(BaseModel):
    run_id: str
    event_id: str = ""
    artifact_id: str = ""
    node_id: str = ""
    rating: int = Field(default=0, ge=-1, le=1)
    comment: str = ""
    feedback_type: str = "general"
    labels: List[str] = Field(default_factory=list)


class HumanDecision(BaseModel):
    comment: str = ""


class BatchRunItemCreate(BaseModel):
    project_id: str = Field(min_length=1)
    demand: str = Field(min_length=10, max_length=20_000)


class BatchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    items: List[BatchRunItemCreate] = Field(min_length=1, max_length=10)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
