from typing import Any, Dict

from app.service_delivery.contracts import CalculationResult


PROJECT_HEALTH_WEIGHTS = {
    "data_completeness": 0.25,
    "operational_progress": 0.20,
    "quality": 0.20,
    "participation": 0.15,
    "risks_resolved": 0.10,
    "approvals_sla": 0.10,
}


class DeterministicCalculationEngine:
    def calculate(self, formula_code: str, formula_version: str, inputs: Dict[str, Any]) -> CalculationResult:
        if formula_code != "project_health" or formula_version != "project_health@1.0":
            raise ValueError(f"Unsupported formula: {formula_code}@{formula_version}")
        components = {}
        total = 0.0
        for key, weight in PROJECT_HEALTH_WEIGHTS.items():
            raw = float(inputs.get(key, 0.0))
            bounded = max(0.0, min(100.0, raw))
            weighted = bounded * weight
            components[key] = {"value": bounded, "weight": weight, "weighted": round(weighted, 2)}
            total += weighted
        return CalculationResult(
            formula_code=formula_code,
            formula_version=formula_version,
            value=round(total, 2),
            explanation={"components": components, "scale": "0-100"},
        )
