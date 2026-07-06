import os
import time

import httpx
import pytest


pytestmark = pytest.mark.production_stack


def test_health_is_public(api_base_url):
    response = httpx.get(f"{api_base_url}/health", timeout=10.0)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_protected_route_rejects_missing_jwt(api_base_url):
    response = httpx.get(f"{api_base_url}/auth/me", timeout=10.0)
    assert response.status_code == 401


def test_auth_me_uses_oidc_principal(client):
    response = client.get("/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["auth_mode"] == "oidc"
    assert body["tenant_id"]


def test_enterprise_run_schedules_temporal_workflow(client):
    payload = {
        "prompt": "Crie uma plataforma enterprise para contratos, aprovações, SLA, auditoria e integrações ERP.",
        "project_name": "Production ContractOps",
        "template": "enterprise-saas",
        "industry": "financial_services",
        "quality_profile": "regulated_enterprise",
        "compliance": ["SOC2", "LGPD", "ISO27001"],
        "integrations": ["SSO/OIDC", "ERP", "Data Warehouse"],
        "data_sensitivity": "confidential",
    }
    response = client.post("/runs/enterprise", json=payload)
    assert response.status_code == 200
    run = response.json()
    assert run["id"]
    assert run["provider"] == "production-litellm"
    assert run["temporal_workflow_id"]
    assert run["status"] == "scheduled"


def test_batch_schedules_child_runs(client):
    response = client.post("/batches")
    assert response.status_code == 200
    batch = response.json()
    assert batch["id"]
    items = client.get(f"/batches/{batch['id']}/items")
    assert items.status_code == 200
    assert len(items.json()) == 3
    metrics = client.get(f"/batches/{batch['id']}/metrics")
    assert metrics.status_code == 200
    assert any(metric["name"] == "scheduled_runs" for metric in metrics.json())


def test_run_evidence_reaches_quality_gate(client):
    run_id = os.getenv("ASF_TEST_COMPLETED_RUN_ID")
    if not run_id:
        pytest.skip("ASF_TEST_COMPLETED_RUN_ID is required for completed evidence assertions")
    deadline = time.time() + 180
    run = {}
    while time.time() < deadline:
        response = client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        if run["status"] in {"waiting_for_human", "approved_for_homologation"}:
            break
        time.sleep(5)
    assert run["homologation_readiness_score"] >= 90
    gates = client.get(f"/runs/{run_id}/quality-gates")
    assert gates.status_code == 200
    assert len(gates.json()) >= 17
    package = client.get(f"/runs/{run_id}/delivery-package")
    assert package.status_code == 200
