#!/usr/bin/env python3
"""Validate the independent Discovery and technical AI MVP commercial cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = (
    REPO_ROOT
    / "homologation"
    / "cases"
    / "portfolio-v2"
    / "commercial-operation-matrix.json"
)
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.service_delivery.catalog import _portfolio_v21  # noqa: E402


def load_matrix(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid commercial operation matrix: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Commercial operation matrix must be a JSON object")
    return payload


def validate_matrix(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != "commercial-operation-matrix/1.0":
        raise RuntimeError("Unsupported commercial operation matrix schema")
    cases = payload.get("cases") or []
    if len(cases) < 2:
        raise RuntimeError("At least two independent commercial cases are required")
    ids = [str(item.get("id") or "") for item in cases]
    tenants = [str(item.get("tenant_id") or "") for item in cases]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        raise RuntimeError("Commercial case ids must be unique and non-empty")
    if len(tenants) != len(set(tenants)) or any(not item for item in tenants):
        raise RuntimeError("Each commercial case needs an isolated tenant")
    catalog = {item["code"]: item for item in _portfolio_v21()["offerings"]}
    errors: list[str] = []
    for case in cases:
        case_id = case["id"]
        offering = catalog.get(str(case.get("offering_code") or ""))
        if not offering:
            errors.append(f"{case_id}: unknown offering")
            continue
        if case.get("offering_version") != "2.1":
            errors.append(f"{case_id}: offering version must be 2.1")
        if case.get("standalone") is not True or case.get("dependency_case_ids"):
            errors.append(f"{case_id}: acceptance cases must also work independently")
        actual_modes = {str(item.get("mode") or "") for item in offering.get("process") or []}
        if set(case.get("expected_process_modes") or []) != actual_modes:
            errors.append(f"{case_id}: process modes differ from the catalog")
        code_required = case.get("code_delivery_required") is True
        if code_required != ("technical_run" in actual_modes):
            errors.append(f"{case_id}: code delivery rule disagrees with technical_run")
        for field in (
            "customer",
            "commercial_goal",
            "ai_solution",
            "required_delivery_families",
            "terminal_evidence",
        ):
            if not case.get(field):
                errors.append(f"{case_id}: missing {field}")
        ai_solution = case.get("ai_solution") or {}
        if any(not ai_solution.get(field) for field in ("use_case", "human_decision", "customer_data_boundary")):
            errors.append(f"{case_id}: AI solution contract is incomplete")
        if code_required:
            acceptance = case.get("technical_acceptance") or {}
            if (
                int(acceptance.get("quality_gates") or 0) != 17
                or float(acceptance.get("minimum_hrs") or 0) < 90
                or acceptance.get("ponytail_status") != "terminal"
                or acceptance.get("cavekit_status") != "terminal"
                or not all(
                    acceptance.get(key) is True
                    for key in (
                        "file_change_diffs_required",
                        "editable_source_required",
                        "unit_integration_e2e_required",
                        "human_approval_required",
                    )
                )
            ):
                errors.append(f"{case_id}: technical acceptance is incomplete")
    concurrency = payload.get("concurrency") or {}
    if set(concurrency.get("parallel_wave") or []) != set(ids):
        errors.append("parallel_wave must include every acceptance case exactly once")
    if (
        concurrency.get("cases_may_run_independently") is not True
        or concurrency.get("cross_tenant_reuse") is not False
        or int(concurrency.get("global_service_wip") or 0) < len(cases)
        or int(concurrency.get("per_tenant_service_wip") or 0) < 1
    ):
        errors.append("concurrency and isolation contract is incomplete")
    if errors:
        raise RuntimeError("; ".join(errors))
    discovery = [item for item in cases if item["offering_code"] == "ai_value_discovery"]
    technical = [item for item in cases if item.get("code_delivery_required") is True]
    if not discovery or not technical:
        raise RuntimeError("Matrix must prove both standalone Discovery and technical AI MVP")
    return {
        "status": "valid",
        "schema_version": payload["schema_version"],
        "cases": len(cases),
        "tenants": len(tenants),
        "standalone_discovery_cases": len(discovery),
        "technical_ai_mvp_cases": len(technical),
        "parallel_wave": list(concurrency["parallel_wave"]),
        "cross_tenant_reuse": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    args = parser.parse_args()
    report = validate_matrix(load_matrix(args.matrix.resolve()))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"commercial operation matrix validation failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
