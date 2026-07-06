from pathlib import Path


class UnsafePathError(ValueError):
    pass


def safe_join(root: Path, relative_path: str) -> Path:
    if not relative_path or relative_path.startswith("/"):
        raise UnsafePathError("Path must be relative")
    candidate = (root / relative_path).resolve()
    root_resolved = root.resolve()
    if root_resolved not in candidate.parents and candidate != root_resolved:
        raise UnsafePathError("Path traversal blocked")
    return candidate
