"""Versioned model/provider capability registry used for safe request adaptation."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class ModelCapabilityError(RuntimeError):
    pass


class ModelCapability(BaseModel):
    upstream_model_env: str
    upstream_model_default: str
    provider: str
    structured_output: Literal["json_schema", "json_object", "none"] = "json_schema"
    cache_mode: Literal["adaptive_openrouter", "anthropic_explicit", "openai_key", "implicit", "none"] = "none"
    cache_min_tokens: int = Field(default=1024, ge=0)
    timeout_seconds: int = Field(ge=1)
    max_output_tokens: int = Field(ge=128, le=128_000)

    @property
    def upstream_model(self) -> str:
        return os.getenv(self.upstream_model_env) or self.upstream_model_default

    @property
    def family(self) -> str:
        model = self.upstream_model.casefold()
        if "anthropic/" in model or "claude" in model:
            return "anthropic"
        if "openai/" in model or "/gpt-" in model or "/o1" in model or "/o3" in model:
            return "openai"
        return "implicit"

    @property
    def effective_cache_mode(self) -> str:
        if self.cache_mode != "adaptive_openrouter":
            return self.cache_mode
        return {"anthropic": "anthropic_explicit", "openai": "openai_key"}.get(self.family, "implicit")


class CapabilityManifest(BaseModel):
    version: int
    aliases: dict[str, ModelCapability]
    usage_fields: dict[str, list[str]] = Field(default_factory=dict)


class ModelCapabilityRegistry:
    def __init__(self, manifest: CapabilityManifest) -> None:
        self.manifest = manifest

    @classmethod
    def load(cls, path: Path | None = None) -> "ModelCapabilityRegistry":
        source = path or Path(__file__).with_name("model_capabilities.yaml")
        if not source.exists():
            raise ModelCapabilityError(f"model capability manifest is missing: {source}")
        payload = yaml.safe_load(source.read_text()) or {}
        return cls(CapabilityManifest.model_validate(payload))

    def get(self, alias: str) -> ModelCapability:
        capability = self.manifest.aliases.get(alias)
        if not capability:
            raise ModelCapabilityError(f"model alias {alias!r} is absent from the capability manifest")
        return capability

    def validate_configured_aliases(self, aliases: set[str]) -> None:
        missing = aliases.difference(self.manifest.aliases)
        if missing:
            raise ModelCapabilityError(f"configured LiteLLM aliases have no capability entry: {sorted(missing)}")


@lru_cache
def model_capabilities() -> ModelCapabilityRegistry:
    return ModelCapabilityRegistry.load()


def validate_model_capabilities(settings) -> None:
    model_capabilities().validate_configured_aliases(
        {settings.default_model, settings.fast_model, settings.reasoning_model, settings.code_model}
    )
