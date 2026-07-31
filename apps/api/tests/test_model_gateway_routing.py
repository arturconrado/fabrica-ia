from types import SimpleNamespace

import litellm

from app.providers import model_gateway as model_gateway_module
from app.providers.model_gateway import ModelGateway


def test_direct_openrouter_routes_alias_to_manifest_upstream(monkeypatch):
    captured = {}
    response = SimpleNamespace(
        id="provider-request-1",
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content='{"result": "ok"}'),
            )
        ],
        usage={"prompt_tokens": 11, "completion_tokens": 4},
        _hidden_params={"custom_llm_provider": "openrouter"},
    )

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(
        model_gateway_module,
        "get_settings",
        lambda: SimpleNamespace(
            litellm_api_key="",
            litellm_base_url="",
            openai_api_key="",
            openrouter_api_key="provider-secret",
            fast_model="asf-fast",
            reasoning_model="asf-reasoning",
            code_model="asf-code",
            fast_model_request_timeout_seconds=90,
            reasoning_model_request_timeout_seconds=240,
            code_model_request_timeout_seconds=360,
            model_request_timeout_seconds=90,
            fast_model_max_output_tokens=4_000,
            reasoning_model_max_output_tokens=16_000,
            code_model_max_output_tokens=32_000,
            model_max_output_tokens=16_000,
        ),
    )
    monkeypatch.setattr(litellm, "completion", fake_completion)
    monkeypatch.setattr(litellm, "completion_cost", lambda completion_response: 0.001)

    result = ModelGateway()._call_litellm(
        "asf-reasoning",
        [{"role": "user", "content": "Validate routing"}],
        None,
        max_output_tokens=256,
        provider_options={
            "provider": "openrouter",
            "upstream_model": "anthropic/claude-sonnet-4.5",
        },
    )

    assert captured["model"] == "openrouter/anthropic/claude-sonnet-4.5"
    assert captured["api_key"] == "provider-secret"
    assert "api_base" not in captured
    assert result["parsed"] == {"result": "ok"}
    assert result["provider_route"] == "openrouter"
