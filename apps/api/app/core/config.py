import os
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "production-like"
    runtime_profile: str = "homologation"
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
    workflow_backend: str = "homologation"
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "software-factory"

    litellm_base_url: str = "http://localhost:4000"
    litellm_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    default_model: str = "asf-default"
    fast_model: str = "asf-fast"
    reasoning_model: str = "asf-reasoning"
    code_model: str = "asf-code"
    model_request_timeout_seconds: int = 180
    fast_model_request_timeout_seconds: int = 90
    reasoning_model_request_timeout_seconds: int = 240
    code_model_request_timeout_seconds: int = 360
    model_max_output_tokens: int = 16_000
    fast_model_max_output_tokens: int = 4_000
    reasoning_model_max_output_tokens: int = 16_000
    code_model_max_output_tokens: int = 32_000
    model_monthly_budget_usd: float = 250.0
    model_run_budget_usd: float = 15.0
    model_commercial_operation_budget_usd: float = 2.0
    model_engagement_plan_budget_usd: float = 2.0
    model_service_deliverable_budget_usd: float = 3.0
    model_rag_answer_budget_usd: float = 0.5
    model_agent_candidate_budget_usd: float = 2.0
    model_agent_evaluation_budget_usd: float = 2.0
    agent_max_step_attempts: int = 2
    agent_retry_backoff_seconds: float = 6.0
    agent_max_total_steps: int = 32

    mcp_enabled: bool = True
    mcp_registry_path: str = "./data/mcp/servers.json"
    mcp_request_timeout_seconds: int = 30

    sandbox_backend: str = "local_trusted"
    sandbox_namespace: str = "software-factory-sandbox"
    sandbox_runtime_class: str = "gvisor"
    sandbox_image: str = "python:3.12-slim"
    sandbox_kubeconfig: str = ""
    sandbox_workspace_pvc: str = ""
    sandbox_workspace_mount_path: str = "/workspace"
    sandbox_timeout_seconds: int = 60
    sandbox_cpu_limit: str = "1000m"
    sandbox_memory_limit: str = "512Mi"
    sandbox_allowed_commands: str = (
        "python -m pytest generated_app/backend/tests||"
        'python -c "from generated_app.backend.app.main import app; assert app"||'
        "npm --prefix generated_app/frontend run test||"
        "npm --prefix generated_app/frontend run build||"
        "npm --prefix generated_app/frontend run test:visual||"
        "npm --prefix generated_app/frontend run test:a11y||"
        "bandit -q -r generated_app/backend -f json"
    )
    agent_step_delay_ms: int = 900

    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "software-factory-artifacts"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    encryption_key: str = ""
    observability_enabled: bool = True
    otel_service_name: str = "agentic-software-factory-api"
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    backup_dir: str = ""
    pilot_max_tenants: int = 10
    pilot_max_users_per_tenant: int = 20
    pilot_max_concurrent_workflows: int = 10
    pilot_max_concurrent_workflows_per_tenant: int = 2
    knowledge_max_bases_per_tenant: int = 10
    knowledge_max_documents_per_tenant: int = 250
    knowledge_max_document_chars: int = 250_000
    knowledge_max_total_chars_per_tenant: int = 5_000_000
    knowledge_chunk_chars: int = 1_200
    knowledge_chunk_overlap_chars: int = 180
    knowledge_max_query_results: int = 8
    generative_build_enabled: bool = False
    service_delivery_os_enabled: bool = True
    service_wip_global_limit: int = 5
    service_wip_per_tenant_limit: int = 2
    agent_candidate_evaluation_repetitions: int = 3

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

    def model_for_role(self, role: str) -> str:
        return {
            "fast": self.fast_model,
            "reasoning": self.reasoning_model,
            "code": self.code_model,
        }.get(role, self.default_model)


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
    if settings.agent_provider.lower() == "litellm":
        from app.providers.model_capabilities import validate_model_capabilities

        validate_model_capabilities(settings)
    if settings.allow_non_production_runtime:
        return

    errors = []
    runtime_profile = settings.runtime_profile.lower()
    agent_provider = settings.agent_provider.lower()
    workflow_backend = settings.workflow_backend.lower()
    allowed_matrix = {
        ("homologation", "litellm", "homologation"),
        ("test", "mock", "homologation"),
        ("production", "litellm", "temporal"),
    }
    if (runtime_profile, agent_provider, workflow_backend) not in allowed_matrix:
        errors.append(
            "Invalid runtime matrix: "
            f"ASF_RUNTIME_PROFILE={settings.runtime_profile}, "
            f"ASF_AGENT_PROVIDER={settings.agent_provider}, "
            f"ASF_WORKFLOW_BACKEND={settings.workflow_backend}"
        )
    if runtime_profile in {"homologation", "test"}:
        if agent_provider == "litellm" and not (settings.openai_api_key or settings.openrouter_api_key or settings.litellm_api_key):
            errors.append("Homologation with ASF_AGENT_PROVIDER=litellm requires a configured LLM key")
        if runtime_profile == "homologation" and settings.generative_build_enabled and settings.sandbox_backend.lower() != "kubernetes":
            errors.append("AI-native homologation requires ASF_SANDBOX_BACKEND=kubernetes")
        if settings.generative_build_enabled and settings.model_run_budget_usd <= 0:
            errors.append("ASF_MODEL_RUN_BUDGET_USD must be greater than zero for AI-native execution")
        if errors:
            raise ProductionRuntimeConfigError("; ".join(errors))
        return

    if settings.database_url.startswith("sqlite"):
        errors.append("SQLite is not allowed in production")
    if settings.auth_disabled:
        errors.append("ASF_AUTH_DISABLED must be false in production")
    if settings.dev_auth_token:
        errors.append("ASF_DEV_AUTH_TOKEN must be empty in production; use OIDC bearer tokens")
    if not settings.oidc_issuer_url or not settings.oidc_jwks_url:
        errors.append("OIDC issuer and JWKS URL are required")
    if agent_provider != "litellm":
        errors.append("ASF_AGENT_PROVIDER must be litellm in production")
    if workflow_backend != "temporal":
        errors.append("ASF_WORKFLOW_BACKEND must be temporal in production")
    if not settings.mcp_enabled:
        errors.append("ASF_MCP_ENABLED must be true")
    if settings.sandbox_backend.lower() != "kubernetes":
        errors.append("ASF_SANDBOX_BACKEND must be kubernetes in production")
    if not settings.generative_build_enabled:
        errors.append("ASF_GENERATIVE_BUILD_ENABLED must be true in production")
    if settings.model_run_budget_usd <= 0:
        errors.append("ASF_MODEL_RUN_BUDGET_USD must be greater than zero in production")
    if not settings.sandbox_workspace_pvc:
        errors.append("ASF_SANDBOX_WORKSPACE_PVC is required for Kubernetes sandbox jobs")
    if not settings.openai_api_key and not settings.openrouter_api_key:
        errors.append("OPENROUTER_API_KEY or OPENAI_API_KEY is required for the production-only LiteLLM gateway")
    if not settings.litellm_api_key:
        errors.append("ASF_LITELLM_API_KEY is required for the LiteLLM gateway")
    if not settings.s3_endpoint_url or not settings.s3_bucket:
        errors.append("S3-compatible artifact storage is required")
    if not settings.s3_access_key_id or not settings.s3_secret_access_key:
        errors.append("S3-compatible artifact storage credentials are required")
    if settings.s3_access_key_id == "minioadmin" or settings.s3_secret_access_key == "minioadmin":
        errors.append("Default MinIO credentials are forbidden in production")
    if not settings.encryption_key:
        errors.append("ASF_ENCRYPTION_KEY is required in production")
    if not settings.observability_enabled:
        errors.append("ASF_OBSERVABILITY_ENABLED must be true in production")
    if settings.observability_enabled and not settings.otel_exporter_otlp_endpoint:
        errors.append("ASF_OTEL_EXPORTER_OTLP_ENDPOINT is required in production")
    if errors:
        raise ProductionRuntimeConfigError("; ".join(errors))
