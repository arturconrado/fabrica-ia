from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/evaluate-workflow-candidate.py"
SPEC = importlib.util.spec_from_file_location("workflow_candidate_evaluation", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
DATASET = ROOT / "homologation/cases/portfolio-v2/realistic-agentic-journeys.json"


def evidence() -> dict:
    dataset_sha = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    cases = MODULE._technical_case_ids(json.loads(DATASET.read_text()))
    rows = []
    for version in (MODULE.BASELINE, MODULE.CANDIDATE):
        for case_id in cases:
            for repetition in range(1, 4):
                rows.append({
                    "run_id": f"{version}-{case_id}-{repetition}",
                    "workflow_version": version,
                    "case_id": case_id,
                    "validation_mode": "real",
                    "provider_real": True,
                    "run_manifest_sha256": "a" * 64,
                    "model_alias_set_sha256": "b" * 64,
                    "evidence_refs": [f"run:{version}:{case_id}:{repetition}"],
                    "contract_pass_rate": 1.0,
                    "quality_gates_passed": 17,
                    "hrs": 92 if version == MODULE.BASELINE else 93,
                    "quality_score": 90 if version == MODULE.BASELINE else 91,
                    "cost_usd": 10 if version == MODULE.BASELINE else 11,
                    "tokens": 1000 if version == MODULE.BASELINE else 1100,
                    "security_regressions": 0,
                    "traceability_regressions": 0,
                })
    return {
        "schema_version": "workflow-candidate-evidence/1.0",
        "portfolio_version": "2.1",
        "validation_mode": "real",
        "dataset_sha256": dataset_sha,
        "runs": rows,
    }


def test_candidate_requires_three_real_repetitions_and_human_promotion() -> None:
    report = MODULE.evaluate(DATASET, evidence())
    assert report["passed"] is True
    assert report["repetitions"] == 3
    assert report["release_decision"] == "human_required"
    assert report["automatic_promotion"] is False


def test_candidate_fails_on_quality_or_cost_regression() -> None:
    payload = evidence()
    case_id = next(
        row["case_id"] for row in payload["runs"]
        if row["workflow_version"] == MODULE.CANDIDATE
    )
    candidates = [
        row for row in payload["runs"]
        if row["workflow_version"] == MODULE.CANDIDATE
        and row["case_id"] == case_id
    ]
    for candidate in candidates:
        candidate["quality_score"] = 0
        candidate["cost_usd"] = 100
    report = MODULE.evaluate(DATASET, payload)
    assert report["passed"] is False
    assert any("quality_not_lower" in blocker for blocker in report["blockers"])
    assert any("cost_within_20_percent" in blocker for blocker in report["blockers"])


def test_candidate_rejects_synthetic_or_wrong_dataset_evidence() -> None:
    payload = evidence()
    payload["validation_mode"] = "synthetic"
    payload["dataset_sha256"] = "0" * 64
    report = MODULE.evaluate(DATASET, payload)
    assert report["passed"] is False
    assert "provider_real_validation_required" in report["blockers"]
    assert "fixed_dataset_hash_mismatch" in report["blockers"]
