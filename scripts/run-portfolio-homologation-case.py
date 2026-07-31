#!/usr/bin/env python3
"""Operate the first real Portfolio 2.1 homologation case through public APIs.

The runner is resumable from server state, never stores credentials and keeps
owner and engagement-manager decisions in separate explicit actions.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_DIR = REPO_ROOT / "homologation/cases/portfolio-v2/commercial-opportunity-copilot"
OFFERING_CODES = {
    "ai_value_discovery",
    "ai_governance_risk_framework",
    "ai_enterprise_launchpad",
    "ai_workforce_productivity_accelerator",
    "ai_engineering_productivity_accelerator",
    "ai_use_case_pilot_sprint",
    "ai_office_as_a_service",
    "ai_adoption_kit_governance_cockpit",
}
QUEUE_CONFIRMATION = "QUEUE_REAL_PROVIDER_WORK"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("validate", "bootstrap", "plan", "approve", "activate", "queue", "status"),
        help="One auditable case transition to execute.",
    )
    parser.add_argument("--base-url", default=os.getenv("ASF_HOMOLOGATION_API_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--tenant-id", default=os.getenv("ASF_HOMOLOGATION_TENANT_ID", ""))
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument(
        "--instance-id",
        default="",
        help=(
            "Create or resume an isolated instance of the canonical case. "
            "The suffix is applied to the case, contract, engagement and knowledge base identifiers."
        ),
    )
    parser.add_argument(
        "--reuse-canonical-knowledge",
        action="store_true",
        help=(
            "Reuse the canonical same-tenant knowledge base for a new instance. "
            "Contract, engagement, documents and decisions remain independently identified."
        ),
    )
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def load_case(case_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    case_file = case_dir / "case.json"
    dataset_file = case_dir / "evaluation-dataset.jsonl"
    evaluation_inputs_file = case_dir / "evaluation-inputs.jsonl"
    rubric_file = case_dir / "evaluation-rubric.md"
    portfolio_file = REPO_ROOT / "apps/api/app/service_delivery/portfolio_v2.yaml"
    try:
        case_text = case_file.read_text(encoding="utf-8")
        dataset_text = dataset_file.read_text(encoding="utf-8")
        evaluation_inputs_text = evaluation_inputs_file.read_text(encoding="utf-8")
        rubric_text = rubric_file.read_text(encoding="utf-8")
        portfolio_text = portfolio_file.read_text(encoding="utf-8")
        case = json.loads(case_text)
        dataset = [json.loads(line) for line in dataset_text.splitlines() if line.strip()]
        evaluation_inputs = [
            json.loads(line) for line in evaluation_inputs_text.splitlines() if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid homologation case bundle: {exc}") from exc
    if any("expected_primary_offering" in row for row in evaluation_inputs):
        raise RuntimeError("Held-out labels must never appear in evaluation-inputs.jsonl")
    if {row.get("id") for row in evaluation_inputs} != {row.get("id") for row in dataset}:
        raise RuntimeError("Evaluation inputs and held-out labels must cover the same case ids")
    return case, dataset, {
        "case.json": case_text,
        "evaluation-inputs.jsonl": evaluation_inputs_text,
        "evaluation-rubric.md": rubric_text,
        "portfolio_v2.yaml": portfolio_text,
    }


def instantiate_case(
    case: dict[str, Any],
    instance_id: str,
    *,
    reuse_canonical_knowledge: bool = False,
) -> dict[str, Any]:
    instance_id = instance_id.strip()
    if not instance_id:
        return case
    if len(instance_id) > 64 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", instance_id):
        raise RuntimeError(
            "--instance-id must be 1-64 characters using only letters, numbers, dot, underscore or hyphen"
        )
    result = copy.deepcopy(case)
    result["case_id"] = f"{case['case_id']}-{instance_id}"
    result["name"] = f"{case['name']} · {instance_id}"
    result["contract"]["number"] = f"{case['contract']['number']}-{instance_id}"
    result["contract"]["commercial_metadata"]["instance_id"] = instance_id
    result["engagement"]["name"] = f"{case['engagement']['name']} · {instance_id}"
    result["engagement"]["service_levels"]["instance_id"] = instance_id
    if not reuse_canonical_knowledge:
        result["knowledge_base"]["name"] = f"{case['knowledge_base']['name']} · {instance_id}"
    return result


def validate_case(case: dict[str, Any], dataset: list[dict[str, Any]]) -> dict[str, Any]:
    required = {
        "schema_version", "case_id", "name", "real_operation", "offering", "program",
        "contract", "engagement", "knowledge_base", "product", "adaptation_brief",
        "technical_execution_instructions", "release_rule", "ai_native_quality",
        "agentic_production",
    }
    missing = sorted(required - case.keys())
    if missing:
        raise RuntimeError(f"Case is missing required fields: {missing}")
    if case["real_operation"] is not True or case["offering"].get("version") != "2.1":
        raise RuntimeError("Case must be a real operation contracted against Portfolio 2.1")
    expected_cases = int(case["ai_native_quality"]["evaluation_dataset"]["cases"])
    if len(dataset) != expected_cases or len({row.get("id") for row in dataset}) != expected_cases:
        raise RuntimeError(
            f"Evaluation dataset must contain exactly {expected_cases} unique scenarios"
        )
    counts = Counter(str(row.get("expected_primary_offering") or "") for row in dataset)
    expected_per_offering = expected_cases // len(OFFERING_CODES)
    if (
        expected_cases % len(OFFERING_CODES)
        or set(counts) != OFFERING_CODES
        or any(counts[code] != expected_per_offering for code in OFFERING_CODES)
    ):
        raise RuntimeError(
            "Evaluation dataset must cover each of the eight offerings equally"
        )
    adversarial = [row for row in dataset if row.get("adversarial_tags")]
    minimum_adversarial = int(
        case["ai_native_quality"]["evaluation_dataset"]["minimum_adversarial_cases"]
    )
    if len(adversarial) < minimum_adversarial:
        raise RuntimeError(
            f"Evaluation dataset requires at least {minimum_adversarial} adversarial scenarios"
        )
    if any(not row.get("expected_safety_behavior") for row in adversarial):
        raise RuntimeError("Every adversarial scenario requires an expected safety behavior")
    return {
        "status": "valid",
        "case_id": case["case_id"],
        "offering": case["offering"],
        "evaluation_scenarios": len(dataset),
        "adversarial_scenarios": len(adversarial),
        "held_out_labels": True,
        "offering_coverage": dict(sorted(counts.items())),
    }


class ApiClient:
    def __init__(self, base_url: str, token: str, tenant_id: str, timeout: int):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.tenant_id = tenant_id
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        idempotency_key: str = "",
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "X-Tenant-ID": self.tenant_id,
            "Content-Type": "application/json",
            "X-Correlation-ID": "portfolio-homologation-commercial-v1",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{method} {path} transport failed: {exc.reason}") from exc
        if not response_body:
            return None
        try:
            return json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{method} {path} returned invalid JSON") from exc


def token_from_environment(name: str) -> str:
    token = os.getenv(name, "").strip()
    if not token:
        raise RuntimeError(f"{name} is required for this action and is never persisted")
    return token


def client_for(args: argparse.Namespace, role: str) -> ApiClient:
    if not args.tenant_id.strip():
        raise RuntimeError("ASF_HOMOLOGATION_TENANT_ID or --tenant-id is required")
    env_name = "ASF_HOMOLOGATION_OWNER_TOKEN" if role == "owner" else "ASF_HOMOLOGATION_VP_TOKEN"
    client = ApiClient(args.base_url, token_from_environment(env_name), args.tenant_id.strip(), args.timeout)
    principal = client.request("GET", "/auth/me")
    actual_role = str(principal.get("role") or "")
    if role == "owner" and actual_role not in {"owner", "super_admin"}:
        raise RuntimeError(f"Owner action requires owner/super_admin, received {actual_role!r}")
    if role == "engagement_manager" and actual_role != "engagement_manager":
        raise RuntimeError(f"VP action requires engagement_manager, received {actual_role!r}")
    return client


def matching(rows: list[dict[str, Any]], key: str, value: Any) -> dict[str, Any] | None:
    return next((row for row in rows if row.get(key) == value), None)


def state(client: ApiClient, case: dict[str, Any]) -> dict[str, Any]:
    offerings = client.request("GET", "/api/v1/service-catalog/offerings")
    offering = next(
        (
            row for row in offerings
            if row.get("code") == case["offering"]["code"] and row.get("version") == case["offering"]["version"]
        ),
        None,
    )
    knowledge_base = matching(
        client.request("GET", "/api/v1/knowledge-bases"), "name", case["knowledge_base"]["name"]
    )
    program = matching(client.request("GET", "/api/v1/programs"), "name", case["program"]["name"])
    contract = matching(
        client.request("GET", "/api/v1/contracts"), "contract_number", case["contract"]["number"]
    )
    entitlement = next(
        (
            row for row in client.request("GET", "/api/v1/entitlements")
            if contract and row.get("contract_id") == contract.get("id")
            and row.get("component_code") == case["offering"]["component_code"]
        ),
        None,
    )
    engagement = matching(
        client.request("GET", "/api/v1/engagements"), "name", case["engagement"]["name"]
    )
    bundle = (
        client.request("GET", f"/api/v1/engagements/{engagement['id']}") if engagement else None
    )
    return {
        "offering": offering,
        "knowledge_base": knowledge_base,
        "program": program,
        "contract": contract,
        "entitlement": entitlement,
        "engagement": bundle or engagement,
    }


def bootstrap(client: ApiClient, case: dict[str, Any], sources: dict[str, str]) -> dict[str, Any]:
    current = state(client, case)
    if not current["offering"]:
        raise RuntimeError("AI Use Case Pilot 2.1 is not available in the service catalog")
    if not current["knowledge_base"]:
        current["knowledge_base"] = client.request(
            "POST",
            "/api/v1/knowledge-bases",
            case["knowledge_base"],
            idempotency_key=f"{case['case_id']}:knowledge-base",
        )
    existing_documents = client.request(
        "GET", f"/api/v1/knowledge-bases/{current['knowledge_base']['id']}/documents"
    )
    existing_refs = {row.get("source_ref") for row in existing_documents}
    existing_checksums = {row.get("checksum") for row in existing_documents}
    for filename, content in sources.items():
        source_ref = f"case://{case['case_id']}/{filename}"
        content_checksum = hashlib.sha256(content.replace("\r\n", "\n").strip().encode("utf-8")).hexdigest()
        if source_ref in existing_refs or content_checksum in existing_checksums:
            continue
        client.request(
            "POST",
            f"/api/v1/knowledge-bases/{current['knowledge_base']['id']}/documents",
            {
                "title": filename,
                "content": content,
                "source_type": "internal_homologation_case",
                "source_ref": source_ref,
                "metadata": {"case_id": case["case_id"], "real_operation": True},
            },
            idempotency_key=f"{case['case_id']}:document:{filename}",
        )
    if not current["program"]:
        current["program"] = client.request("POST", "/api/v1/programs", case["program"])
    if not current["contract"]:
        contract = case["contract"]
        current["contract"] = client.request(
            "POST",
            "/api/v1/contracts",
            {
                "contract_number": contract["number"],
                "status": "draft",
                "scope_summary": contract["scope_summary"],
                "commercial_metadata": contract["commercial_metadata"],
            },
        )
    if current["contract"].get("status") != "active":
        current["contract"] = client.request(
            "POST",
            f"/api/v1/contracts/{current['contract']['id']}/activate",
            {},
            idempotency_key=f"{case['case_id']}:contract-activate",
        )
    if not current["entitlement"]:
        contract = case["contract"]
        current["entitlement"] = client.request(
            "POST",
            f"/api/v1/contracts/{current['contract']['id']}/entitlements",
            {
                "component_code": case["offering"]["component_code"],
                "component_version": "1.0",
                "status": "granted",
                "limits": contract["limits"],
                "capabilities": contract["capabilities"],
                "terms": contract["terms"],
            },
        )
    if not current["engagement"]:
        engagement = case["engagement"]
        current["engagement"] = client.request(
            "POST",
            "/api/v1/engagements",
            {
                "contract_id": current["contract"]["id"],
                "offering_version_id": current["offering"]["version_id"],
                "program_id": current["program"]["id"],
                "name": engagement["name"],
                "description": engagement["description"],
                "sponsor": engagement["sponsor"],
                "success_criteria": engagement["success_criteria"],
                "service_levels": engagement["service_levels"],
            },
            idempotency_key=f"{case['case_id']}:engagement-create",
        )
    return state(client, case)


def require_bootstrapped(current: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in ("offering", "knowledge_base", "program", "contract", "entitlement", "engagement") if not current[key]]
    if missing:
        raise RuntimeError(f"Run bootstrap first; missing resources: {missing}")
    return current


def generate_plan(client: ApiClient, case: dict[str, Any]) -> dict[str, Any]:
    current = require_bootstrapped(state(client, case))
    engagement = current["engagement"]
    if engagement.get("latest_plan"):
        return current
    client.request(
        "POST",
        f"/api/v1/engagements/{engagement['id']}/plans/generate",
        {
            "expected_version": engagement["record_version"],
            "adaptation_brief": case["adaptation_brief"],
            "knowledge_base_ids": [current["knowledge_base"]["id"]],
        },
        idempotency_key=f"{case['case_id']}:plan-generate",
    )
    return state(client, case)


def approve_plan(client: ApiClient, case: dict[str, Any]) -> dict[str, Any]:
    current = require_bootstrapped(state(client, case))
    engagement = current["engagement"]
    plan = engagement.get("latest_plan")
    if not plan:
        raise RuntimeError("Generate the plan before VP approval")
    if plan.get("status") == "approved":
        return current
    client.request(
        "POST",
        f"/api/v1/engagements/{engagement['id']}/plans/{plan['version']}/approve",
        {
            "expected_version": engagement["record_version"],
            "comment": "VP reviewed scope, deliverables, risks and four-eyes responsibilities for the real internal pilot.",
        },
        idempotency_key=f"{case['case_id']}:plan-approve:{plan['version']}",
    )
    return state(client, case)


def activate(client: ApiClient, case: dict[str, Any]) -> dict[str, Any]:
    current = require_bootstrapped(state(client, case))
    engagement = current["engagement"]
    if engagement.get("status") == "active":
        return current
    if not engagement.get("latest_plan") or engagement["latest_plan"].get("status") != "approved":
        raise RuntimeError("VP approval is required before activation")
    client.request(
        "POST",
        f"/api/v1/engagements/{engagement['id']}/activate",
        {
            "expected_version": engagement["record_version"],
            "comment": "Activate the real internal homologation case after the independent VP plan decision.",
        },
        idempotency_key=f"{case['case_id']}:engagement-activate",
    )
    return state(client, case)


def queue_work(client: ApiClient, case: dict[str, Any], confirmation: str) -> dict[str, Any]:
    if confirmation != QUEUE_CONFIRMATION:
        raise RuntimeError(f"Paid provider work requires --confirm {QUEUE_CONFIRMATION}")
    current = require_bootstrapped(state(client, case))
    engagement = current["engagement"]
    if engagement.get("status") != "active":
        raise RuntimeError("Activate the engagement before queueing work")
    existing = {row["work_item_id"] for row in engagement.get("service_executions", [])}
    queued: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for item in engagement.get("work_items", []):
        mode = str(item.get("execution_mode") or "")
        if mode not in {"agent", "technical_run"} or item["id"] in existing or item.get("status") not in {"queued", "blocked"}:
            skipped.append({"id": item["id"], "mode": mode, "reason": "manual_or_already_queued"})
            continue
        if mode == "technical_run":
            instructions = case["technical_execution_instructions"]
        else:
            instructions = (
                f"Produza o entregável {item['title']} para o caso real {case['name']}. "
                "Use somente as fontes tenant-scoped anexadas, diferencie fatos de hipóteses, não invente ações concluídas "
                "e mantenha qualquer aprovação ou ação externa pendente de decisão humana."
            )
        execution = client.request(
            "POST",
            f"/api/v1/service-work-items/{item['id']}/execute",
            {
                "expected_version": item["record_version"],
                "instructions": instructions,
                "knowledge_base_ids": [current["knowledge_base"]["id"]],
            },
            idempotency_key=f"{case['case_id']}:execute:{item['id']}",
        )
        queued.append({"work_item_id": item["id"], "execution_id": execution["id"], "mode": mode})
    refreshed = state(client, case)
    return {**refreshed, "queue_result": {"queued": queued, "skipped": skipped}}


def summary(current: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    engagement = current.get("engagement") or {}
    executions = engagement.get("service_executions") or []
    return {
        "case_id": case["case_id"],
        "case_name": case["name"],
        "offering": {
            "code": (current.get("offering") or {}).get("code"),
            "version": (current.get("offering") or {}).get("version"),
            "status": (current.get("offering") or {}).get("version_status"),
        },
        "resources": {
            "knowledge_base_id": (current.get("knowledge_base") or {}).get("id"),
            "program_id": (current.get("program") or {}).get("id"),
            "contract_id": (current.get("contract") or {}).get("id"),
            "entitlement_id": (current.get("entitlement") or {}).get("id"),
            "engagement_id": engagement.get("id"),
        },
        "engagement_status": engagement.get("status"),
        "record_version": engagement.get("record_version"),
        "plan_status": (engagement.get("latest_plan") or {}).get("status"),
        "counts": engagement.get("counts") or {},
        "execution_statuses": dict(sorted(Counter(str(row.get("status")) for row in executions).items())),
    }


def main() -> int:
    args = parse_args()
    case, dataset, sources = load_case(args.case_dir.resolve())
    case = instantiate_case(
        case,
        args.instance_id,
        reuse_canonical_knowledge=args.reuse_canonical_knowledge,
    )
    validation = validate_case(case, dataset)
    if args.action == "validate":
        print(json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    role = "engagement_manager" if args.action == "approve" else "owner"
    client = client_for(args, role)
    if args.action == "bootstrap":
        current = bootstrap(client, case, sources)
    elif args.action == "plan":
        current = generate_plan(client, case)
    elif args.action == "approve":
        current = approve_plan(client, case)
    elif args.action == "activate":
        current = activate(client, case)
    elif args.action == "queue":
        current = queue_work(client, case, args.confirm)
    else:
        current = state(client, case)
    result = summary(current, case)
    if "queue_result" in current:
        result["queue_result"] = current["queue_result"]
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"portfolio homologation case failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
