from pathlib import Path

from app.core.security import safe_join


def read_text(root: Path, relative_path: str) -> str:
    return safe_join(root, relative_path).read_text()
