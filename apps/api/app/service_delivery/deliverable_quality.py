from __future__ import annotations

import re
import unicodedata
from itertools import combinations
from statistics import median
from typing import Any, Iterable


EVALUATION_SCHEMA_VERSION = "deliverable-contract-evaluation/1.0"
REPEATED_EVALUATION_SCHEMA_VERSION = "agentic-repeated-evaluation/1.0"
MIN_DELIVERABLE_WORDS = 60
MAX_PEER_SIMILARITY = 0.92

_PLACEHOLDERS = (
    "lorem ipsum",
    "[cliente]",
    "[nome do cliente]",
    "<cliente>",
    "a preencher",
    "insira aqui",
)

_PLACEHOLDER_PATTERNS = {
    "lorem ipsum": re.compile(r"\blorem\s+ipsum\b", re.IGNORECASE),
    "[cliente]": re.compile(r"\[\s*cliente\s*\]", re.IGNORECASE),
    "[nome do cliente]": re.compile(r"\[\s*nome\s+do\s+cliente\s*\]", re.IGNORECASE),
    "<cliente>": re.compile(r"<\s*cliente\s*>", re.IGNORECASE),
    "a preencher": re.compile(r"\ba\s+preencher\b", re.IGNORECASE),
    "insira aqui": re.compile(r"\binsira\s+aqui\b", re.IGNORECASE),
}


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    ascii_value = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in _normalize(value).split()
        if len(token) >= 3
    }


def _headings(markdown: str) -> list[str]:
    return [
        _normalize(match.group(1))
        for line in markdown.splitlines()
        if (match := re.match(r"^\s{0,3}#{2,6}\s+(.+?)\s*#*\s*$", line))
    ]


def _section_present(required: str, headings: Iterable[str]) -> bool:
    expected = _tokens(required)
    return bool(expected) and any(expected.issubset(_tokens(heading)) for heading in headings)


def _similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _check(
    key: str,
    passed: bool,
    detail: str,
    *,
    dimension: str,
    critical: bool = True,
) -> dict[str, Any]:
    return {
        "key": key,
        "passed": passed,
        "critical": critical,
        "dimension": dimension,
        "detail": detail,
    }


def evaluate_deliverable_contract(
    *,
    content: dict[str, Any],
    template: dict[str, Any],
    evidence_refs: list[str],
    verified_evidence_refs: Iterable[str] | None = None,
    peer_markdowns: Iterable[str] = (),
    specificity_terms: Iterable[str] = (),
    forbidden_claims: Iterable[str] = (),
) -> dict[str, Any]:
    """Evaluate deterministic parts of a contracted deliverable.

    This is deliberately not an AI judge and never approves a deliverable. It
    prevents structurally incomplete, ungrounded or duplicated material from
    reaching the human decision gate.
    """

    title = str(content.get("title") or "").strip()
    markdown = str(content.get("content_markdown") or "").strip()
    evidence_claims = [
        str(item).strip()
        for item in (content.get("evidence_claims") or [])
        if str(item).strip()
    ]
    risks = [str(item).strip() for item in (content.get("risks") or []) if str(item).strip()]
    next_actions = [
        str(item).strip()
        for item in (content.get("next_actions") or [])
        if str(item).strip()
    ]
    headings = _headings(markdown)
    word_count = len(re.findall(r"\b[\wÀ-ÿ-]+\b", markdown))
    checks: list[dict[str, Any]] = [
        _check(
            "title_present",
            bool(title),
            "O entregável possui título." if title else "O título está ausente.",
            dimension="contract",
        ),
        _check(
            "minimum_substance",
            word_count >= MIN_DELIVERABLE_WORDS,
            f"O conteúdo possui {word_count} palavras; mínimo contratual de teste: {MIN_DELIVERABLE_WORDS}.",
            dimension="usefulness",
        ),
    ]

    for index, section in enumerate(template.get("required_sections") or [], start=1):
        present = _section_present(str(section), headings)
        checks.append(
            _check(
                f"required_section_{index:02d}",
                present,
                (
                    f"Seção contratada encontrada: {section}."
                    if present
                    else f"Seção contratada ausente como heading H2-H6: {section}."
                ),
                dimension="contract",
            )
        )

    required_evidence = set(template.get("required_evidence") or [])
    if "source_refs" in required_evidence:
        checks.append(
            _check(
                "source_evidence_present",
                bool(evidence_refs),
                (
                    f"{len(evidence_refs)} referência(s) tenant-scoped registrada(s)."
                    if evidence_refs
                    else "Nenhuma referência tenant-scoped foi registrada."
                ),
                dimension="grounding",
            )
        )
        checks.append(
            _check(
                "evidence_claims_present",
                bool(evidence_claims),
                (
                    f"{len(evidence_claims)} afirmação(ões) de evidência declarada(s)."
                    if evidence_claims
                    else "O conteúdo não separa as afirmações sustentadas por evidência."
                ),
                dimension="grounding",
            )
        )
        if verified_evidence_refs is not None:
            verified = set(verified_evidence_refs)
            unverified = [item for item in evidence_refs if item not in verified]
            checks.append(
                _check(
                    "evidence_refs_verified",
                    bool(evidence_refs) and not unverified,
                    (
                        "Todas as referências foram resolvidas no tenant ativo."
                        if evidence_refs and not unverified
                        else f"Referências não verificadas no tenant ativo: {', '.join(unverified) or 'todas'}."
                    ),
                    dimension="grounding",
                )
            )

    checks.extend(
        [
            _check(
                "risks_present",
                bool(risks),
                "Riscos e limitações foram estruturados." if risks else "Riscos e limitações estão vazios.",
                dimension="decision",
            ),
            _check(
                "next_actions_present",
                bool(next_actions),
                "Próximas ações foram estruturadas." if next_actions else "Próximas ações estão vazias.",
                dimension="decision",
            ),
        ]
    )

    normalized_markdown = _normalize(markdown)
    found_placeholders = [
        value
        for value in _PLACEHOLDERS
        if _PLACEHOLDER_PATTERNS[value].search(markdown)
    ]
    checks.append(
        _check(
            "no_unresolved_placeholders",
            not found_placeholders,
            (
                "Nenhum placeholder editorial foi encontrado."
                if not found_placeholders
                else f"Placeholders editoriais encontrados: {', '.join(found_placeholders)}."
            ),
            dimension="usefulness",
        )
    )

    requested_terms = [str(item).strip() for item in specificity_terms if str(item).strip()]
    missing_terms = [
        term for term in requested_terms if _normalize(term) not in normalized_markdown
    ]
    if requested_terms:
        checks.append(
            _check(
                "scenario_specificity",
                not missing_terms,
                (
                    "O conteúdo contém todos os sinais específicos do cenário."
                    if not missing_terms
                    else f"Sinais específicos ausentes: {', '.join(missing_terms)}."
                ),
                dimension="specificity",
            )
        )

    forbidden_terms = [str(item).strip() for item in forbidden_claims if str(item).strip()]
    forbidden = [
        str(item).strip()
        for item in forbidden_terms
        if _normalize(str(item)) in normalized_markdown
    ]
    if forbidden_terms:
        checks.append(
            _check(
                "no_forbidden_claims",
                not forbidden,
                (
                    "Nenhuma alegação proibida foi encontrada."
                    if not forbidden
                    else f"Alegações proibidas encontradas: {', '.join(forbidden)}."
                ),
                dimension="safety",
            )
        )

    similarities = [
        _similarity(markdown, peer)
        for peer in peer_markdowns
        if str(peer).strip()
    ]
    maximum_similarity = max(similarities, default=0.0)
    checks.append(
        _check(
            "distinct_from_peer_deliverables",
            maximum_similarity <= MAX_PEER_SIMILARITY,
            (
                f"Maior similaridade com outro entregável: {maximum_similarity:.3f}; "
                f"limite: {MAX_PEER_SIMILARITY:.2f}."
            ),
            dimension="specificity",
        )
    )

    critical_checks = [item for item in checks if item["critical"]]
    passed_checks = sum(bool(item["passed"]) for item in critical_checks)
    score = round((passed_checks / len(critical_checks)) * 100, 2) if critical_checks else 0.0
    failures = [item["key"] for item in critical_checks if not item["passed"]]
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "passed": not failures,
        "score": score,
        "failures": failures,
        "checks": checks,
        "metrics": {
            "word_count": word_count,
            "required_sections": len(template.get("required_sections") or []),
            "evidence_refs": len(evidence_refs),
            "evidence_claims": len(evidence_claims),
            "max_peer_similarity": round(maximum_similarity, 4),
        },
        "human_approval_required": True,
    }


def aggregate_repeated_evaluations(
    runs: list[dict[str, Any]],
    *,
    minimum_runs: int = 3,
    minimum_pass_rate: float = 0.8,
) -> dict[str, Any]:
    evaluations = [item.get("evaluation") or {} for item in runs]
    passed_count = sum(bool(item.get("passed")) for item in evaluations)
    pass_rate = passed_count / len(runs) if runs else 0.0
    scores = [float(item.get("score") or 0.0) for item in evaluations]
    markdowns = [str(item.get("markdown") or "") for item in runs]
    pairwise_similarities = [
        _similarity(left, right)
        for left, right in combinations(markdowns, 2)
        if left.strip() and right.strip()
    ]
    blockers: list[str] = []
    if len(runs) < minimum_runs:
        blockers.append("insufficient_repeated_runs")
    if pass_rate < minimum_pass_rate:
        blockers.append("unstable_contract_pass_rate")
    return {
        "schema_version": REPEATED_EVALUATION_SCHEMA_VERSION,
        "passed": not blockers,
        "runs": len(runs),
        "passed_runs": passed_count,
        "pass_rate": round(pass_rate, 4),
        "median_score": round(median(scores), 2) if scores else 0.0,
        "pairwise_similarity": {
            "minimum": round(min(pairwise_similarities), 4) if pairwise_similarities else 0.0,
            "median": round(median(pairwise_similarities), 4) if pairwise_similarities else 0.0,
            "maximum": round(max(pairwise_similarities), 4) if pairwise_similarities else 0.0,
        },
        "blockers": blockers,
        "human_approval_required": True,
    }
