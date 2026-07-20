import os
import time
import io
import zipfile
import uuid

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


def test_direct_enterprise_run_is_disabled_in_production(client):
    payload = {
        "prompt": "Valide ContractFlow para clientes, contratos e faturas com auditoria e aprovação humana.",
        "project_name": "ContractFlow Reference Validation",
        "template": "contractflow-reference",
        "industry": "general_b2b",
        "quality_profile": "assisted_pilot",
        "compliance": ["LGPD baseline"],
        "integrations": [],
        "data_sensitivity": "internal",
    }
    response = client.post("/runs/enterprise", json=payload)
    assert response.status_code == 409


def test_batch_requires_real_name_and_items(client):
    response = client.post("/batches")
    assert response.status_code == 422


def test_tenant_knowledge_ingestion_and_hybrid_retrieval(client):
    suffix = uuid.uuid4().hex
    listed = client.get("/api/v1/knowledge-bases")
    assert listed.status_code == 200, listed.text
    release_bases = [
        row
        for row in listed.json()
        if row.get("name") == "Release validation knowledge"
        or str(row.get("name") or "").startswith("Release knowledge ")
    ]
    if release_bases:
        base_id = release_bases[0]["id"]
    else:
        created = client.post(
            "/api/v1/knowledge-bases",
            json={"name": "Release validation knowledge", "description": "Target-stack tenant isolation validation"},
            headers={"Idempotency-Key": "knowledge-base:production-stack-contract-v1"},
        )
        assert created.status_code == 200, created.text
        base_id = created.json()["id"]

    canary = f"tenantcanary{suffix}"
    document = client.post(
        f"/api/v1/knowledge-bases/{base_id}/documents",
        json={
            "title": "Private release validation",
            "content": f"The private validation marker is {canary}. It belongs only to the authenticated tenant.",
            "source_type": "release-test",
        },
        headers={"Idempotency-Key": f"knowledge-document:{suffix}"},
    )
    assert document.status_code == 200, document.text
    assert document.json()["storage_key"].startswith(f"tenants/")
    assert f"/knowledge/{base_id}/" in document.json()["storage_key"]

    result = client.post(
        f"/api/v1/knowledge-bases/{base_id}/query",
        json={"question": f"What is {canary}?", "top_k": 5, "generate_answer": False},
        headers={"Idempotency-Key": f"knowledge-query:{suffix}"},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["answer_mode"] == "extractive"
    assert body["results"]
    assert canary in " ".join(item["content"] for item in body["results"])
    assert all("score_components" in item for item in body["results"])


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
    if run["status"] == "waiting_for_human":
        assert 80 <= run["homologation_readiness_score"] < 100
    else:
        assert run["homologation_readiness_score"] == 100
    gates = client.get(f"/runs/{run_id}/quality-gates")
    assert gates.status_code == 200
    assert len(gates.json()) >= 17
    if run["status"] == "waiting_for_human":
        assert any(gate["status"] == "review_required" for gate in gates.json())
    package = client.get(f"/runs/{run_id}/delivery-package")
    assert package.status_code == 200
    package_body = package.json()
    assert package_body["path"].startswith("s3://")
    assert package_body["manifest_json"]["storage_prefix"].startswith("tenants/")
    download = client.get(f"/runs/{run_id}/delivery-package/download")
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert "manifest.json" in archive.namelist()


def test_two_ai_native_missions_have_complete_distinct_validation_manifests(client):
    run_ids = [os.getenv("ASF_TEST_CONTRACTFLOW_RUN_ID"), os.getenv("ASF_TEST_SERVICEDESK_RUN_ID")]
    if not all(run_ids):
        pytest.skip("Two completed AI-native mission ids are required")
    manifests = []
    for run_id in run_ids:
        response = client.get(f"/runs/{run_id}/validation-manifest")
        assert response.status_code == 200, response.text
        manifest = response.json()
        assert manifest["workflow_id"] == "software_factory_ai_native_v2"
        assert manifest["generation_mode"] == "ai_native_v2"
        assert manifest["generation_fingerprint"]
        assert manifest["generated_files"]
        assert len(manifest["ai_nodes"]) >= 18
        assert 0 < float(manifest["budget"]["actual_usd"]) <= 15
        assert manifest["invariants"] and all(manifest["invariants"].values()), manifest["invariants"]
        assert len(manifest["gates"]) == 17
        assert all(call["status"] == "success" for call in manifest["model_calls"])
        assert all(artifact["model_call_id"] and artifact["step_execution_id"] for artifact in manifest["artifacts"])
        assert all(change["model_call_id"] and change["step_execution_id"] for change in manifest["generated_files"])
        failed_reports = [report for report in manifest["test_reports"] if report["status"] == "failed"]
        if failed_reports:
            engineer_iterations = [step["iteration"] for step in manifest["steps"] if step["node_id"] == "Engineer"]
            assert max(engineer_iterations) >= 2
        manifests.append(manifest)
    assert manifests[0]["generation_fingerprint"] != manifests[1]["generation_fingerprint"]
