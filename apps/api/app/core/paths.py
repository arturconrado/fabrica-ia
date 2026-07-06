from pathlib import Path

from app.core.config import get_settings


def data_dir() -> Path:
    path = Path(get_settings().data_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_root() -> Path:
    path = data_dir() / "workspaces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def delivery_root() -> Path:
    path = data_dir() / "deliveries"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_workspace(run_id: str) -> Path:
    path = workspace_root() / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_delivery(run_id: str) -> Path:
    path = delivery_root() / run_id / "delivery"
    path.mkdir(parents=True, exist_ok=True)
    return path
