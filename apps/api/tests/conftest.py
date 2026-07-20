import os

import httpx
import pytest


os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ASF_DATABASE_URL", "sqlite:///:memory:")
os.environ["ASF_RUNTIME_PROFILE"] = "test"
os.environ["ASF_AGENT_PROVIDER"] = "mock"
os.environ["ASF_WORKFLOW_BACKEND"] = "homologation"


def pytest_configure(config):
    config.addinivalue_line("markers", "production_stack: requires a running production-only ASF stack")
    config.addinivalue_line("markers", "postgres_hardening: requires a migrated PostgreSQL test database")


@pytest.fixture(scope="session")
def api_base_url() -> str:
    base_url = os.getenv("ASF_TEST_API_BASE_URL", "")
    if not base_url:
        pytest.skip("ASF_TEST_API_BASE_URL is required; production-stack tests do not start local services")
    return base_url.rstrip("/")


@pytest.fixture(scope="session")
def bearer_token() -> str:
    token = os.getenv("ASF_TEST_BEARER_TOKEN", "")
    if not token:
        pytest.skip("ASF_TEST_BEARER_TOKEN is required; tests require OIDC auth")
    return token


@pytest.fixture(scope="session")
def tenant_id() -> str:
    return os.getenv("ASF_TEST_TENANT_ID", "local-dev")


@pytest.fixture(scope="session")
def client(api_base_url: str, bearer_token: str, tenant_id: str):
    headers = {"Authorization": f"Bearer {bearer_token}", "X-Tenant-ID": tenant_id}
    with httpx.Client(base_url=api_base_url, headers=headers, timeout=60.0) as http_client:
        yield http_client
