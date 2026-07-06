import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AgentEvent, WorkflowRun


def emit_event(
    db: Session,
    run_id: str,
    event_type: str,
    summary: str,
    *,
    node_id: str = "",
    phase: str = "",
    agent_name: str = "",
    status: str = "success",
    severity: str = "info",
    payload: Optional[Dict[str, Any]] = None,
    tenant_id: str = "",
    workflow_id: str = "",
    activity_id: str = "",
    model_call_id: str = "",
    tool_call_id: str = "",
) -> AgentEvent:
    resolved_tenant_id = tenant_id
    if not resolved_tenant_id and run_id and run_id != "batch":
        run = db.get(WorkflowRun, run_id)
        if run:
            resolved_tenant_id = run.tenant_id
            workflow_id = workflow_id or run.workflow_id
    if not resolved_tenant_id:
        resolved_tenant_id = get_settings().default_tenant_id
    event = AgentEvent(
        id=str(uuid.uuid4()),
        tenant_id=resolved_tenant_id,
        run_id=run_id,
        node_id=node_id,
        phase=phase,
        agent_name=agent_name,
        event_type=event_type,
        status=status,
        severity=severity,
        summary=summary,
        payload_json=payload or {},
        workflow_id=workflow_id,
        activity_id=activity_id,
        model_call_id=model_call_id,
        tool_call_id=tool_call_id,
    )
    db.add(event)
    db.flush()
    return event
