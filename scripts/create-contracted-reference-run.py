#!/usr/bin/env python3
"""Create one real AI-native validation mission through the contracted journey."""

import json
import hashlib
import os
import sys
import time
import urllib.error
import urllib.request


BASE_URL = os.environ["ASF_TEST_API_BASE_URL"].rstrip("/")
TOKEN = os.environ["ASF_TEST_BEARER_TOKEN"]
TENANT_ID = os.environ["ASF_TEST_TENANT_ID"]
MISSION_KEY = os.environ.get("ASF_VALIDATION_MISSION", "contractflow").strip().lower()
VALIDATION_ID = f"{os.environ.get('ASF_VALIDATION_ID') or str(int(time.time()))}-{MISSION_KEY}"

MISSIONS = {
    "contractflow": {
        "name": "ContractFlow",
        "sector": "legal_operations",
        "summary": "Gestão de clientes, contratos, faturas, vencimentos e aprovações com dashboard auditável.",
        "briefing": (
            "Criar um produto ContractFlow full-stack para uma consultoria B2B. Usuários de operações precisam cadastrar "
            "clientes, elaborar contratos com status e vigência, emitir faturas vinculadas, marcar pagamentos, acompanhar "
            "valores em aberto e aprovar exceções. Exigir API, interface responsiva, banco tenant-scoped, testes backend e "
            "frontend, Playwright, axe, scan de segurança, rastreabilidade e aprovação humana final."
        ),
    },
    "servicedesk": {
        "name": "ServiceDesk",
        "sector": "service_operations",
        "summary": "Gestão de chamados, SLA, prioridade, atribuição e dashboard operacional auditável.",
        "briefing": (
            "Criar um produto ServiceDesk full-stack para uma operação de serviços. Solicitantes abrem chamados por categoria "
            "e prioridade; analistas recebem atribuições, atualizam status e registram resolução; gestores acompanham SLA, "
            "backlog e violações em dashboard. Exigir API, interface responsiva, banco tenant-scoped, testes backend e frontend, "
            "Playwright, axe, scan de segurança, rastreabilidade e aprovação humana final."
        ),
    },
}

CAPABILITIES = [
    "briefing.intake",
    "idea.validate",
    "mvp.scope",
    "mvp.generate",
    "mvp.review",
    "proposal.generate",
    "package.export",
    "component.start",
    "component.view",
    "asf.run.create",
    "homologation.package",
    "delivery.approve",
]


def request(method, path, payload=None, *, idempotency_key=""):
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "X-Tenant-ID": TENANT_ID,
        "Content-Type": "application/json",
        "X-Correlation-ID": f"contracted-reference-validation-{VALIDATION_ID}",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    body = json.dumps(payload).encode() if payload is not None else None
    http_request = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(http_request, timeout=600) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {path} transport failed: {exc.reason}") from exc
    try:
        return json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{method} {path} returned invalid JSON") from exc


def ensure_validation_entitlement(mission):
    entitlements = request("GET", "/api/v1/entitlements")
    active_contract_ids = {
        contract["id"] for contract in request("GET", "/api/v1/contracts") if contract.get("status") == "active"
    }
    for entitlement in entitlements:
        if (
            entitlement.get("component_code") == "rapid_mvp_factory"
            and entitlement.get("status") == "granted"
            and entitlement.get("contract_id") in active_contract_ids
            and (entitlement.get("terms_json") or {}).get("validation") is True
            and (entitlement.get("terms_json") or {}).get("build_mode") == "ai_native"
            and (entitlement.get("terms_json") or {}).get("generative_build") is True
            and set(CAPABILITIES).issubset(set(entitlement.get("capabilities_json") or []))
        ):
            return entitlement
    contract = request(
        "POST",
        "/api/v1/contracts",
        {
            "contract_number": f"VALIDATION-{mission['name'].upper()}-{VALIDATION_ID}",
            "status": "draft",
            "scope_summary": f"AI-native contracted validation for {mission['name']}.",
            "commercial_metadata": {"validation": True, "mission": mission["name"], "workflow": "software_factory_ai_native_v2"},
        },
    )
    request(
        "POST",
        f"/api/v1/contracts/{contract['id']}/activate",
        {},
        idempotency_key=f"validation-contract-activate-{VALIDATION_ID}",
    )
    return request(
        "POST",
        f"/api/v1/contracts/{contract['id']}/entitlements",
        {
            "component_code": "rapid_mvp_factory",
            "status": "granted",
            "limits": {"mvp_runs": 100, "users": 20, "concurrent_workflows": 2},
            "capabilities": CAPABILITIES,
            "terms": {
                "validation": True,
                "build_mode": "ai_native",
                "generative_build": True,
                "regulated_data": False,
            },
        },
    )


def main():
    mission = MISSIONS.get(MISSION_KEY)
    if not mission:
        raise RuntimeError(f"Unknown validation mission: {MISSION_KEY}")
    ensure_validation_entitlement(mission)
    prospect = request(
        "POST",
        "/api/v1/prospects",
        {
            "name": f"{mission['name']} Validation {VALIDATION_ID}",
            "company": f"{mission['name']} Validation {VALIDATION_ID}",
            "sector": mission["sector"],
            "source": "production_validation",
            "metadata": {"validation": True},
        },
    )
    opportunity = request(
        "POST",
        "/api/v1/opportunities",
        {
            "prospect_id": prospect["id"],
            "title": f"{mission['name']} AI-Native Validation {VALIDATION_ID}",
            "summary": mission["summary"],
            "value_potential": 1.0,
        },
    )
    bundle = request("GET", f"/api/v1/opportunities/{opportunity['id']}")
    if not bundle.get("briefing"):
        request(
            "POST",
            f"/api/v1/opportunities/{opportunity['id']}/briefing",
            {"raw_text": mission["briefing"]},
        )
        bundle = request("GET", f"/api/v1/opportunities/{opportunity['id']}")
    spec = bundle.get("mvp_spec")
    if not spec:
        request("POST", f"/api/v1/opportunities/{opportunity['id']}/validate", {})
        spec = request("POST", f"/api/v1/opportunities/{opportunity['id']}/scope-mvp", {})
    if spec.get("blueprint_ref") != "ai_native_webapp@1.0":
        raise RuntimeError(f"Unexpected validation blueprint: {spec.get('blueprint_ref')}")
    bundle = request("GET", f"/api/v1/opportunities/{opportunity['id']}")
    mvp_run = bundle.get("mvp_run") or request("POST", f"/api/v1/opportunities/{opportunity['id']}/generate-mvp", {})
    bundle = request("GET", f"/api/v1/opportunities/{opportunity['id']}")
    proposal = bundle.get("proposal") or request(
        "POST", f"/api/v1/opportunities/{opportunity['id']}/generate-proposal", {},
        idempotency_key=f"validation-proposal-{VALIDATION_ID}",
    )
    bundle = request("GET", f"/api/v1/opportunities/{opportunity['id']}")
    mvp_run = bundle.get("mvp_run") or mvp_run
    proposal = bundle.get("proposal") or proposal
    if mvp_run.get("status") != "approved" or proposal.get("status") != "approved":
        state_key = f"{mvp_run.get('status', 'unknown')}-{proposal.get('status', 'unknown')}"
        request(
            "POST",
            f"/api/v1/opportunities/{opportunity['id']}/approve",
            {"comment": f"Human approval for the AI-native non-regulated {mission['name']} validation scope."},
            idempotency_key=f"validation-opportunity-approve-{VALIDATION_ID}-{state_key}",
        )
        bundle = request("GET", f"/api/v1/opportunities/{opportunity['id']}")
        mvp_run = bundle.get("mvp_run") or mvp_run
        proposal = bundle.get("proposal") or proposal
    if bundle.get("status") != "converted":
        request(
            "POST",
            f"/api/v1/opportunities/{opportunity['id']}/convert-to-delivery",
            {"confirmation": "activate approved proposal"},
            idempotency_key=f"validation-convert-{VALIDATION_ID}-{bundle.get('status', 'unknown')}",
        )
    run = request(
        "POST",
        f"/api/v1/mvp-runs/{mvp_run['id']}/create-asf-run",
        {},
        idempotency_key=f"validation-asf-run-{VALIDATION_ID}",
    )
    for retry_index in range(1, 11):
        current = request("GET", f"/runs/{run['id']}")
        if current.get("status") not in {"failed", "cancelled"}:
            run = current
            break
        run = request(
            "POST",
            f"/api/v1/mvp-runs/{mvp_run['id']}/create-asf-run",
            {},
            idempotency_key=f"validation-asf-run-{VALIDATION_ID}-retry-{retry_index}",
        )
    if not run.get("temporal_workflow_id"):
        raise RuntimeError("Contracted AI-native run was committed without a Temporal workflow id")
    if run.get("workflow_id") != "software_factory_ai_native_v2" or run.get("generation_mode") != "ai_native_v2":
        raise RuntimeError(f"Unexpected run executor: {run.get('workflow_id')} / {run.get('generation_mode')}")
    if os.environ.get("ASF_VALIDATION_OUTPUT") == "json":
        print(json.dumps({
            "run_id": run["id"],
            "mission": MISSION_KEY,
            "proposal_sha256": hashlib.sha256(str(proposal.get("content") or "").encode()).hexdigest(),
        }))
    else:
        print(run["id"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"contracted reference validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
