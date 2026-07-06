def condition_matches(condition, status: str) -> bool:
    if condition is True:
        return True
    if isinstance(condition, str):
        return condition in {status, "success" if status in {"success", "approved"} else status}
    if isinstance(condition, dict):
        return condition.get("equals") == status
    return False
