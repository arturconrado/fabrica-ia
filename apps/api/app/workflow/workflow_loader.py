from pathlib import Path

import yaml


def load_workflow(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())
