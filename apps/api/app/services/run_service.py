from app.core.config import get_settings
from app.providers.litellm_industrial_provider import LiteLLMIndustrialAgentProvider


def create_provider():
    provider_name = get_settings().agent_provider.lower()
    if provider_name in {"litellm", "real"}:
        return LiteLLMIndustrialAgentProvider()
    raise RuntimeError("Production-only runtime requires ASF_AGENT_PROVIDER=litellm")


provider = create_provider()
