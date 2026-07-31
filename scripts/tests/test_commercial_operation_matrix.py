from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "validate-commercial-operation-matrix.py"
SPEC = importlib.util.spec_from_file_location("validate_commercial_operation_matrix", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_matrix_proves_independent_discovery_and_code_delivering_ai_mvp():
    payload = MODULE.load_matrix(MODULE.DEFAULT_MATRIX)

    report = MODULE.validate_matrix(payload)

    assert report == {
        "status": "valid",
        "schema_version": "commercial-operation-matrix/1.0",
        "cases": 2,
        "tenants": 2,
        "standalone_discovery_cases": 1,
        "technical_ai_mvp_cases": 1,
        "parallel_wave": [
            "standalone-discovery-atlaslog",
            "agentic-quotation-mvp-metalquote",
        ],
        "cross_tenant_reuse": False,
    }


def test_matrix_rejects_mvp_without_code_diff_and_test_acceptance():
    payload = deepcopy(MODULE.load_matrix(MODULE.DEFAULT_MATRIX))
    mvp = next(item for item in payload["cases"] if item["code_delivery_required"])
    mvp["technical_acceptance"]["file_change_diffs_required"] = False
    mvp["technical_acceptance"]["unit_integration_e2e_required"] = False

    try:
        MODULE.validate_matrix(payload)
    except RuntimeError as exc:
        assert "technical acceptance is incomplete" in str(exc)
    else:
        raise AssertionError("A technical MVP without code/test evidence must not pass")


def test_matrix_rejects_cross_tenant_reuse_or_hidden_dependency():
    payload = deepcopy(MODULE.load_matrix(MODULE.DEFAULT_MATRIX))
    payload["concurrency"]["cross_tenant_reuse"] = True
    payload["cases"][1]["dependency_case_ids"] = [payload["cases"][0]["id"]]

    try:
        MODULE.validate_matrix(payload)
    except RuntimeError as exc:
        assert "work independently" in str(exc)
        assert "concurrency and isolation contract is incomplete" in str(exc)
    else:
        raise AssertionError("Cross-tenant reuse or a hidden dependency must not pass")
