import os
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "production-like"
    database_url: str = "postgresql+psycopg://factory:factory@localhost:5432/factory"
    data_dir: str = "./data"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    default_tenant_id: str = "local-dev"
    default_tenant_name: str = "Local Development"
    auth_disabled: bool = False
    dev_auth_token: str = ""
    oidc_issuer_url: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_tenant_claim: str = "tenant_id"

    agent_provider: str = "litellm"
    workflow_backend: str = "temporal"
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "software-factory"

    litellm_base_url: str = "http://localhost:4000"
    litellm_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    default_model: str = "openrouter/openai/gpt-4o-mini"
    model_request_timeout_seconds: int = 60
    model_monthly_budget_usd: float = 250.0

    mcp_enabled: bool = True
    mcp_registry_path: str = "./data/mcp/servers.json"
    mcp_request_timeout_seconds: int = 30

    sandbox_backend: str = "kubernetes"
    sandbox_namespace: str = "software-factory-sandbox"
    sandbox_runtime_class: str = "gvisor"
    sandbox_image: str = "python:3.12-slim"
    sandbox_kubeconfig: str = ""
    sandbox_workspace_pvc: str = ""
    sandbox_workspace_mount_path: str = "/workspace"
    sandbox_timeout_seconds: int = 60
    sandbox_cpu_limit: str = "1000m"
    sandbox_memory_limit: str = "512Mi"
    sandbox_allowed_commands: str = "python -m pytest generated_app/tests"
    agent_step_delay_ms: int = 900

    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "software-factory-artifacts"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"

    # This flag is intentionally absent from .env.example. It is only for
    # isolated developer diagnostics and must never be used for homologation.
    allow_non_production_runtime: bool = False

    model_config = SettingsConfigDict(env_prefix="ASF_", env_file=".env", extra="ignore")

    @property
    def origins(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_sandbox_commands(self) -> List[str]:
        return [command.strip() for command in self.sandbox_allowed_commands.split("||") if command.strip()]

    @property
    def auth_required(self) -> bool:
        return not self.auth_disabled


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        settings.database_url = database_url
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if openai_api_key and not settings.openai_api_key:
        settings.openai_api_key = openai_api_key
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_api_key and not settings.openrouter_api_key:
        settings.openrouter_api_key = openrouter_api_key
    return settings


class ProductionRuntimeConfigError(RuntimeError):
    pass


def validate_production_runtime(settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    if settings.allow_non_production_runtime:
        return

    errors = []
    if settings.database_url.startswith("sqlite"):
        errors.append("SQLite is not allowed in the production-only runtime")
    if settings.auth_disabled:
        errors.append("ASF_AUTH_DISABLED must be false")
    if settings.dev_auth_token:
        errors.append("ASF_DEV_AUTH_TOKEN must be empty; use OIDC bearer tokens")
    if not settings.oidc_issuer_url or not settings.oidc_jwks_url:
        errors.append("OIDC issuer and JWKS URL are required")
    if settings.agent_provider.lower() != "litellm":
        errors.append("ASF_AGENT_PROVIDER must be litellm")
    if settings.workflow_backend.lower() != "temporal":
        errors.append("ASF_WORKFLOW_BACKEND must be temporal")
    if not settings.mcp_enabled:
        errors.append("ASF_MCP_ENABLED must be true")
    if settings.sandbox_backend.lower() != "kubernetes":
        errors.append("ASF_SANDBOX_BACKEND must be kubernetes")
    if not settings.sandbox_workspace_pvc:
        errors.append("ASF_SANDBOX_WORKSPACE_PVC is required for Kubernetes sandbox jobs")
    if not settings.openai_api_key and not settings.openrouter_api_key:
        errors.append("OPENROUTER_API_KEY or OPENAI_API_KEY is required for the production-only LiteLLM gateway")
    if not settings.litellm_api_key:
        errors.append("ASF_LITELLM_API_KEY is required for the LiteLLM gateway")
    if not settings.s3_endpoint_url or not settings.s3_bucket:
        errors.append("S3-compatible artifact storage is required")
    if errors:
        raise ProductionRuntimeConfigError("; ".join(errors))
