"""Asynchronous ports for the modular AI-native factory core."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence


class WorkflowRuntimePort(Protocol):
    async def start(self, *, tenant_id: str, run_id: str) -> str: ...
    async def signal(self, *, tenant_id: str, run_id: str, signal: str, payload: Mapping[str, Any]) -> None: ...
    async def cancel(self, *, tenant_id: str, run_id: str, reason: str) -> None: ...


class ModelPort(Protocol):
    async def invoke(
        self,
        *,
        tenant_id: str,
        run_id: str,
        execution_unit_id: str,
        model_role: str,
        messages: Sequence[Mapping[str, Any]],
        response_schema: Mapping[str, Any],
        max_output_tokens: int,
    ) -> Mapping[str, Any]: ...


class SandboxPort(Protocol):
    async def run_profile(self, *, tenant_id: str, run_id: str, profile: str, workspace_ref: str) -> Mapping[str, Any]: ...


class ArtifactStorePort(Protocol):
    async def put(self, *, tenant_id: str, run_id: str, path: str, content: bytes, checksum: str) -> str: ...
    async def get(self, *, tenant_id: str, run_id: str, path: str) -> bytes: ...


class PromptCachePort(Protocol):
    async def capabilities(self, *, model_alias: str) -> Mapping[str, Any]: ...
    async def stable_prefix(self, *, prompt_version: str, schema_hash: str, toolset_hash: str) -> Mapping[str, Any]: ...


class LearningPolicyCatalogPort(Protocol):
    async def effective_policy(self, *, tenant_id: str, agent_name: str, task_type: str) -> Mapping[str, Any]: ...
