#!/usr/bin/env python3
"""Compare provider-real workflow 2.14.0 evidence with immutable 2.13.2.

The evaluator is deterministic, performs no provider call and never promotes a
workflow. It requires three repetitions of every technical case in the fixed
commercial dataset for both versions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from release_evidence import enrich_release_report


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "homologation/cases/portfolio-v2/realistic-agentic-journeys.json"
BASELINE = "2.13.2"
CANDIDATE = "2.14.0"
REPETITIONS = 3
HEX_LENGTH = 64


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _technical_case_ids(dataset: dict[str, Any]) -> set[str]:
    return {
        str(item["id"])
        for item in dataset.get("scenarios") or []
        if "technical_run" in set(item.get("expected_modes") or [])
    }


def evaluate(dataset_path: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    dataset_bytes = dataset_path.read_bytes()
    dataset = json.loads(dataset_bytes)
    expected_dataset_sha = hashlib.sha256(dataset_bytes).hexdigest()
    blockers: list[str] = []
    expected_run_id = os.getenv("ASF_PRODUCTION_E2E_RUN_ID", "").strip()
    evidence_run_id = str(evidence.get("production_e2e_run_id") or "")
    if expected_run_id and evidence_run_id != expected_run_id:
        blockers.append("production_e2e_run_id_mismatch")
    if evidence.get("schema_version") != "workflow-candidate-evidence/1.0":
        blockers.append("unsupported_evidence_schema")
    if evidence.get("portfolio_version") != "2.1":
        blockers.append("portfolio_version_mismatch")
    if evidence.get("validation_mode") != "real":
        blockers.append("provider_real_validation_required")
    if evidence.get("dataset_sha256") != expected_dataset_sha:
        blockers.append("fixed_dataset_hash_mismatch")
    technical_cases = _technical_case_ids(dataset)
    if not technical_cases:
        blockers.append("technical_cases_missing_from_dataset")

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    seen_run_ids: set[str] = set()
    for run in evidence.get("runs") or []:
        version = str(run.get("workflow_version") or "")
        case_id = str(run.get("case_id") or "")
        run_id = str(run.get("run_id") or "")
        if version not in {BASELINE, CANDIDATE}:
            blockers.append(f"unsupported_workflow_version:{version or 'missing'}")
            continue
        if case_id not in technical_cases:
            blockers.append(f"unknown_technical_case:{case_id or 'missing'}")
            continue
        if not run_id or run_id in seen_run_ids:
            blockers.append("run_identity_missing_or_duplicate")
        seen_run_ids.add(run_id)
        if run.get("validation_mode") != "real" or run.get("provider_real") is not True:
            blockers.append(f"{version}:{case_id}:provider_real_evidence_required")
        if len(str(run.get("run_manifest_sha256") or "")) != HEX_LENGTH:
            blockers.append(f"{version}:{case_id}:run_manifest_hash_invalid")
        if not run.get("evidence_refs"):
            blockers.append(f"{version}:{case_id}:evidence_refs_missing")
        grouped[(version, case_id)].append(run)

    comparisons: list[dict[str, Any]] = []
    for case_id in sorted(technical_cases):
        baseline = grouped.get((BASELINE, case_id), [])
        candidate = grouped.get((CANDIDATE, case_id), [])
        if len(baseline) != REPETITIONS:
            blockers.append(f"{case_id}:baseline_repetitions_not_three")
        if len(candidate) != REPETITIONS:
            blockers.append(f"{case_id}:candidate_repetitions_not_three")
        if len(baseline) != REPETITIONS or len(candidate) != REPETITIONS:
            continue

        def median(rows: list[dict[str, Any]], key: str) -> float:
            return statistics.median(float(row.get(key) or 0.0) for row in rows)

        base = {
            key: median(baseline, key)
            for key in ("hrs", "quality_score", "cost_usd", "tokens")
        }
        proposed = {
            key: median(candidate, key)
            for key in ("hrs", "quality_score", "cost_usd", "tokens")
        }
        checks = {
            "baseline_contract_pass_rate_100": all(float(row.get("contract_pass_rate") or 0) == 1.0 for row in baseline),
            "candidate_contract_pass_rate_100": all(float(row.get("contract_pass_rate") or 0) == 1.0 for row in candidate),
            "baseline_17_gates": all(int(row.get("quality_gates_passed") or 0) == 17 for row in baseline),
            "candidate_17_gates": all(int(row.get("quality_gates_passed") or 0) == 17 for row in candidate),
            "hrs_not_lower": proposed["hrs"] >= 90.0 and proposed["hrs"] >= base["hrs"],
            "every_candidate_hrs_at_least_90": all(
                float(row.get("hrs") or 0) >= 90.0 for row in candidate
            ),
            "hrs_distribution_not_lower": all(
                proposed_hrs >= baseline_hrs
                for proposed_hrs, baseline_hrs in zip(
                    sorted(float(row.get("hrs") or 0) for row in candidate),
                    sorted(float(row.get("hrs") or 0) for row in baseline),
                    strict=True,
                )
            ),
            "quality_not_lower": proposed["quality_score"] >= base["quality_score"],
            "cost_within_20_percent": proposed["cost_usd"] <= base["cost_usd"] * 1.2,
            "tokens_within_20_percent": proposed["tokens"] <= base["tokens"] * 1.2,
            "security_no_regression": all(int(row.get("security_regressions") or 0) == 0 for row in candidate),
            "traceability_no_regression": all(int(row.get("traceability_regressions") or 0) == 0 for row in candidate),
            "same_model_aliases": {
                str(row.get("model_alias_set_sha256") or "") for row in baseline
            } == {
                str(row.get("model_alias_set_sha256") or "") for row in candidate
            } and all(len(str(row.get("model_alias_set_sha256") or "")) == HEX_LENGTH for row in [*baseline, *candidate]),
        }
        failed = [key for key, passed in checks.items() if not passed]
        blockers.extend(f"{case_id}:{key}" for key in failed)
        comparisons.append({
            "case_id": case_id,
            "baseline_medians": base,
            "candidate_medians": proposed,
            "checks": checks,
            "passed": not failed,
        })

    return {
        "schema_version": "workflow-candidate-evaluation/1.0",
        "baseline_workflow_version": BASELINE,
        "candidate_workflow_version": CANDIDATE,
        "portfolio_version": "2.1",
        "production_e2e_run_id": evidence_run_id,
        "dataset_sha256": expected_dataset_sha,
        "technical_case_ids": sorted(technical_cases),
        "repetitions": REPETITIONS,
        "comparisons": comparisons,
        "passed": not blockers,
        "blockers": sorted(set(blockers)),
        "release_decision": "human_required" if not blockers else "blocked",
        "automatic_promotion": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    started_monotonic = time.monotonic()
    args = parse_args()
    report = evaluate(args.dataset.resolve(), load_json(args.evidence.resolve()))
    report = enrich_release_report(
        report,
        repo_root=REPO_ROOT,
        command="evaluate-workflow-candidate.py",
        started_monotonic=started_monotonic,
        artifact_paths=(args.dataset, args.evidence),
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"workflow candidate evaluation failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
