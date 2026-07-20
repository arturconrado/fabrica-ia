from app.core.config import get_settings
from app.agents.production_pipeline_provider import ProductionPipelineProvider
from app.providers.litellm_industrial_provider import LiteLLMIndustrialAgentProvider


def create_provider():
    provider_name = get_settings().agent_provider.lower()
    if provider_name in {"litellm", "real"}:
        return LiteLLMIndustrialAgentProvider()
    if provider_name == "mock":
        return ProductionPipelineProvider()
    raise RuntimeError("Unsupported ASF_AGENT_PROVIDER; expected mock or litellm")


provider = create_provider()
