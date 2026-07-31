from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "production-readiness-gate.py"
SPEC = importlib.util.spec_from_file_location("production_readiness_gate", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ProductionReadinessGateTests(unittest.TestCase):
    def test_manifest_hash_binds_every_required_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = []
            for relative in MODULE.EXPECTED_EVIDENCE_PATHS:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"real evidence: {relative}\n", encoding="utf-8")
                rows.append({
                    "path": relative,
                    "exists": True,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size_bytes": path.stat().st_size,
                })
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": "production-evidence-manifest/1.0",
                "verification_id": "current-run",
                "commit_sha": "a" * 40,
                "runtime_profile": "homologation",
                "agent_provider": "litellm",
                "workflow_backend": "temporal",
                "release_tenant_id": "release-validation",
                "operator": "release-owner",
                "credential_source": "secret_or_environment",
                "credentials_persisted": False,
                "evidence_files": rows,
            }), encoding="utf-8")
            self.assertTrue(MODULE.validate_evidence_manifest(
                manifest, evidence_root=root, expected_run_id="current-run",
                release_tenant_id="release-validation",
            ).passed)
            (root / next(iter(MODULE.EXPECTED_EVIDENCE_PATHS))).write_text("tampered", encoding="utf-8")
            self.assertFalse(MODULE.validate_evidence_manifest(
                manifest, evidence_root=root, expected_run_id="current-run",
                release_tenant_id="release-validation",
            ).passed)

    def test_credential_rotation_never_records_the_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential-rotation.json"
            path.write_text(json.dumps({
                "schema_version": "release-credential-rotation/1.0",
                "status": "passed",
                "production_e2e_run_id": "current-run",
                "tenant_id": "release-validation",
                "oauth_client_id": "software-factory-release",
                "secret_recorded": False,
                "commit_sha": "a" * 40,
                "operator": "release-owner",
            }), encoding="utf-8")
            self.assertTrue(MODULE.validate_credential_rotation(
                path, expected_run_id="current-run", release_tenant_id="release-validation",
            ).passed)
            report = json.loads(path.read_text(encoding="utf-8"))
            report["secret_recorded"] = True
            path.write_text(json.dumps(report), encoding="utf-8")
            self.assertFalse(MODULE.validate_credential_rotation(
                path, expected_run_id="current-run", release_tenant_id="release-validation",
            ).passed)

    def test_load_gate_requires_every_full_duration_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            load_dir = Path(directory)
            for profile, (users, seconds) in MODULE.LOAD_PROFILES.items():
                (load_dir / f"portfolio-v2-{profile}.json").write_text(json.dumps({
                    "schema_version": "service-portfolio-load-v2",
                    "portfolio_version": "2.1",
                    "production_e2e_run_id": "current-run",
                    "profile": profile,
                    "required_for_pilot": profile in MODULE.PILOT_REQUIRED_LOAD_PROFILES,
                    "required_for_production_scale": True,
                    "status": "passed",
                    "virtual_users": users,
                    "duration_scale": 1.0,
                    "duration_seconds": seconds,
                    "timeout_rate": 0.0,
                    "provider_error_rate": 0.0,
                    "unexpected_failures": 0,
                    "latency_ms": {"p95": 100.0},
                    "personas": ["owner", "vp"],
                    "authentication": {
                        "owner": {"renewable": True, "token_renewals": 1},
                        "vp": {"renewable": True, "token_renewals": 1},
                    },
                    "command_probe": {"passed": True},
                    "db_pool": {"observations": 1, "max_utilization_ratio": 0.5},
                    "by_path": {
                        path: {
                            "requests": 1, "unexpected_failures": 0, "timeout_rate": 0.0,
                            "latency_ms": {"p95": 100.0},
                        }
                        for path in MODULE.OPERATIONAL_PATHS
                    },
                }), encoding="utf-8")
            self.assertTrue(
                MODULE.validate_load_evidence(load_dir, "current-run").passed
            )
            baseline_path = load_dir / "portfolio-v2-baseline-2.json"
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline["production_e2e_run_id"] = "old-run"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            self.assertFalse(
                MODULE.validate_load_evidence(load_dir, "current-run").passed
            )
            baseline["production_e2e_run_id"] = "current-run"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            soak_path = load_dir / "portfolio-v2-soak-20.json"
            soak = json.loads(soak_path.read_text(encoding="utf-8"))
            soak["authentication"]["vp"]["token_renewals"] = 0
            soak_path.write_text(json.dumps(soak), encoding="utf-8")
            self.assertFalse(
                MODULE.validate_load_evidence(load_dir, "current-run").passed
            )
            soak["authentication"]["vp"]["token_renewals"] = 1
            soak_path.write_text(json.dumps(soak), encoding="utf-8")
            self.assertTrue(
                MODULE.validate_load_evidence(load_dir, "current-run").passed
            )
            (load_dir / "portfolio-v2-soak-20.json").unlink()
            self.assertFalse(
                MODULE.validate_load_evidence(load_dir, "current-run").passed
            )

    def test_pilot_requires_stress_and_spike_evidence_but_treats_results_as_informational(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            load_dir = Path(directory)
            for profile, (users, seconds) in MODULE.LOAD_PROFILES.items():
                informational = profile in {"stress-200", "spike-500"}
                (load_dir / f"portfolio-v2-{profile}.json").write_text(json.dumps({
                    "schema_version": "service-portfolio-load-v2",
                    "portfolio_version": "2.1",
                    "production_e2e_run_id": "current-run",
                    "profile": profile,
                    "status": "failed" if informational else "passed",
                    "required_for_pilot": not informational,
                    "required_for_production_scale": True,
                    "virtual_users": users,
                    "duration_scale": 1.0,
                    "duration_seconds": seconds,
                    "timeout_rate": 1.0 if informational else 0.0,
                    "provider_error_rate": 0.0,
                    "unexpected_failures": 1 if informational else 0,
                    "latency_ms": {"p95": 10_000 if informational else 100},
                    "personas": ["owner", "vp"],
                    "authentication": {
                        "owner": {"renewable": True, "token_renewals": 1},
                        "vp": {"renewable": True, "token_renewals": 1},
                    },
                    "command_probe": {"passed": True},
                    "db_pool": {"observations": 1},
                    "by_path": {
                        path: {"requests": 1, "unexpected_failures": 1 if informational else 0,
                               "timeout_rate": 1.0 if informational else 0.0,
                               "latency_ms": {"p95": 10_000 if informational else 100}}
                        for path in MODULE.OPERATIONAL_PATHS
                    },
                }), encoding="utf-8")
            self.assertTrue(MODULE.validate_load_evidence(
                load_dir, "current-run", target="internal_assisted_pilot_ready"
            ).passed)
            self.assertFalse(MODULE.validate_load_evidence(
                load_dir, "current-run", target="market_ready"
            ).passed)

    def test_playwright_gate_rejects_skips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playwright.json"
            path.write_text(json.dumps({
                "stats": {"expected": 9, "skipped": 1, "unexpected": 0, "flaky": 0}
            }), encoding="utf-8")
            self.assertFalse(MODULE.validate_playwright_evidence(path, 9).passed)
            path.write_text(json.dumps({
                "stats": {"expected": 9, "skipped": 0, "unexpected": 0, "flaky": 0}
            }), encoding="utf-8")
            self.assertTrue(MODULE.validate_playwright_evidence(path, 9).passed)

    def test_local_evidence_must_belong_to_the_current_production_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            playwright_path = root / "playwright.json"
            playwright_path.write_text(json.dumps({
                "config": {"metadata": {"productionE2ERunId": "old-run"}},
                "stats": {"expected": 10, "skipped": 0, "unexpected": 0, "flaky": 0},
            }), encoding="utf-8")
            self.assertFalse(
                MODULE.validate_playwright_evidence(
                    playwright_path,
                    10,
                    "current-run",
                ).passed
            )

            backup_path = root / "backup.json"
            backup_path.write_text(json.dumps({
                "schema_version": "local-backup-restore-v1",
                "production_e2e_run_id": "old-run",
                "status": "passed",
                "restore_attempts": 3,
                "rpo_lost_confirmed_outputs": 0,
                "rto_p95_seconds": 120,
                "ledger_valid": True,
                "corrupt_backup_rejected_by_sha256": True,
                "tampered_restore_rejected_by_ledger": True,
                "backup_sha256": "a" * 64,
            }), encoding="utf-8")
            self.assertFalse(
                MODULE.validate_backup_restore_evidence(
                    backup_path,
                    "current-run",
                ).passed
            )

    def test_backup_restore_gate_requires_three_restores_rpo_zero_and_corruption_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup-restore.json"
            path.write_text(json.dumps({
                "schema_version": "local-backup-restore-v1", "status": "passed",
                "restore_attempts": 3, "rpo_lost_confirmed_outputs": 0,
                "rto_p95_seconds": 120, "ledger_valid": True,
                "corrupt_backup_rejected_by_sha256": True,
                "tampered_restore_rejected_by_ledger": True, "backup_sha256": "a" * 64,
            }), encoding="utf-8")
            self.assertTrue(MODULE.validate_backup_restore_evidence(path).passed)
            report = json.loads(path.read_text(encoding="utf-8"))
            report["rpo_lost_confirmed_outputs"] = 1
            path.write_text(json.dumps(report), encoding="utf-8")
            self.assertFalse(MODULE.validate_backup_restore_evidence(path).passed)

    def test_provider_real_evaluation_report_belongs_to_same_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluation.json"
            path.write_text(json.dumps({
                "schema_version": "workflow-candidate-evaluation/1.0",
                "portfolio_version": "2.1",
                "production_e2e_run_id": "current-run",
                "passed": True,
                "blockers": [],
                "release_decision": "human_required",
            }), encoding="utf-8")
            result = MODULE.validate_evaluation_report(
                path,
                name="workflow_candidate_2_14",
                schema_version="workflow-candidate-evaluation/1.0",
                portfolio_version="2.1",
                expected_run_id="current-run",
            )
            self.assertTrue(result.passed)
            stale = MODULE.validate_evaluation_report(
                path,
                name="workflow_candidate_2_14",
                schema_version="workflow-candidate-evaluation/1.0",
                portfolio_version="2.1",
                expected_run_id="other-run",
            )
            self.assertFalse(stale.passed)

    def test_api_gate_requires_internal_and_market_evidence(self) -> None:
        health = {"status": "ok"}
        release_session = {
            "me": {
                "tenant_id": "tenant", "role": "release_validator", "auth_mode": "oidc",
                "token_client_id": "software-factory-release",
            },
            "tenants": [{"id": "tenant", "runtime_configuration_json": {
                "tenant_purpose": "release_homologation", "environment": "homologation",
                "customer_data_allowed": False, "synthetic_data_only": True,
            }}],
        }
        blocked = {
            "internal_assisted_pilot_ready": True,
            "market_ready": False,
            "release_blockers": [],
            "market_blockers": ["real_canary"],
            "market_validation_reports": [],
            "four_eyes_verified": True,
        }
        ready = {
            "internal_assisted_pilot_ready": True,
            "market_ready": True,
            "release_blockers": [],
            "market_blockers": [],
            "market_validation_reports": [
                {"report_kind": kind, "passed": True} for kind in MODULE.MARKET_REPORTS
            ],
            "four_eyes_verified": True,
        }
        blocked_evaluation = {
            "evaluations": [{
                "evaluation_type": "market_ready", "status": "blocked",
                "approved_by_user_id": "owner", "metrics_json": {
                    "four_eyes_verified": True, "portfolio_version": "2.1",
                },
                "evidence_hashes_json": ["a" * 64], "blockers_json": ["real_canary"],
            }],
        }
        passed_evaluation = {
            "evaluations": [{
                "evaluation_type": "market_ready", "status": "passed",
                "approved_by_user_id": "owner", "metrics_json": {
                    "four_eyes_verified": True, "portfolio_version": "2.1",
                },
                "evidence_hashes_json": ["a" * 64], "blockers_json": [],
            }],
        }
        costs = {"totals": {"actual_cost_usd": 49.0}}
        with patch.object(MODULE, "request_json", side_effect=[health, release_session, blocked, blocked_evaluation, costs]):
            results = MODULE.validate_api("http://127.0.0.1:8000", "token", "tenant", 1)
            self.assertFalse(results[2].passed)
            self.assertFalse(results[3].passed)
            self.assertTrue(results[4].passed)
        with patch.object(MODULE, "request_json", side_effect=[health, release_session, ready, passed_evaluation, costs]):
            results = MODULE.validate_api("http://127.0.0.1:8000", "token", "tenant", 1)
            self.assertTrue(all(result.passed for result in results))

        owner_session = json.loads(json.dumps(release_session))
        owner_session["me"]["role"] = "owner"
        with patch.object(MODULE, "request_json", side_effect=[health, owner_session, ready, passed_evaluation, costs]):
            results = MODULE.validate_api("http://127.0.0.1:8000", "token", "tenant", 1)
        self.assertFalse(next(item for item in results if item.name == "release_service_account").passed)

    def test_api_gate_can_target_first_assisted_client_without_market_evidence(self) -> None:
        health = {"status": "ok"}
        release_session = {
            "me": {
                "tenant_id": "tenant", "role": "release_validator", "auth_mode": "oidc",
                "token_client_id": "software-factory-release",
            },
            "tenants": [{"id": "tenant", "runtime_configuration_json": {
                "tenant_purpose": "release_homologation", "environment": "homologation",
                "customer_data_allowed": False, "synthetic_data_only": True,
            }}],
        }
        readiness = {
            "internal_assisted_pilot_ready": True,
            "market_ready": False,
            "release_blockers": [],
            "market_blockers": ["real_canary", "operational_slo", "external_user_validation"],
            "market_validation_reports": [],
            "four_eyes_verified": True,
        }
        evaluation = {
            "evaluations": [{
                "evaluation_type": "internal_assisted_pilot_ready",
                "status": "passed",
                "approved_by_user_id": "owner",
                "metrics_json": {"four_eyes_verified": True, "portfolio_version": "2.1"},
                "evidence_hashes_json": ["a" * 64],
                "blockers_json": [],
            }],
        }
        costs = {"totals": {"actual_cost_usd": 12.0}}
        with patch.object(MODULE, "request_json", side_effect=[health, release_session, readiness, evaluation, costs]):
            results = MODULE.validate_api(
                "http://127.0.0.1:8000",
                "token",
                "tenant",
                1,
                "internal_assisted_pilot_ready",
            )
        self.assertTrue(all(result.passed for result in results))
        self.assertEqual(results[2].name, "portfolio_internal_assisted_pilot_ready")


if __name__ == "__main__":
    unittest.main()
