import json
import time
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ModelCall


class ModelGatewayError(RuntimeError):
    pass


class ModelGateway:
    def call(
        self,
        *,
        messages: List[Dict[str, str]],
        response_schema: Optional[Dict[str, Any]] = None,
        tenant_id: str,
        run_id: str = "",
        agent_name: str = "",
        db: Optional[Session] = None,
        model: str = "",
    ) -> Dict[str, Any]:
        settings = get_settings()
        model_name = model or settings.default_model
        start = time.time()
        call_id = str(uuid.uuid4())
        request_json = {"messages": messages, "response_schema": response_schema or {}, "model": model_name}
        status = "success"
        error = ""
        response_json: Dict[str, Any] = {}
        prompt_tokens = 0
        completion_tokens = 0
        try:
            response_json = self._call_litellm(model_name, messages, response_schema)
            usage = response_json.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
        except Exception as exc:
            status = "failed"
            error = str(exc)
            raise ModelGatewayError(error) from exc
        finally:
            if db is not None:
                db.add(
                    ModelCall(
                        id=call_id,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        agent_name=agent_name,
                        provider="litellm",
                        model_name=model_name,
                        request_json=request_json,
                        response_json=response_json,
                        status=status,
                        error=error,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        duration_seconds=round(time.time() - start, 3),
                    )
                )
                db.flush()
        return {"id": call_id, "model": model_name, "content": response_json}

    def _call_litellm(
        self,
        model_name: str,
        messages: List[Dict[str, str]],
        response_schema: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        settings = get_settings()
        if not settings.litellm_api_key and not (settings.openai_api_key or settings.openrouter_api_key):
            raise ModelGatewayError("ASF_LITELLM_API_KEY plus OPENROUTER_API_KEY or OPENAI_API_KEY is required for real LLM calls")
        try:
            from litellm import completion
        except Exception as exc:  # pragma: no cover - dependency failure path
            raise ModelGatewayError(f"litellm is not installed: {exc}") from exc

        kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "timeout": settings.model_request_timeout_seconds,
        }
        if settings.litellm_base_url:
            kwargs["api_base"] = settings.litellm_base_url
        if settings.litellm_api_key:
            kwargs["api_key"] = settings.litellm_api_key
        elif model_name.startswith("openrouter/") and settings.openrouter_api_key:
            kwargs["api_key"] = settings.openrouter_api_key
        elif settings.openai_api_key:
            kwargs["api_key"] = settings.openai_api_key
        if response_schema:
            kwargs["response_format"] = {"type": "json_object"}
        response = completion(**kwargs)
        message = response.choices[0].message
        content = message.content or "{}"
        parsed: Any
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {"text": content}
        return {
            "parsed": parsed,
            "raw": content,
            "usage": dict(getattr(response, "usage", {}) or {}),
        }
