from pathlib import Path


def load_skill(skill_id: str) -> str:
    path = Path("skills") / f"{skill_id}.skill.yaml"
    return path.read_text() if path.exists() else ""
