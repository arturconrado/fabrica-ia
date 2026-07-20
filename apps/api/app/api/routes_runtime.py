from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, audit, require_roles
from app.db.session import get_db
from app.models import McpToolInvocation, ModelCall, PlatformReadinessEvaluation, SandboxExecution, ToolPolicy
from app.observability.slo import SLOCalculator
from app.providers.mcp_tool_provider import McpPolicyError, McpToolExecutor, McpToolRegistry
from app.schemas import McpToolCallCreate, ToolPolicyCreate
from app.services.serialization import model_to_dict, models_to_dict

router = APIRouter(tags=["runtime"])
get_current_principal = require_roles("owner", "super_admin", "tenant_admin", "engagement_manager", "consultant", "admin", "operator")


@router.get("/api/v1/operator/slo")
def operator_slo(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return SLOCalculator().calculate(db, tenant_id=principal.tenant_id)


@router.get("/api/v1/admin/platform-readiness")
def platform_readiness(
    principal: Principal = Depends(require_roles("owner", "super_admin")),
    db: Session = Depends(get_db),
):
    evaluations = db.query(PlatformReadinessEvaluation).order_by(PlatformReadinessEvaluation.created_at.desc()).limit(20).all()
    return {
        "live_tenant_slo": SLOCalculator().calculate(db, tenant_id=principal.tenant_id),
        "evaluations": models_to_dict(evaluations),
        "release_definitions": {
            "pilot_ready": "12 comparative runs, five isolated tenants, two delivered products, cache and recovery evidence",
            "market_ready": "assisted canary meets every persisted SLO and receives human approval",
        },
    }


@router.get("/model-calls")
def model_calls(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return models_to_dict(db.query(ModelCall).filter_by(tenant_id=principal.tenant_id).order_by(ModelCall.created_at.desc()).limit(100).all())


@router.get("/sandbox-executions")
def sandbox_executions(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return models_to_dict(
        db.query(SandboxExecution).filter_by(tenant_id=principal.tenant_id).order_by(SandboxExecution.created_at.desc()).limit(100).all()
    )


@router.get("/runs/{run_id}/model-calls")
def run_model_calls(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return models_to_dict(
        db.query(ModelCall).filter_by(tenant_id=principal.tenant_id, run_id=run_id).order_by(ModelCall.created_at.desc()).all()
    )


@router.get("/runs/{run_id}/sandbox-executions")
def run_sandbox_executions(run_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return models_to_dict(
        db.query(SandboxExecution)
        .filter_by(tenant_id=principal.tenant_id, run_id=run_id)
        .order_by(SandboxExecution.created_at.desc())
        .all()
    )


@router.get("/mcp/tools")
def mcp_tools(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return McpToolRegistry().list_tools(db, principal.tenant_id)


@router.post("/mcp/tool-policies")
def create_tool_policy(
    payload: ToolPolicyCreate,
    principal: Principal = Depends(require_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    import uuid

    if payload.allowed and payload.constraints.get("access_mode") != "read_only":
        raise HTTPException(status_code=400, detail="Assisted pilot permits only read_only MCP tool policies")
    policy = ToolPolicy(
        id=str(uuid.uuid4()),
        tenant_id=principal.tenant_id,
        tool_name=payload.tool_name,
        transport=payload.transport,
        server_name=payload.server_name,
        allowed=payload.allowed,
        constraints_json=payload.constraints,
    )
    db.add(policy)
    audit(db, principal, "mcp.tool_policy_created", "tool_policy", policy.id, {"tool": payload.tool_name})
    db.commit()
    db.refresh(policy)
    return model_to_dict(policy)


@router.post("/mcp/tools/{tool_name}/call")
def call_mcp_tool(
    tool_name: str,
    payload: McpToolCallCreate,
    principal: Principal = Depends(require_roles("owner", "admin", "operator")),
    db: Session = Depends(get_db),
):
    try:
        result = McpToolExecutor().call_tool(
            db,
            tenant_id=principal.tenant_id,
            run_id=payload.run_id,
            tool_name=tool_name,
            payload=payload.arguments,
        )
        audit(db, principal, "mcp.tool_called", "mcp_tool", tool_name, {"run_id": payload.run_id})
        db.commit()
        return result
    except McpPolicyError as exc:
        audit(db, principal, "mcp.tool_denied", "mcp_tool", tool_name, {"run_id": payload.run_id, "reason": str(exc)})
        db.commit()
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/mcp/invocations")
def mcp_invocations(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return models_to_dict(
        db.query(McpToolInvocation).filter_by(tenant_id=principal.tenant_id).order_by(McpToolInvocation.created_at.desc()).limit(100).all()
    )
