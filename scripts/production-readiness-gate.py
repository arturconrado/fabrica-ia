#!/usr/bin/env python3
"""Fail-closed final gate for a production release candidate.

This command does not create evidence, approve reports, or mutate the factory.
It verifies evidence produced by the real E2E journeys and exits successfully
only when every automated, human, load and market-readiness gate is terminal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOAD_PROFILES = {
    "baseline-2": (2, 60),
    "load-20": (20, 120),
    "load-50": (50, 120),
    "stress-200": (200, 120),
    "spike-500": (500, 30),
    "soak-20": (20, 8 * 60 * 60),
}
MARKET_REPORTS = {"real_canary", "operational_slo", "external_user_validation"}
PILOT_REQUIRED_LOAD_PROFILES = {"baseline-2", "load-20", "load-50", "soak-20"}
OPERATIONAL_PATHS = {
    "/api/v1/service-catalog/offerings",
    "/api/v1/operator/capacity",
    "/api/v1/operator/work-queue",
    "/api/v1/engagements",
    "/api/v1/client-operations/overview",
    "/api/v1/review/inbox",
    "/api/v1/service-deliverables",
}
EXPECTED_EVIDENCE_PATHS = {
    "playwright.json",
    "backup-restore/backup-restore.json",
    "backup-restore/restore-log.txt",
    *(f"load/portfolio-v2-{profile}.json" for profile in LOAD_PROFILES),
    "agentic-journey-evaluation.json",
    "commercial-ai-case-evaluation.json",
    "workflow-candidate-evaluation.json",
    "credential-rotation.json",
}
HEX_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    detail: str
    evidence: list[str]


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_evidence_manifest(
    path: Path,
    *,
    evidence_root: Path,
    expected_run_id: str,
    release_tenant_id: str,
) -> GateResult:
    failures: list[str] = []
    evidence = [str(path)]
    try:
        manifest = read_json(path)
        rows = manifest.get("evidence_files") or []
        row_by_path = {
            str(row.get("path") or ""): row for row in rows if isinstance(row, dict)
        }
        checks = {
            "schema": manifest.get("schema_version") == "production-evidence-manifest/1.0",
            "run_id": bool(expected_run_id) and manifest.get("verification_id") == expected_run_id,
            "commit_sha": bool(HEX_SHA.fullmatch(str(manifest.get("commit_sha") or ""))),
            "runtime_profile": manifest.get("runtime_profile") == "homologation",
            "provider_real": str(manifest.get("agent_provider") or "") not in {"", "mock", "synthetic"},
            "workflow_backend": manifest.get("workflow_backend") == "temporal",
            "tenant": bool(release_tenant_id)
            and manifest.get("release_tenant_id") == release_tenant_id
            and release_tenant_id.casefold().startswith(("release-", "homologation-")),
            "operator": bool(str(manifest.get("operator") or "").strip()),
            "credential_source": manifest.get("credential_source") == "secret_or_environment",
            "credentials_not_persisted": manifest.get("credentials_persisted") is False,
            "expected_inventory": EXPECTED_EVIDENCE_PATHS.issubset(set(row_by_path)),
        }
        failures.extend(key for key, passed in checks.items() if not passed)
        root = evidence_root.resolve()
        for relative in sorted(EXPECTED_EVIDENCE_PATHS):
            row = row_by_path.get(relative) or {}
            candidate = (root / relative).resolve()
            if root not in candidate.parents or candidate == root:
                failures.append(f"unsafe_path:{relative}")
                continue
            evidence.append(str(candidate))
            if row.get("exists") is not True or not candidate.is_file():
                failures.append(f"missing:{relative}")
                continue
            actual_hash = _file_sha256(candidate)
            if row.get("sha256") != actual_hash:
                failures.append(f"hash_mismatch:{relative}")
            if int(row.get("size_bytes") or -1) != candidate.stat().st_size:
                failures.append(f"size_mismatch:{relative}")
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        failures.append(f"manifest_unavailable:{exc}")
    return GateResult(
        "evidence_manifest",
        not failures,
        "all evidence is inventoried and hash-bound to the release run"
        if not failures else "; ".join(failures),
        evidence,
    )


def validate_load_evidence(
    load_dir: Path,
    expected_run_id: str = "",
    portfolio_version: str = "2.1",
    target: str = "market_ready",
    release_tenant_id: str = "",
) -> GateResult:
    failures: list[str] = []
    evidence: list[str] = []
    for profile, (users, seconds) in LOAD_PROFILES.items():
        path = load_dir / f"portfolio-v2-{profile}.json"
        evidence.append(str(path))
        try:
            report = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"{profile}: evidence unavailable ({exc})")
            continue
        required_for_pilot = profile in PILOT_REQUIRED_LOAD_PROFILES
        checks = {
            "schema": report.get("schema_version") == "service-portfolio-load-v2",
            "portfolio_version": report.get("portfolio_version") == portfolio_version,
            "run_id": not expected_run_id
            or report.get("production_e2e_run_id") == expected_run_id,
            "profile": report.get("profile") == profile,
            "users": report.get("virtual_users") == users,
            "full_duration": float(report.get("duration_scale") or 0) == 1.0
            and float(report.get("duration_seconds") or 0) >= seconds * 0.95,
            "personas": set(report.get("personas") or []) == {"owner", "vp"},
            "idempotency": bool((report.get("command_probe") or {}).get("passed")),
            "db_pool_observed": int((report.get("db_pool") or {}).get("observations") or 0) > 0,
            "pilot_classification": report.get("required_for_pilot") is required_for_pilot,
            "scale_classification": report.get("required_for_production_scale") is True,
            "release_metadata": not release_tenant_id or bool(
                report.get("environment") == "homologation"
                and report.get("tenant_id") == release_tenant_id
                and HEX_SHA.fullmatch(str(report.get("commit_sha") or ""))
                and report.get("command") == f"portfolio-load-test.py --profile {profile}"
            ),
        }
        by_path = report.get("by_path") or {}
        checks["operational_paths"] = OPERATIONAL_PATHS.issubset(set(by_path)) and all(
            int((by_path.get(path) or {}).get("requests") or 0) > 0
            and int((by_path.get(path) or {}).get("unexpected_failures") or 0) == 0
            and float((by_path.get(path) or {}).get("timeout_rate") or 0) <= 0.03
            and float(((by_path.get(path) or {}).get("latency_ms") or {}).get("p95") or 0) <= 5000
            for path in OPERATIONAL_PATHS
        )
        if profile == "soak-20":
            authentication = report.get("authentication") or {}
            checks["renewable_authentication"] = all(
                bool((authentication.get(persona) or {}).get("renewable"))
                and int((authentication.get(persona) or {}).get("token_renewals") or 0) >= 1
                for persona in ("owner", "vp")
            )
        performance_checks = {
            "status": report.get("status") == "passed"
            or (
                target == "internal_assisted_pilot_ready"
                and profile == "load-50"
                and report.get("status") == "passed_with_observations"
            ),
            "timeouts": float(report.get("timeout_rate", 1)) <= 0.03,
            "provider_errors": float(report.get("provider_error_rate", 1)) <= 0.05,
            "unexpected_failures": int(report.get("unexpected_failures") or 0) == 0,
            "p95": float((report.get("latency_ms") or {}).get("p95") or 0) <= 5000,
            "operational_paths": checks.pop("operational_paths"),
        }
        if target == "market_ready" or required_for_pilot:
            checks.update(performance_checks)
        failed_checks = [name for name, passed in checks.items() if not passed]
        if failed_checks:
            failures.append(f"{profile}: {', '.join(failed_checks)}")
    return GateResult(
        name="load_profiles",
        passed=not failures,
        detail=(
            "four pilot profiles passed; stress-200 and spike-500 evidence is informational"
            if not failures and target == "internal_assisted_pilot_ready"
            else "all six scale profiles passed at full duration"
            if not failures
            else "; ".join(failures)
        ),
        evidence=evidence,
    )


def validate_playwright_evidence(
    path: Path,
    minimum_tests: int,
    expected_run_id: str = "",
    release_tenant_id: str = "",
) -> GateResult:
    try:
        report = read_json(path)
        stats = report.get("stats") or {}
        expected = int(stats.get("expected") or 0)
        skipped = int(stats.get("skipped") or 0)
        unexpected = int(stats.get("unexpected") or 0)
        flaky = int(stats.get("flaky") or 0)
        report_run_id = str(
            ((report.get("config") or {}).get("metadata") or {}).get("productionE2ERunId")
            or ""
        )
        run_id_matches = not expected_run_id or report_run_id == expected_run_id
        release_metadata = not release_tenant_id or bool(
            report.get("schema_version") == "playwright-release-evidence/1.0"
            and report.get("status") == "passed"
            and report.get("environment") == "homologation"
            and report.get("tenant_id") == release_tenant_id
            and HEX_SHA.fullmatch(str(report.get("commit_sha") or ""))
            and report.get("command") == "npm run test:e2e:release"
            and float(report.get("duration_seconds") or 0) > 0
            and int(report.get("critical_failures") or 0) == 0
        )
        passed = (
            expected >= minimum_tests
            and skipped == 0
            and unexpected == 0
            and flaky == 0
            and run_id_matches
            and release_metadata
        )
        detail = (
            f"expected={expected}, skipped={skipped}, unexpected={unexpected}, flaky={flaky}, "
            f"minimum={minimum_tests}, run_id_matches={run_id_matches}, "
            f"release_metadata={release_metadata}"
        )
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        passed = False
        detail = f"evidence unavailable ({exc})"
    return GateResult("playwright_release", passed, detail, [str(path)])


def validate_backup_restore_evidence(
    path: Path, expected_run_id: str = "", release_tenant_id: str = ""
) -> GateResult:
    try:
        report = read_json(path)
        checks = {
            "schema": report.get("schema_version") == "local-backup-restore-v1",
            "run_id": not expected_run_id
            or report.get("production_e2e_run_id") == expected_run_id,
            "status": report.get("status") == "passed",
            "three_restores": int(report.get("restore_attempts") or 0) >= 3,
            "rpo_zero": int(report.get("rpo_lost_confirmed_outputs", -1)) == 0,
            "rto": float(report.get("rto_p95_seconds") or 301) <= 300,
            "ledger": report.get("ledger_valid") is True,
            "corruption": report.get("corrupt_backup_rejected_by_sha256") is True,
            "tampered_ledger": report.get("tampered_restore_rejected_by_ledger") is True,
            "sha256": len(str(report.get("backup_sha256") or "")) == 64,
            "release_metadata": not release_tenant_id or bool(
                report.get("environment") == "homologation"
                and report.get("tenant_id") == release_tenant_id
                and HEX_SHA.fullmatch(str(report.get("commit_sha") or ""))
                and report.get("command") == "local-backup-restore-drill.sh"
                and float(report.get("duration_seconds") or 0) > 0
            ),
        }
        failed = [name for name, value in checks.items() if not value]
        return GateResult(
            "backup_restore", not failed,
            "three restores passed with RPO zero" if not failed else ", ".join(failed),
            [str(path)],
        )
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        return GateResult("backup_restore", False, f"evidence unavailable ({exc})", [str(path)])


def validate_evaluation_report(
    path: Path,
    *,
    name: str,
    schema_version: str,
    portfolio_version: str,
    expected_run_id: str = "",
    release_tenant_id: str = "",
) -> GateResult:
    try:
        report = read_json(path)
        checks = {
            "schema": report.get("schema_version") == schema_version,
            "portfolio_version": report.get("portfolio_version") == portfolio_version,
            "run_id": not expected_run_id
            or report.get("production_e2e_run_id") == expected_run_id,
            "passed": report.get("passed") is True,
            "no_blockers": not (report.get("blockers") or []),
            "human_release": report.get("release_decision") == "human_required",
            "release_metadata": not release_tenant_id or bool(
                report.get("environment") == "homologation"
                and report.get("tenant_id") == release_tenant_id
                and HEX_SHA.fullmatch(str(report.get("commit_sha") or ""))
                and str(report.get("command") or "").strip()
                and float(report.get("duration_seconds") or 0) >= 0
            ),
        }
        failed = [key for key, value in checks.items() if not value]
        return GateResult(
            name,
            not failed,
            "provider-real evaluation passed; human release required"
            if not failed else ", ".join(failed),
            [str(path)],
        )
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        return GateResult(name, False, f"evidence unavailable ({exc})", [str(path)])


def validate_credential_rotation(
    path: Path, *, expected_run_id: str, release_tenant_id: str
) -> GateResult:
    try:
        report = read_json(path)
        checks = {
            "schema": report.get("schema_version") == "release-credential-rotation/1.0",
            "passed": report.get("status") == "passed",
            "run_id": bool(expected_run_id)
            and report.get("production_e2e_run_id") == expected_run_id,
            "tenant": bool(release_tenant_id) and report.get("tenant_id") == release_tenant_id,
            "client": report.get("oauth_client_id") == "software-factory-release",
            "secret_not_recorded": report.get("secret_recorded") is False,
            "commit_sha": bool(HEX_SHA.fullmatch(str(report.get("commit_sha") or ""))),
            "operator": bool(str(report.get("operator") or "").strip()),
        }
        failed = [key for key, value in checks.items() if not value]
        return GateResult(
            "release_credential_rotation",
            not failed,
            "release client secret rotated after the evidence cycle"
            if not failed else ", ".join(failed),
            [str(path)],
        )
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        return GateResult(
            "release_credential_rotation", False,
            f"evidence unavailable ({exc})", [str(path)],
        )


def request_json(base_url: str, path: str, token: str, tenant_id: str, timeout: float) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers.update({"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id})
    request = urllib.request.Request(f"{base_url.rstrip('/')}{path}", headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"HTTP {response.status}")
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError("API response root must be an object")
    return value


def validate_api(
    base_url: str,
    token: str,
    tenant_id: str,
    timeout: float,
    target: str = "market_ready",
    portfolio_version: str = "2.1",
    cost_cap_usd: float = 50.0,
) -> list[GateResult]:
    results: list[GateResult] = []
    try:
        health = request_json(base_url, "/health", "", "", timeout)
        results.append(GateResult("api_health", health.get("status") == "ok", str(health), [f"{base_url}/health"]))
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        results.append(GateResult("api_health", False, str(exc), [f"{base_url}/health"]))

    if not token or not tenant_id:
        results.append(GateResult(
            f"portfolio_{target}", False,
            "ASF_RELEASE_BEARER_TOKEN and ASF_RELEASE_TENANT_ID are required",
            [f"{base_url}/api/v1/service-catalog/versions/{portfolio_version}/readiness"],
        ))
        results.extend([
            GateResult(f"persisted_{target}_evaluation", False, "release credentials are required", []),
            GateResult("provider_cost_cap", False, "release credentials are required", []),
        ])
        return results
    try:
        session = request_json(base_url, "/auth/session", token, tenant_id, timeout)
        me = session.get("me") or {}
        tenant = next(
            (item for item in session.get("tenants") or [] if item.get("id") == tenant_id),
            {},
        )
        configuration = tenant.get("runtime_configuration_json") or {}
        identity_checks = {
            "tenant_scope": me.get("tenant_id") == tenant_id,
            "service_role": me.get("role") == "release_validator",
            "oidc": me.get("auth_mode") == "oidc",
            "oauth_client": me.get("token_client_id") == "software-factory-release",
            "release_tenant": configuration.get("tenant_purpose") == "release_homologation",
            "homologation_environment": configuration.get("environment") == "homologation",
            "no_customer_data": configuration.get("customer_data_allowed") is False,
            "synthetic_only": configuration.get("synthetic_data_only") is True,
        }
        failed_identity_checks = [key for key, value in identity_checks.items() if not value]
        results.append(GateResult(
            "release_service_account",
            not failed_identity_checks,
            "dedicated least-privilege release identity"
            if not failed_identity_checks else ", ".join(failed_identity_checks),
            [f"{base_url}/auth/session"],
        ))
    except (OSError, ValueError, RuntimeError, StopIteration, urllib.error.URLError) as exc:
        results.append(GateResult(
            "release_service_account", False, str(exc), [f"{base_url}/auth/session"],
        ))
    try:
        readiness = request_json(
            base_url,
            f"/api/v1/service-catalog/versions/{portfolio_version}/readiness",
            token,
            tenant_id,
            timeout,
        )
        market_reports = readiness.get("market_validation_reports") or []
        report_kinds = {
            str(item.get("report_kind")) for item in market_reports
            if isinstance(item, dict) and item.get("passed") is True
        }
        internal_ready = bool(
            readiness.get("internal_assisted_pilot_ready") is True
            and readiness.get("four_eyes_verified") is True
            and not readiness.get("release_blockers")
        )
        if target == "internal_assisted_pilot_ready":
            passed = internal_ready
        else:
            passed = bool(
                internal_ready
                and readiness.get("market_ready") is True
                and not readiness.get("market_blockers")
                and MARKET_REPORTS.issubset(report_kinds)
            )
        detail = json.dumps({
            "internal_assisted_pilot_ready": readiness.get("internal_assisted_pilot_ready"),
            "market_ready": readiness.get("market_ready"),
            "four_eyes_verified": readiness.get("four_eyes_verified"),
            "release_blockers": readiness.get("release_blockers") or [],
            "market_blockers": readiness.get("market_blockers") or [],
        }, ensure_ascii=False, sort_keys=True)
        results.append(GateResult(
            f"portfolio_{target}", passed, detail,
            [f"{base_url}/api/v1/service-catalog/versions/{portfolio_version}/readiness"],
        ))
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        results.append(GateResult(
            f"portfolio_{target}", False, str(exc),
            [f"{base_url}/api/v1/service-catalog/versions/{portfolio_version}/readiness"],
        ))
    try:
        platform = request_json(base_url, "/api/v1/admin/platform-readiness", token, tenant_id, timeout)
        evaluations = [
            item for item in platform.get("evaluations") or []
            if isinstance(item, dict)
            and item.get("evaluation_type") == target
            and (item.get("metrics_json") or {}).get("portfolio_version") == portfolio_version
        ]
        latest = evaluations[0] if evaluations else {}
        metrics = latest.get("metrics_json") or {}
        hashes = latest.get("evidence_hashes_json") or []
        passed = bool(
            latest.get("status") == "passed"
            and latest.get("approved_by_user_id")
            and metrics.get("four_eyes_verified") is True
            and hashes
            and not (latest.get("blockers_json") or [])
        )
        results.append(GateResult(
            f"persisted_{target}_evaluation", passed,
            json.dumps({
                "status": latest.get("status"),
                "four_eyes_verified": metrics.get("four_eyes_verified"),
                "evidence_hash_count": len(hashes),
                "blockers": latest.get("blockers_json") or [],
            }, ensure_ascii=False, sort_keys=True),
            [f"{base_url}/api/v1/admin/platform-readiness"],
        ))
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        results.append(GateResult(
            f"persisted_{target}_evaluation", False, str(exc),
            [f"{base_url}/api/v1/admin/platform-readiness"],
        ))
    try:
        costs = request_json(base_url, "/api/v1/operator/ai-cost-analysis?group_by=tenant", token, tenant_id, timeout)
        actual_cost = (costs.get("totals") or {}).get("actual_cost_usd")
        passed = actual_cost is not None and 0 <= float(actual_cost) <= cost_cap_usd
        results.append(GateResult(
            "provider_cost_cap", passed,
            f"actual_cost_usd={actual_cost}; cap={cost_cap_usd:g}",
            [f"{base_url}/api/v1/operator/ai-cost-analysis?group_by=tenant"],
        ))
    except (OSError, ValueError, RuntimeError, TypeError, urllib.error.URLError) as exc:
        results.append(GateResult(
            "provider_cost_cap", False, str(exc),
            [f"{base_url}/api/v1/operator/ai-cost-analysis?group_by=tenant"],
        ))
    return results


def write_report(results: list[GateResult], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    passed = all(result.passed for result in results)
    payload = {
        "schema_version": "production-readiness-gate-v2",
        "generated_at": generated_at,
        "status": "passed" if passed else "failed",
        "gates": [asdict(result) for result in results],
    }
    json_path = output_dir / "production-readiness-gate.json"
    markdown_path = output_dir / "production-readiness-gate.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = "\n".join(
        f"| {result.name} | {'PASSOU' if result.passed else 'FALHOU'} | {result.detail.replace('|', '/')} |"
        for result in results
    )
    markdown_path.write_text(
        "# Production readiness gate\n\n"
        f"- Generated at: `{generated_at}`\n"
        f"- Status: **{'PASSOU' if passed else 'FALHOU'}**\n\n"
        "| Gate | Resultado | Detalhe |\n| --- | --- | --- |\n"
        f"{rows}\n\n"
        "Este relatório agrega evidência; não cria aprovação humana nem promove o catálogo.\n",
        encoding="utf-8",
    )
    return json_path, markdown_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("ASF_RELEASE_API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--load-dir", type=Path, default=Path("artifacts/portfolio-v2/load"))
    parser.add_argument("--playwright-report", type=Path, default=Path("artifacts/production-readiness/playwright.json"))
    parser.add_argument("--backup-restore-report", type=Path, default=Path("artifacts/production-readiness/backup-restore/backup-restore.json"))
    parser.add_argument("--agentic-journey-report", type=Path, default=Path("artifacts/production-readiness/agentic-journey-evaluation.json"))
    parser.add_argument("--commercial-ai-case-report", type=Path, default=Path("artifacts/production-readiness/commercial-ai-case-evaluation.json"))
    parser.add_argument("--workflow-candidate-report", type=Path, default=Path("artifacts/production-readiness/workflow-candidate-evaluation.json"))
    parser.add_argument("--manifest", type=Path, default=Path("artifacts/production-readiness/manifest.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/production-readiness/latest"))
    parser.add_argument("--minimum-playwright-tests", type=int, default=10)
    parser.add_argument("--run-id", default=os.getenv("ASF_PRODUCTION_E2E_RUN_ID", ""))
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--portfolio-version",
        choices=("2.0", "2.1"),
        default=os.getenv("ASF_PORTFOLIO_VERSION", "2.1"),
    )
    parser.add_argument(
        "--cost-cap-usd",
        type=float,
        default=float(os.getenv("ASF_PRODUCTION_E2E_COST_CAP_USD", "50")),
    )
    parser.add_argument(
        "--target",
        choices=("internal_assisted_pilot_ready", "market_ready"),
        default="market_ready",
    )
    parser.add_argument("--allow-remote", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    parsed = urllib.parse.urlparse(args.base_url)
    if parsed.scheme not in {"http", "https"}:
        raise SystemExit("--base-url must use http or https")
    if not args.allow_remote and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("Remote release checks require --allow-remote and explicit authorization")
    if not 0 < args.cost_cap_usd <= 50:
        raise SystemExit("--cost-cap-usd must be > 0 and <= 50")
    results = [
        validate_evidence_manifest(
            args.manifest,
            evidence_root=args.manifest.parent,
            expected_run_id=args.run_id,
            release_tenant_id=os.getenv("ASF_RELEASE_TENANT_ID", "").strip(),
        ),
        *validate_api(
            args.base_url,
            os.getenv("ASF_RELEASE_BEARER_TOKEN", "").strip(),
            os.getenv("ASF_RELEASE_TENANT_ID", "").strip(),
            args.timeout,
            args.target,
            args.portfolio_version,
            args.cost_cap_usd,
        ),
        validate_playwright_evidence(
            args.playwright_report,
            args.minimum_playwright_tests,
            args.run_id,
            os.getenv("ASF_RELEASE_TENANT_ID", "").strip(),
        ),
        validate_backup_restore_evidence(
            args.backup_restore_report,
            args.run_id,
            os.getenv("ASF_RELEASE_TENANT_ID", "").strip(),
        ),
        validate_load_evidence(
            args.load_dir, args.run_id, args.portfolio_version, args.target,
            os.getenv("ASF_RELEASE_TENANT_ID", "").strip(),
        ),
        validate_credential_rotation(
            args.manifest.parent / "credential-rotation.json",
            expected_run_id=args.run_id,
            release_tenant_id=os.getenv("ASF_RELEASE_TENANT_ID", "").strip(),
        ),
        validate_evaluation_report(
            args.agentic_journey_report,
            name="agentic_journeys",
            schema_version="agentic-journey-evaluation-report/1.0",
            portfolio_version=args.portfolio_version,
            expected_run_id=args.run_id,
            release_tenant_id=os.getenv("ASF_RELEASE_TENANT_ID", "").strip(),
        ),
        validate_evaluation_report(
            args.commercial_ai_case_report,
            name="commercial_ai_case",
            schema_version="commercial-ai-case-evaluation-report/1.0",
            portfolio_version=args.portfolio_version,
            expected_run_id=args.run_id,
            release_tenant_id=os.getenv("ASF_RELEASE_TENANT_ID", "").strip(),
        ),
    ]
    if args.portfolio_version == "2.1":
        results.append(validate_evaluation_report(
            args.workflow_candidate_report,
            name="workflow_candidate_2_14",
            schema_version="workflow-candidate-evaluation/1.0",
            portfolio_version=args.portfolio_version,
            expected_run_id=args.run_id,
            release_tenant_id=os.getenv("ASF_RELEASE_TENANT_ID", "").strip(),
        ))
    json_path, markdown_path = write_report(results, args.output_dir)
    print(json.dumps({
        "status": "passed" if all(result.passed for result in results) else "failed",
        "json_report": str(json_path),
        "markdown_report": str(markdown_path),
    }, ensure_ascii=False))
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
