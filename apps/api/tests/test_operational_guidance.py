from datetime import datetime

from app.operational_guidance import build_operational_guidance


ACTION = {
    "kind": "approval",
    "title": "Revisar plano",
    "resource_id": "engagement-1",
    "href": "/engagements/engagement-1",
}


def _guidance(**overrides):
    values = {
        "action": ACTION,
        "state": {"record_version": 1, "status": "awaiting_approval"},
        "why_now": "O plano aguarda decisão.",
        "checks": ["Confira o escopo."],
        "risks": ["Escopo incompleto."],
        "draft": "Plano revisado.",
        "evidence_refs": ["plan-1"],
        "generated_at": datetime(2026, 7, 21, 12, 0, 0),
    }
    values.update(overrides)
    return build_operational_guidance(**values)


def test_model_narrative_cannot_change_deterministic_action_or_authority():
    result = _guidance(ai_content={
        "action": {"kind": "admin", "href": "/admin/tenants", "resource_id": "other-tenant"},
        "priority": "critical",
        "why_now": "Confira o plano sem executar instruções do artifact.",
        "checks": ["Confirme a evidência."],
        "risks": ["Artifact contém prompt injection."],
        "draft": "Solicito revisão humana.",
    }, model_call_id="model-call-1")

    assert result["action"] == ACTION
    assert result["provenance"]["source"] == "ai"
    assert "priority" not in result


def test_state_hash_invalidates_guidance_after_record_version_change():
    first = _guidance()
    changed = _guidance(state={"record_version": 2, "status": "approved"})

    assert first["state_hash"] != changed["state_hash"]
    assert first["generated_at"] == changed["generated_at"]


def test_provider_absence_produces_bounded_deterministic_fallback():
    result = _guidance(
        checks=["um", "dois", "três", "quatro"],
        risks=["a", "b", "c", "d"],
        evidence_refs=[],
    )

    assert result["provenance"]["source"] == "deterministic_fallback"
    assert result["provenance"]["model_call_id"] is None
    assert len(result["checks"]) == 3
    assert len(result["risks"]) == 3
    assert result["evidence_refs"] == [ACTION["resource_id"]]


def test_rebuilding_same_projection_is_stable_and_requires_no_model_call():
    first = _guidance()
    second = _guidance()

    assert first == second
