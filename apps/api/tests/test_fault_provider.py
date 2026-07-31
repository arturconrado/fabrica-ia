from fastapi.testclient import TestClient

from tests.support.fault_provider import app


def test_fault_provider_exposes_deterministic_openai_compatible_failures(monkeypatch):
    client = TestClient(app)
    payload = {"model": "asf-fast", "messages": [{"role": "user", "content": "private"}]}
    assert client.post("/rate_limit/v1/chat/completions", json=payload).status_code == 429
    assert client.post("/unavailable/v1/chat/completions", json=payload).status_code == 503
    assert client.post("/schema_invalid/v1/chat/completions", json=payload).json()["choices"][0]["message"]["content"] == "{}"
    truncated = client.post("/truncated/v1/chat/completions", json=payload)
    assert truncated.status_code == 200
    assert truncated.text.endswith("[")
    monkeypatch.setenv("ASF_FAULT_TIMEOUT_SECONDS", "0")
    assert client.post("/timeout/v1/chat/completions", json=payload).status_code == 200
