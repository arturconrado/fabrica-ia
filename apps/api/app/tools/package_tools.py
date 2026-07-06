from pathlib import Path


def ensure_package_dirs(root: Path) -> None:
    for folder in ["source-code", "docs", "deploy", "evidence/test-logs", "evidence/diffs"]:
        (root / folder).mkdir(parents=True, exist_ok=True)
