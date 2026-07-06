def build_summary(status: str, score: float, blockers: list) -> str:
    return f"Status: {status}; HRS: {score}; blockers: {len(blockers)}"
