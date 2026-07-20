import time
import uuid
from typing import Any, Dict, List

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import McpServer, McpToolInvocation, ToolPolicy


class McpPolicyError(PermissionError):
    pass


class McpToolRegistry:
    def list_tools(self, db: Session, tenant_id: str) -> List[Dict[str, Any]]:
        policies = db.query(ToolPolicy).filter_by(tenant_id=tenant_id, allowed=True).order_by(ToolPolicy.tool_name.asc()).all()
        return [
            {
                "tool_name": policy.tool_name,
                "server_name": policy.server_name,
                "transport": policy.transport,
                "constraints": policy.constraints_json,
            }
            for policy in policies
        ]

    def is_allowed(self, db: Session, tenant_id: str, tool_name: str) -> ToolPolicy:
        policy = db.query(ToolPolicy).filter_by(tenant_id=tenant_id, tool_name=tool_name, allowed=True).first()
        if not policy:
            raise McpPolicyError(f"MCP tool is not allowlisted for tenant: {tool_name}")
        return policy


class McpToolExecutor:
    def __init__(self) -> None:
        self.registry = McpToolRegistry()

    def call_tool(
        self,
        db: Session,
        *,
        tenant_id: str,
        run_id: str,
        tool_name: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        start = time.time()
        invocation_id = str(uuid.uuid4())
        output: Dict[str, Any] = {}
        status = "success"
        error = ""
        server_name = ""
        try:
            policy = self.registry.is_allowed(db, tenant_id, tool_name)
            if (policy.constraints_json or {}).get("access_mode") != "read_only":
                raise McpPolicyError("Assisted pilot blocks write-enabled MCP tool policies")
            server_name = policy.server_name
            server = db.query(McpServer).filter_by(tenant_id=tenant_id, name=policy.server_name, enabled=True).first()
            if not server:
                raise McpPolicyError(f"MCP server is not configured or disabled: {policy.server_name}")
            if server.transport not in {"http", "sse"}:
                raise McpPolicyError("Stdio MCP tools must run through the dedicated MCP gateway, not inside the API process")
            output = self._call_http_json_rpc(server.endpoint, tool_name, payload)
            return {"id": invocation_id, "output": output}
        except Exception as exc:
            status = "failed"
            error = str(exc)
            raise
        finally:
            db.add(
                McpToolInvocation(
                    id=invocation_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    server_name=server_name,
                    tool_name=tool_name,
                    input_json=payload,
                    output_json=output,
                    status=status,
                    error=error,
                    duration_seconds=round(time.time() - start, 3),
                )
            )
            db.flush()

    def _call_http_json_rpc(self, endpoint: str, tool_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        settings = get_settings()
        if not endpoint.startswith("https://") and "localhost" not in endpoint and "127.0.0.1" not in endpoint:
            raise McpPolicyError("MCP HTTP/SSE endpoints must use HTTPS outside local development")
        request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": payload},
        }
        response = httpx.post(endpoint, json=request, timeout=settings.mcp_request_timeout_seconds)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise RuntimeError(data["error"])
        return data.get("result", {})
