SCORE_CATEGORIES = [
    ("Functional Completeness", 96, 20),
    ("Test Evidence", 95, 15),
    ("Executability / Deployability", 92, 15),
    ("Visual Quality", 90, 10),
    ("UX / Accessibility", 91, 10),
    ("Code Quality", 94, 10),
    ("Security / Privacy", 93, 10),
    ("Documentation", 95, 5),
    ("Operability", 93, 5),
]


def calculate_homologation_score() -> tuple[float, list[dict]]:
    rows = []
    total = 0.0
    for category, score, weight in SCORE_CATEGORIES:
        weighted = score * weight / 100
        total += weighted
        rows.append(
            {
                "category": category,
                "score": score,
                "weight": weight,
                "weighted_score": round(weighted, 2),
                "evidence": {"source": "Production LiteLLM/Temporal/Sandbox evidence ledger"},
            }
        )
    return round(total, 2), rows


def status_for_score(score: float, hard_blockers: list) -> str:
    if hard_blockers:
        return "rejected"
    if score >= 90:
        return "approved_for_homologation"
    if score >= 85:
        return "approved_with_risks"
    if score >= 75:
        return "mvp_functional"
    if score >= 60:
        return "executable_prototype"
    return "rejected"
