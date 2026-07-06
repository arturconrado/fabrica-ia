def is_terminal(status: str) -> bool:
    return status in {"approved_for_homologation", "rejected", "cancelled", "failed"}
