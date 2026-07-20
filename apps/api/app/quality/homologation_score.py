def calculate_homologation_score(categories: list[dict]) -> tuple[float, list[dict]]:
    """Calculate a score only from caller-supplied, evidence-classified rows."""
    rows = []
    total = 0.0
    for item in categories:
        category = str(item["category"])
        score = float(item["score"])
        weight = float(item["weight"])
        evidence = dict(item.get("evidence") or {})
        if evidence.get("classification") not in {"real", "calculated", "declared", "estimated", "recommendation"}:
            raise ValueError(f"Evidence classification is required for {category}")
        weighted = score * weight / 100
        total += weighted
        rows.append(
            {
                "category": category,
                "score": score,
                "weight": weight,
                "weighted_score": round(weighted, 2),
                "evidence": evidence,
            }
        )
    return round(total, 2), rows


def status_for_score(score: float, hard_blockers: list, manual_review_required: bool = True) -> str:
    if hard_blockers:
        return "rejected"
    if manual_review_required:
        return "awaiting_human_review"
    if score >= 90:
        return "approved_for_homologation"
    if score >= 85:
        return "approved_with_risks"
    if score >= 75:
        return "mvp_functional"
    if score >= 60:
        return "executable_prototype"
    return "rejected"
