from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = "ContractFlow Enterprise"
    description: str = ""


class TenantCreate(BaseModel):
    id: Optional[str] = None
    name: str = "Production Tenant"


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
    demand: str = Field(default="Crie um sistema para gestão de clientes, contratos e faturas.")
    project_id: Optional[str] = None


class EnterpriseRunCreate(BaseModel):
    prompt: str = Field(
        default="Crie um portal enterprise para contratos, aprovações, SLA e auditoria."
    )
    project_name: str = "Enterprise Software Factory Build"
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
    rating: int = 1
    comment: str = ""
    feedback_type: str = "general"
    labels: List[str] = Field(default_factory=list)


class HumanDecision(BaseModel):
    comment: str = ""


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
