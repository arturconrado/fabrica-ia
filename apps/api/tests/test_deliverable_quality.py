from app.service_delivery.deliverable_quality import (
    aggregate_repeated_evaluations,
    evaluate_deliverable_contract,
)


TEMPLATE = {
    "required_sections": [
        "objetivo",
        "conteúdo",
        "evidências",
        "riscos e limitações",
        "próximos passos",
    ],
    "required_evidence": ["artifact_ref", "source_refs", "human_review"],
}


def _content(customer: str = "NovaMec", variation: str = "primeira") -> dict:
    return {
        "title": f"Documento do problema — {customer}",
        "content_markdown": (
            f"# Documento do problema — {customer}\n\n"
            "## Objetivo\n\n"
            f"Definir de forma verificável a oportunidade da {customer}, mantendo a decisão final com o VP e "
            "separando fatos, hipóteses e trabalho ainda não executado.\n\n"
            "## Conteúdo\n\n"
            f"Esta é a {variation} análise do fluxo de manutenção. O escopo controlado cobre 12 mil documentos, "
            "um tipo de equipamento e 120 perguntas. O copiloto recupera trechos, apresenta citações e nunca "
            "substitui procedimentos oficiais ou a confirmação humana em ações críticas.\n\n"
            "## Evidências\n\n"
            "Os números de escopo vieram do trecho tenant-scoped `knowledge_chunk:novamec-one`; precisão, "
            "latência, integração e benefício permanecem pendentes de testes reais.\n\n"
            "## Riscos e limitações\n\n"
            "Documentos desatualizados podem produzir grounding incorreto. Dados sensíveis e orientações de "
            "segurança exigem controles, revisão humana e avaliação adversarial antes de qualquer piloto.\n\n"
            "## Próximos passos\n\n"
            "O owner confere as fontes, a equipe executa o dataset controlado e o VP decide se solicita ajustes "
            "ou autoriza a etapa seguinte.\n"
        ),
        "evidence_claims": [
            "O escopo de 12 mil documentos e 120 perguntas está em knowledge_chunk:novamec-one."
        ],
        "risks": ["Documentos desatualizados podem comprometer o grounding."],
        "next_actions": ["Conferir fontes e executar o dataset controlado."],
    }


def test_realistic_deliverable_contract_passes_without_granting_approval():
    evaluation = evaluate_deliverable_contract(
        content=_content(),
        template=TEMPLATE,
        evidence_refs=["knowledge_chunk:novamec-one"],
        specificity_terms=["NovaMec", "12 mil documentos", "120 perguntas"],
        forbidden_claims=["piloto aprovado", "precisão comprovada"],
    )

    assert evaluation["passed"] is True
    assert evaluation["score"] == 100.0
    assert evaluation["human_approval_required"] is True
    assert evaluation["metrics"]["required_sections"] == 5


def test_incomplete_ungrounded_and_placeholder_output_is_blocked():
    evaluation = evaluate_deliverable_contract(
        content={
            "title": "Relatório [Cliente]",
            "content_markdown": "# Relatório\n\n## Objetivo\n\nA preencher.",
            "evidence_claims": [],
            "risks": [],
            "next_actions": [],
        },
        template=TEMPLATE,
        evidence_refs=[],
        specificity_terms=["NovaMec"],
    )

    assert evaluation["passed"] is False
    assert {
        "minimum_substance",
        "required_section_02",
        "required_section_03",
        "required_section_04",
        "required_section_05",
        "source_evidence_present",
        "evidence_claims_present",
        "risks_present",
        "next_actions_present",
        "no_unresolved_placeholders",
        "scenario_specificity",
    }.issubset(evaluation["failures"])


def test_normal_customer_language_is_not_mistaken_for_an_editorial_placeholder():
    content = _content()
    content["content_markdown"] = content["content_markdown"].replace(
        "oportunidade da NovaMec",
        "oportunidade do cliente NovaMec",
    )

    evaluation = evaluate_deliverable_contract(
        content=content,
        template=TEMPLATE,
        evidence_refs=["knowledge_chunk:novamec-one"],
    )

    assert evaluation["passed"] is True
    assert "no_unresolved_placeholders" not in evaluation["failures"]


def test_copying_a_peer_deliverable_is_detected_even_when_sections_exist():
    content = _content()
    evaluation = evaluate_deliverable_contract(
        content=content,
        template=TEMPLATE,
        evidence_refs=["knowledge_chunk:novamec-one"],
        peer_markdowns=[content["content_markdown"]],
    )

    assert evaluation["passed"] is False
    assert "distinct_from_peer_deliverables" in evaluation["failures"]
    assert evaluation["metrics"]["max_peer_similarity"] == 1.0


def test_declared_reference_does_not_count_when_tenant_attestation_is_missing():
    evaluation = evaluate_deliverable_contract(
        content=_content(),
        template=TEMPLATE,
        evidence_refs=["knowledge_chunk:made-up"],
        verified_evidence_refs=[],
    )

    assert evaluation["passed"] is False
    assert "evidence_refs_verified" in evaluation["failures"]


def test_repeated_evaluation_requires_multiple_stable_runs():
    passing = evaluate_deliverable_contract(
        content=_content(),
        template=TEMPLATE,
        evidence_refs=["knowledge_chunk:novamec-one"],
    )
    insufficient = aggregate_repeated_evaluations(
        [{"evaluation": passing, "markdown": _content()["content_markdown"]}],
    )
    stable = aggregate_repeated_evaluations(
        [
            {
                "evaluation": evaluate_deliverable_contract(
                    content=_content(variation=variation),
                    template=TEMPLATE,
                    evidence_refs=["knowledge_chunk:novamec-one"],
                ),
                "markdown": _content(variation=variation)["content_markdown"],
            }
            for variation in ("primeira", "segunda", "terceira")
        ],
    )

    assert insufficient["passed"] is False
    assert "insufficient_repeated_runs" in insufficient["blockers"]
    assert stable["passed"] is True
    assert stable["runs"] == 3
    assert stable["pass_rate"] == 1.0
