import json
import inspect
import time
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents.ai_native_contracts import stable_hash
from app.core.config import get_settings
from app.models import AIInvocation, ModelCall, Tenant, WorkflowRun, utcnow
from app.observability.tracing import trace_span
from app.providers.cost_governor import (
    AIInvocationScope,
    CostProjection,
    classify_retry,
    estimate_message_tokens,
    invocation_spend,
    project_cost,
)
from app.providers.model_capabilities import ModelCapabilityError, model_capabilities
from app.service_delivery.ledger import append_ledger_event


class ModelGatewayError(RuntimeError):
    def __init__(self, message: str, *, call_id: str = ""):
        super().__init__(message)
        self.call_id = call_id


_PROVIDER_UNSUPPORTED_SCHEMA_KEYWORDS = {
    "$schema",
    "default",
    "examples",
    "exclusiveMaximum",
    "exclusiveMinimum",
    "format",
    "maxItems",
    "maxLength",
    "maxProperties",
    "maximum",
    "minItems",
    "minLength",
    "minProperties",
    "minimum",
    "multipleOf",
    "pattern",
    "title",
    "uniqueItems",
}


def portable_response_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Return a provider-portable structural schema.

    OpenRouter providers implement different JSON Schema subsets. Limits and
    patterns remain authoritative in the local Pydantic validation, while the
    provider receives only the common structural contract needed to produce
    parseable JSON.
    """

    def sanitize(value: Any) -> Any:
        if isinstance(value, dict):
            sanitized: Dict[str, Any] = {}
            for key, item in value.items():
                if key in _PROVIDER_UNSUPPORTED_SCHEMA_KEYWORDS:
                    continue
                if key == "properties" and isinstance(item, dict):
                    # Property names are domain fields, not JSON Schema
                    # keywords. A field named `title`, for example, must not
                    # disappear when the metadata keyword `title` is removed.
                    sanitized[key] = {property_name: sanitize(property_schema) for property_name, property_schema in item.items()}
                else:
                    sanitized[key] = sanitize(item)
            properties = sanitized.get("properties")
            if sanitized.get("type") == "object" and isinstance(properties, dict) and properties:
                # Gemini requires every declared property to be listed as
                # required; nullable Pydantic fields already carry an anyOf
                # branch for null. Claude also becomes substantially less
                # likely to omit locally-required fields with this shape.
                sanitized["required"] = list(properties)
                sanitized["additionalProperties"] = False
            return sanitized
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        return value

    return sanitize(schema)


def request_timeout_seconds(model_name: str) -> int:
    """Return a bounded timeout suited to the selected model role alias."""

    settings = get_settings()
    if model_name == settings.fast_model:
        return settings.fast_model_request_timeout_seconds
    if model_name == settings.reasoning_model:
        return settings.reasoning_model_request_timeout_seconds
    if model_name == settings.code_model:
        return settings.code_model_request_timeout_seconds
    return settings.model_request_timeout_seconds


def request_max_output_tokens(model_name: str, node_limit: Optional[int] = None) -> int:
    """Return an output ceiling sized for the selected role alias."""

    settings = get_settings()
    if model_name == settings.fast_model:
        role_limit = settings.fast_model_max_output_tokens
    elif model_name == settings.reasoning_model:
        role_limit = settings.reasoning_model_max_output_tokens
    elif model_name == settings.code_model:
        role_limit = settings.code_model_max_output_tokens
    else:
        role_limit = settings.model_max_output_tokens
    return min(role_limit, int(node_limit)) if node_limit and int(node_limit) > 0 else role_limit


class ModelGateway:
    def call(
        self,
        *,
        messages: List[Dict[str, Any]],
        response_schema: Optional[Dict[str, Any]] = None,
        tenant_id: str,
        run_id: str = "",
        agent_name: str = "",
        db: Optional[Session] = None,
        model: str = "",
        model_role: str = "default",
        workflow_node_state_id: str = "",
        execution_unit_id: str = "",
        prompt_version_id: str = "",
        trace_id: str = "",
        input_hash: str = "",
        context_refs: Optional[List[str]] = None,
        max_output_tokens: Optional[int] = None,
        cache_scope: str = "none",
        routing_policy_version: str = "",
        invocation_scope: AIInvocationScope | Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        settings = get_settings()
        model_name = model or settings.model_for_role(model_role)
        start = time.time()
        call_id = str(uuid.uuid4())
        request_hash = input_hash or stable_hash({"messages": messages, "response_schema": response_schema or {}, "model": model_name})
        refs = list(context_refs or [])
        provider_response_schema = portable_response_schema(response_schema) if response_schema else {}
        output_ceiling = request_max_output_tokens(model_name, max_output_tokens)
        try:
            capability = model_capabilities().get(model_name)
        except ModelCapabilityError:
            if settings.runtime_profile.lower() != "test":
                raise
            capability = None
        if invocation_scope is None:
            if settings.runtime_profile.lower() != "test":
                raise ModelGatewayError("An explicit tenant-scoped AI invocation scope is required in operational profiles")
            invocation_scope = AIInvocationScope(
                scope_type="factory_run" if run_id else "system_validation",
                scope_id=run_id or request_hash,
                correlation_id=run_id or request_hash,
                policy_version=routing_policy_version or "test",
                routing_reason="test_compatibility",
            )
        elif not isinstance(invocation_scope, AIInvocationScope):
            invocation_scope = AIInvocationScope.model_validate(invocation_scope)
        invocation_id = invocation_scope.logical_id(tenant_id=tenant_id, agent_name=agent_name)
        input_token_estimate = estimate_message_tokens(messages, provider_response_schema, model_name)
        projection = (
            project_cost(
                db,
                tenant_id=tenant_id,
                agent_name=agent_name,
                model_name=model_name,
                model_role=model_role,
                input_tokens=input_token_estimate,
                output_ceiling=output_ceiling,
            )
            if db is not None
            else CostProjection(input_tokens=input_token_estimate, output_tokens=output_ceiling)
        )
        if db is not None:
            try:
                self._assert_budget(
                    db,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    invocation_id=invocation_id,
                    scope=invocation_scope,
                    projection=projection,
                )
            except ModelGatewayError as exc:
                self._persist_budget_decision(
                    db,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    invocation_id=invocation_id,
                    agent_name=agent_name,
                    model_name=model_name,
                    model_role=model_role,
                    routing_policy_version=routing_policy_version,
                    scope=invocation_scope,
                    projection=projection,
                    context_refs=refs,
                    error=str(exc),
                )
                raise
        cache_mode = capability.effective_cache_mode if capability and cache_scope == "global_static" else "none"
        stable_system_messages = [message for message in messages if message.get("role") == "system"]
        cache_eligible_tokens = (
            estimate_message_tokens(stable_system_messages, provider_response_schema, model_name)
            if cache_scope == "global_static"
            else 0
        )
        prompt_cache_key = (
            stable_hash(
                {
                    "upstream_model": capability.upstream_model if capability else model_name,
                    "prompt_version_id": prompt_version_id,
                    "stable_system_messages": stable_system_messages,
                    "schema_hash": stable_hash(provider_response_schema),
                    "toolset_hash": stable_hash([]),
                }
            )
            if cache_scope == "global_static"
            else ""
        )
        provider_messages = self._cache_marked_messages(messages) if cache_mode == "anthropic_explicit" else messages
        provider_options = {
            "cache_mode": cache_mode,
            "prompt_cache_key": prompt_cache_key if cache_mode == "openai_key" else "",
            "upstream_model": capability.upstream_model if capability else model_name,
        }
        request_json = {
            "messages": messages,
            "response_schema": response_schema or {},
            "provider_response_schema": provider_response_schema,
            "model": model_name,
            "model_role": model_role,
            "input_hash": request_hash,
            "context_refs": refs,
            "max_output_tokens": output_ceiling,
            "cache_scope": cache_scope,
            "cache_mode": cache_mode,
            "cache_eligible_tokens": cache_eligible_tokens,
            "prompt_cache_key": prompt_cache_key,
            "routing_policy_version": routing_policy_version,
            "ai_invocation_id": invocation_id,
            "scope_type": invocation_scope.scope_type,
            "scope_id": invocation_scope.scope_id,
            "attempt_number": invocation_scope.attempt_number,
            "retry_classification": invocation_scope.retry_classification,
            "projected_input_tokens": projection.input_tokens,
            "projected_output_tokens": projection.output_tokens,
            "projected_cost_usd": projection.cost_usd,
            "execution_unit_id": execution_unit_id,
            "trace_id": trace_id,
        }
        status = "success"
        error = ""
        response_json: Dict[str, Any] = {}
        prompt_tokens = 0
        completion_tokens = 0
        cache_read_tokens = 0
        cache_creation_tokens = 0
        cache_write_tokens = 0
        cache_savings_usd = 0.0
        provider_route = ""
        provider_request_id = ""
        finish_reason = ""
        estimated_cost_usd = 0.0
        output_hash = ""
        budget_error = ""
        try:
            call_parameters = inspect.signature(self._call_litellm).parameters
            if "max_output_tokens" in call_parameters:
                kwargs: Dict[str, Any] = {"max_output_tokens": output_ceiling}
                if "provider_options" in call_parameters:
                    kwargs["provider_options"] = provider_options
                response_json = self._call_litellm(model_name, provider_messages, provider_response_schema, **kwargs)
            else:  # Compatibility for test/provider subclasses written for v2.11.
                response_json = self._call_litellm(model_name, provider_messages, provider_response_schema)
            output_hash = stable_hash(response_json)
            parse_error = str(response_json.get("parse_error") or "")
            if parse_error:
                status = "invalid_response"
                error = f"Provider response was not valid JSON: {parse_error}"
                invocation_scope.retry_classification = "schema_repair"
            usage = response_json.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            prompt_details = usage.get("prompt_tokens_details") or {}
            cache_read_tokens = int(
                usage.get("cache_read_input_tokens")
                or usage.get("cached_tokens")
                or prompt_details.get("cached_tokens")
                or 0
            )
            cache_creation_tokens = int(
                usage.get("cache_creation_input_tokens")
                or usage.get("cache_write_input_tokens")
                or usage.get("cache_creation_tokens")
                or 0
            )
            cache_write_tokens = int(
                usage.get("cache_write_input_tokens")
                or usage.get("cache_creation_input_tokens")
                or usage.get("cache_creation_tokens")
                or 0
            )
            cache_savings_usd = float(response_json.get("cache_savings_usd") or usage.get("cache_savings_usd") or 0.0)
            provider_route = str(response_json.get("provider_route") or "")
            provider_request_id = str(response_json.get("provider_request_id") or "")
            finish_reason = str(response_json.get("finish_reason") or "")
            estimated_cost_usd = float(response_json.get("estimated_cost_usd") or 0.0)
            if db is not None:
                budget_error = self._post_call_budget_error(
                    db,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    invocation_id=invocation_id,
                    scope=invocation_scope,
                    call_cost_usd=estimated_cost_usd,
                )
                if budget_error:
                    status = "budget_exceeded"
                    error = budget_error
        except Exception as exc:
            status = "failed"
            error = str(exc)
            if invocation_scope.retry_classification == "initial":
                invocation_scope.retry_classification = classify_retry(exc)
            raise ModelGatewayError(error, call_id=call_id) from exc
        finally:
            if db is not None:
                invocation = self._invocation_record(
                    db,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    invocation_id=invocation_id,
                    agent_name=agent_name,
                    model_name=model_name,
                    model_role=model_role,
                    routing_policy_version=routing_policy_version,
                    scope=invocation_scope,
                    projection=projection,
                    context_refs=refs,
                    status=status,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_eligible_tokens=cache_eligible_tokens,
                    cache_write_tokens=cache_write_tokens,
                    cache_savings_usd=cache_savings_usd,
                    trace_id=trace_id,
                    actual_cost_usd=estimated_cost_usd,
                )
                model_call = ModelCall(
                    id=call_id,
                    tenant_id=tenant_id,
                    ai_invocation_id=invocation_id,
                    execution_unit_id=execution_unit_id or None,
                    run_id=run_id,
                    agent_name=agent_name,
                    workflow_node_state_id=workflow_node_state_id or None,
                    prompt_version_id=prompt_version_id or None,
                    provider="litellm",
                    model_name=model_name,
                    model_role=model_role,
                    input_hash=request_hash,
                    output_hash=output_hash,
                    context_refs_json=refs,
                    output_refs_json=[],
                    request_json=request_json,
                    response_json=response_json,
                    status=status,
                    error=error,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    cache_eligible_tokens=cache_eligible_tokens,
                    cache_write_tokens=cache_write_tokens,
                    cache_savings_usd=cache_savings_usd,
                    prompt_cache_key=prompt_cache_key,
                    provider_route=provider_route,
                    provider_request_id=provider_request_id,
                    finish_reason=finish_reason,
                    trace_id=trace_id,
                    max_output_tokens=output_ceiling,
                    attempt_number=invocation_scope.attempt_number,
                    retry_classification=invocation_scope.retry_classification,
                    routing_reason=invocation_scope.routing_reason,
                    projected_cost_usd=projection.cost_usd,
                    estimated_cost_usd=estimated_cost_usd,
                    duration_seconds=round(time.time() - start, 3),
                )
                # Commercial discovery calls are made before their aggregate is
                # committed. Persist their provider evidence independently so a
                # later output-contract rejection cannot erase usage and cost.
                if not run_id and settings.runtime_profile.lower() != "test":
                    self._persist_independent_call(model_call, invocation)
                else:
                    if db.get(AIInvocation, invocation.id) is None:
                        db.add(invocation)
                    db.add(model_call)
                    db.flush()
                    self._append_invocation_event(db, invocation=invocation, model_call=model_call)
                if run_id and estimated_cost_usd > 0:
                    run = db.query(WorkflowRun).filter_by(id=run_id, tenant_id=tenant_id).first()
                    if run:
                        run.ai_cost_usd = round(float(run.ai_cost_usd or 0.0) + estimated_cost_usd, 8)
                        run.cost_estimate = run.ai_cost_usd
                        db.flush()
        if budget_error:
            raise ModelGatewayError(budget_error, call_id=call_id)
        if status == "invalid_response":
            raise ModelGatewayError(error, call_id=call_id)
        return {"id": call_id, "invocation_id": invocation_id, "model": model_name, "content": response_json}

    @staticmethod
    def _cache_marked_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Mark only the stable global system prompt as provider-cacheable."""

        marked: List[Dict[str, Any]] = []
        for message in messages:
            if message.get("role") == "system" and isinstance(message.get("content"), str):
                marked.append(
                    {
                        **message,
                        "content": [
                            {
                                "type": "text",
                                "text": message["content"],
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                )
            else:
                marked.append(dict(message))
        return marked

    @staticmethod
    def _persist_independent_call(model_call: ModelCall, invocation: AIInvocation) -> None:
        from app.db.session import SessionLocal, set_tenant_context

        audit_db = SessionLocal()
        try:
            set_tenant_context(audit_db, model_call.tenant_id, "model-gateway")
            persisted = audit_db.get(AIInvocation, invocation.id)
            if persisted:
                ModelGateway._merge_invocation(persisted, invocation)
                invocation = persisted
            else:
                audit_db.add(invocation)
                audit_db.flush()
            audit_db.add(model_call)
            audit_db.flush()
            ModelGateway._append_invocation_event(audit_db, invocation=invocation, model_call=model_call)
            audit_db.commit()
        except Exception:
            audit_db.rollback()
            raise
        finally:
            audit_db.close()

    def _assert_budget(
        self,
        db: Session,
        *,
        tenant_id: str,
        run_id: str,
        invocation_id: str,
        scope: AIInvocationScope,
        projection: CostProjection,
    ) -> None:
        settings = get_settings()
        if run_id:
            run = db.query(WorkflowRun).filter_by(id=run_id, tenant_id=tenant_id).first()
            if run:
                limit = float(run.ai_budget_usd or settings.model_run_budget_usd)
                projected = projection.cost_usd if projection.provenance == "historical" else 0.0
                if float(run.ai_cost_usd or 0.0) + projected + scope.envelope.reserved_budget_usd > limit:
                    raise ModelGatewayError(
                        f"AI run budget exhausted for run {run_id}; projected=${projected:.6f}, "
                        f"reserved=${scope.envelope.reserved_budget_usd:.6f}, hard_limit=${limit:.6f}"
                    )
        hard_limit = float(scope.envelope.hard_budget_usd or 0.0)
        if hard_limit:
            spent = invocation_spend(db, tenant_id=tenant_id, invocation_id=invocation_id)
            projected = projection.cost_usd if projection.provenance == "historical" else 0.0
            if spent >= hard_limit or spent + projected + scope.envelope.reserved_budget_usd > hard_limit:
                raise ModelGatewayError(
                    f"AI operation budget exhausted for {scope.scope_type}:{scope.scope_id}; "
                    f"spent=${spent:.6f}, projected=${projected:.6f}, reserved=${scope.envelope.reserved_budget_usd:.6f}, "
                    f"hard_limit=${hard_limit:.6f}"
                )
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        tenant_limit = float(
            ((tenant.runtime_configuration_json or {}).get("model_monthly_budget_usd") if tenant else None)
            or settings.model_monthly_budget_usd
        )
        month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_cost = float(
            db.query(func.coalesce(func.sum(ModelCall.estimated_cost_usd), 0.0))
            .filter(
                ModelCall.tenant_id == tenant_id,
                ModelCall.estimated_cost_usd > 0,
                ModelCall.created_at >= month_start,
            )
            .scalar()
            or 0.0
        )
        if monthly_cost >= tenant_limit:
            raise ModelGatewayError(f"AI monthly budget exhausted for tenant {tenant_id}")

    def _post_call_budget_error(
        self,
        db: Session,
        *,
        tenant_id: str,
        run_id: str,
        invocation_id: str,
        scope: AIInvocationScope,
        call_cost_usd: float,
    ) -> str:
        settings = get_settings()
        if run_id:
            run = db.query(WorkflowRun).filter_by(id=run_id, tenant_id=tenant_id).first()
            if run:
                limit = float(run.ai_budget_usd or settings.model_run_budget_usd)
                if float(run.ai_cost_usd or 0.0) + call_cost_usd + scope.envelope.reserved_budget_usd > limit:
                    return (
                        f"AI call would exceed the ${limit:.2f} budget for run {run_id} while preserving "
                        f"the ${scope.envelope.reserved_budget_usd:.2f} critical-step reserve"
                    )
        hard_limit = float(scope.envelope.hard_budget_usd or 0.0)
        if hard_limit:
            spent = invocation_spend(db, tenant_id=tenant_id, invocation_id=invocation_id)
            if spent + call_cost_usd > hard_limit:
                return f"AI call would exceed the ${hard_limit:.2f} budget for {scope.scope_type}:{scope.scope_id}"
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        tenant_limit = float(
            ((tenant.runtime_configuration_json or {}).get("model_monthly_budget_usd") if tenant else None)
            or settings.model_monthly_budget_usd
        )
        month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_cost = float(
            db.query(func.coalesce(func.sum(ModelCall.estimated_cost_usd), 0.0))
            .filter(ModelCall.tenant_id == tenant_id, ModelCall.estimated_cost_usd > 0, ModelCall.created_at >= month_start)
            .scalar()
            or 0.0
        )
        if monthly_cost + call_cost_usd > tenant_limit:
            return f"AI call would exceed the ${tenant_limit:.2f} monthly budget for tenant {tenant_id}"
        return ""

    @staticmethod
    def _invocation_record(
        db: Session,
        *,
        tenant_id: str,
        run_id: str,
        invocation_id: str,
        agent_name: str,
        model_name: str,
        model_role: str,
        routing_policy_version: str,
        scope: AIInvocationScope,
        projection: CostProjection,
        context_refs: List[str],
        status: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_read_tokens: int,
        actual_cost_usd: float,
        cache_eligible_tokens: int = 0,
        cache_write_tokens: int = 0,
        cache_savings_usd: float = 0.0,
        trace_id: str = "",
    ) -> AIInvocation:
        existing = db.get(AIInvocation, invocation_id)
        base_prompt = int(existing.prompt_tokens if existing else 0)
        base_completion = int(existing.completion_tokens if existing else 0)
        base_cache = int(existing.cache_read_tokens if existing else 0)
        base_cache_eligible = int(existing.cache_eligible_tokens if existing else 0)
        base_cache_write = int(existing.cache_write_tokens if existing else 0)
        base_cache_savings = float(existing.cache_savings_usd if existing else 0.0)
        base_cost = float(existing.actual_cost_usd if existing else 0.0)
        values = {
            "id": invocation_id,
            "tenant_id": tenant_id,
            "idempotency_key": invocation_id,
            "scope_type": scope.scope_type,
            "scope_id": scope.scope_id,
            "correlation_id": scope.correlation_id,
            "run_id": run_id,
            "agent_name": agent_name,
            "policy_version": scope.policy_version,
            "routing_policy_version": routing_policy_version or scope.policy_version,
            "requested_model_role": model_role,
            "resolved_model_name": model_name,
            "routing_reason": scope.routing_reason,
            "retry_classification": scope.retry_classification,
            "attempt_count": max(int(existing.attempt_count if existing else 0), scope.attempt_number),
            "status": status,
            "soft_budget_usd": scope.envelope.soft_budget_usd,
            "hard_budget_usd": scope.envelope.hard_budget_usd,
            "reserved_budget_usd": scope.envelope.reserved_budget_usd,
            "projected_input_tokens": projection.input_tokens,
            "projected_output_tokens": projection.output_tokens,
            "projected_cost_usd": projection.cost_usd,
            "prompt_tokens": base_prompt + prompt_tokens,
            "completion_tokens": base_completion + completion_tokens,
            "cache_read_tokens": base_cache + cache_read_tokens,
            "cache_eligible_tokens": base_cache_eligible + cache_eligible_tokens,
            "cache_write_tokens": base_cache_write + cache_write_tokens,
            "cache_savings_usd": round(base_cache_savings + cache_savings_usd, 8),
            "trace_id": trace_id or (existing.trace_id if existing else ""),
            "actual_cost_usd": round(base_cost + actual_cost_usd, 8),
            "metadata_json": {
                **dict(scope.metadata),
                "operation_context": {
                    "selected_reference_ids": sorted(set(context_refs)),
                    "selected_reference_count": len(set(context_refs)),
                    "estimated_input_tokens": projection.input_tokens,
                    "selection_policy_version": scope.policy_version,
                },
            },
            "updated_at": utcnow(),
        }
        if existing and (run_id or get_settings().runtime_profile.lower() == "test"):
            for key, value in values.items():
                if key not in {"id", "tenant_id", "idempotency_key"}:
                    setattr(existing, key, value)
            return existing
        return AIInvocation(**values)

    @staticmethod
    def _merge_invocation(target: AIInvocation, source: AIInvocation) -> None:
        for field in (
            "scope_type",
            "scope_id",
            "correlation_id",
            "run_id",
            "agent_name",
            "policy_version",
            "routing_policy_version",
            "requested_model_role",
            "resolved_model_name",
            "routing_reason",
            "retry_classification",
            "attempt_count",
            "status",
            "soft_budget_usd",
            "hard_budget_usd",
            "reserved_budget_usd",
            "projected_input_tokens",
            "projected_output_tokens",
            "projected_cost_usd",
            "prompt_tokens",
            "completion_tokens",
            "cache_read_tokens",
            "cache_eligible_tokens",
            "cache_write_tokens",
            "cache_savings_usd",
            "trace_id",
            "actual_cost_usd",
            "metadata_json",
            "updated_at",
        ):
            setattr(target, field, getattr(source, field))

    @staticmethod
    def _append_invocation_event(
        db: Session,
        *,
        invocation: AIInvocation,
        model_call: ModelCall | None = None,
        error: str = "",
    ) -> None:
        append_ledger_event(
            db,
            tenant_id=invocation.tenant_id,
            aggregate_type="ai_invocation",
            aggregate_id=invocation.id,
            event_type="ai.invocation_budget_blocked" if invocation.status == "budget_blocked" else "ai.invocation_recorded",
            actor_user_id="system:model-gateway",
            correlation_id=invocation.correlation_id,
            idempotency_key=f"ai-invocation:{invocation.id}:{model_call.id if model_call else 'budget'}",
            payload={
                "summary": "AI invocation cost and routing evidence recorded",
                "scope_type": invocation.scope_type,
                "scope_id": invocation.scope_id,
                "agent_name": invocation.agent_name,
                "policy_version": invocation.policy_version,
                "model_role": invocation.requested_model_role,
                "model_name": invocation.resolved_model_name,
                "routing_reason": invocation.routing_reason,
                "retry_classification": invocation.retry_classification,
                "attempt_count": invocation.attempt_count,
                "status": invocation.status,
                "projected_cost_usd": invocation.projected_cost_usd,
                "actual_cost_usd": invocation.actual_cost_usd,
                "model_call_id": model_call.id if model_call else "",
                "error": error[:1000],
            },
        )

    def _persist_budget_decision(
        self,
        db: Session,
        *,
        tenant_id: str,
        run_id: str,
        invocation_id: str,
        agent_name: str,
        model_name: str,
        model_role: str,
        routing_policy_version: str,
        scope: AIInvocationScope,
        projection: CostProjection,
        context_refs: List[str],
        error: str,
    ) -> None:
        scope.retry_classification = "budget_or_isolation"
        invocation = self._invocation_record(
            db,
            tenant_id=tenant_id,
            run_id=run_id,
            invocation_id=invocation_id,
            agent_name=agent_name,
            model_name=model_name,
            model_role=model_role,
            routing_policy_version=routing_policy_version,
            scope=scope,
            projection=projection,
            context_refs=context_refs,
            status="budget_blocked",
            prompt_tokens=0,
            completion_tokens=0,
            cache_read_tokens=0,
            actual_cost_usd=0.0,
        )
        if not run_id and get_settings().runtime_profile.lower() != "test":
            from app.db.session import SessionLocal, set_tenant_context

            audit_db = SessionLocal()
            try:
                set_tenant_context(audit_db, tenant_id, "model-gateway")
                persisted = audit_db.get(AIInvocation, invocation.id)
                if persisted:
                    self._merge_invocation(persisted, invocation)
                    invocation = persisted
                else:
                    audit_db.add(invocation)
                    audit_db.flush()
                self._append_invocation_event(audit_db, invocation=invocation, error=error)
                audit_db.commit()
            except Exception:
                audit_db.rollback()
                raise
            finally:
                audit_db.close()
            return
        if db.get(AIInvocation, invocation.id) is None:
            db.add(invocation)
            db.flush()
        self._append_invocation_event(db, invocation=invocation, error=error)
        db.flush()

    def _call_litellm(
        self,
        model_name: str,
        messages: List[Dict[str, Any]],
        response_schema: Optional[Dict[str, Any]],
        *,
        max_output_tokens: Optional[int] = None,
        provider_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        settings = get_settings()
        if not settings.litellm_api_key and not (settings.openai_api_key or settings.openrouter_api_key):
            raise ModelGatewayError("ASF_LITELLM_API_KEY plus OPENROUTER_API_KEY or OPENAI_API_KEY is required for real LLM calls")
        try:
            from litellm import completion, completion_cost
        except Exception as exc:  # pragma: no cover - dependency failure path
            raise ModelGatewayError(f"litellm is not installed: {exc}") from exc

        # LiteLLM's Python client still needs an OpenAI-compatible provider
        # prefix when it targets a proxy-side custom alias. The prefix is
        # consumed client-side; the proxy receives the configured alias.
        sdk_model_name = model_name
        if settings.litellm_base_url and not model_name.startswith("openai/"):
            sdk_model_name = f"openai/{model_name}"
        kwargs: Dict[str, Any] = {
            "model": sdk_model_name,
            "messages": messages,
            "timeout": request_timeout_seconds(model_name),
            "max_tokens": request_max_output_tokens(model_name, max_output_tokens),
            # Step retries belong to the AI-native executor, where every
            # failed attempt is persisted and can be audited.  LiteLLM's
            # implicit client retries can otherwise keep one model call
            # opaque for several timeout windows.
            "num_retries": 0,
        }
        provider_options = provider_options or {}
        if provider_options.get("cache_mode") == "openai_key" and provider_options.get("prompt_cache_key"):
            kwargs["prompt_cache_key"] = provider_options["prompt_cache_key"]
        if settings.litellm_base_url:
            kwargs["api_base"] = settings.litellm_base_url
        if settings.litellm_api_key:
            kwargs["api_key"] = settings.litellm_api_key
        elif model_name.startswith("openrouter/") and settings.openrouter_api_key:
            kwargs["api_key"] = settings.openrouter_api_key
        elif settings.openai_api_key:
            kwargs["api_key"] = settings.openai_api_key
        if response_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "asf_agent_response",
                    "strict": False,
                    "schema": response_schema,
                },
            }
        with trace_span(
            "llm.invocation",
            {
                "asf.model_alias": model_name,
                "asf.provider": "litellm",
                "asf.cache_mode": str(provider_options.get("cache_mode") or "none"),
            },
        ):
            response = completion(**kwargs)
        try:
            estimated_cost_usd = float(completion_cost(completion_response=response) or 0.0)
        except Exception:
            estimated_cost_usd = 0.0
        if estimated_cost_usd <= 0:
            hidden = getattr(response, "_hidden_params", {}) or {}
            estimated_cost_usd = float(hidden.get("response_cost") or hidden.get("response_cost_usd") or 0.0)
        message = response.choices[0].message
        finish_reason = str(getattr(response.choices[0], "finish_reason", "") or "")
        provider_request_id = str(getattr(response, "id", "") or "")
        hidden = getattr(response, "_hidden_params", {}) or {}
        provider_route = str(
            hidden.get("custom_llm_provider")
            or hidden.get("provider")
            or hidden.get("model_id")
            or provider_options.get("upstream_model")
            or ""
        )
        content = message.content or "{}"
        usage_object = getattr(response, "usage", {}) or {}
        if hasattr(usage_object, "model_dump"):
            usage = usage_object.model_dump(mode="json")
        else:
            usage = dict(usage_object)
        if estimated_cost_usd <= 0:
            estimated_cost_usd = float(usage.get("cost") or 0.0)
        parsed: Any
        try:
            parsed = json.loads(content)
            parse_error = ""
        except json.JSONDecodeError as exc:
            parsed = {"text": content}
            parse_error = str(exc)
        return {
            "parsed": parsed,
            "raw": content,
            "usage": usage,
            "estimated_cost_usd": estimated_cost_usd,
            "finish_reason": finish_reason,
            "provider_request_id": provider_request_id,
            "provider_route": provider_route,
            "cache_savings_usd": float(usage.get("cache_savings_usd") or hidden.get("cache_savings_usd") or 0.0),
            "parse_error": parse_error,
        }
