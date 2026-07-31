from datetime import datetime
from typing import Any, Optional

from app.agents.ai_native_contracts import stable_hash


def _bounded(values: Any, fallback: list[str]) -> list[str]:
    if not isinstance(values, list):
        return fallback[:3]
    result = [str(value).strip()[:220] for value in values if str(value).strip()]
    return result[:3] or [str(value).strip()[:220] for value in fallback[:3] if str(value).strip()]


def build_operational_guidance(
    *,
    action: Optional[dict[str, str]],
    state: dict[str, Any],
    why_now: str,
    checks: list[str],
    risks: list[str],
    draft: str,
    evidence_refs: list[str],
    generated_at: datetime | str,
    ai_content: Optional[dict[str, Any]] = None,
    model_call_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Attach bounded narrative to a server-owned action.

    Model output can only supply explanatory copy. Its action, links, resource
    identifiers, priority or authority are deliberately ignored.
    """
    if not action:
        return None
    source = ai_content if isinstance(ai_content, dict) else {}
    refs = list(dict.fromkeys(str(ref).strip() for ref in evidence_refs if str(ref).strip()))
    if not refs:
        refs = [action["resource_id"]]
    timestamp = generated_at.isoformat() if isinstance(generated_at, datetime) else str(generated_at)
    state_hash = stable_hash({"action": action, "state": state, "evidence_refs": refs})
    ai_backed = bool(model_call_id and source)
    return {
        "action": action,
        "why_now": str(source.get("why_now") or why_now).strip()[:400],
        "checks": _bounded(source.get("checks"), checks),
        "risks": _bounded(source.get("risks"), risks),
        "draft": str(source.get("draft") or draft).strip()[:500],
        "evidence_refs": refs[:20],
        "confidence": min(1.0, max(0.0, float(source.get("confidence") or (0.85 if ai_backed else 0.65)))),
        "provenance": {
            "source": "ai" if ai_backed else "deterministic_fallback",
            "model_call_id": model_call_id if ai_backed else None,
            "generated_from": refs[:20],
        },
        "state_hash": state_hash,
        "generated_at": timestamp,
    }
