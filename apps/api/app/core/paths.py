from pathlib import Path
from urllib.parse import quote

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


def tenant_storage_key(tenant_id: str) -> str:
    return quote(tenant_id, safe="-_.")


def workspace_subpath(tenant_id: str, run_id: str) -> str:
    return f"tenants/{tenant_storage_key(tenant_id)}/{run_id}"


def run_workspace(run_id: str, tenant_id: str) -> Path:
    path = workspace_root() / workspace_subpath(tenant_id, run_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_delivery(run_id: str, tenant_id: str) -> Path:
    path = delivery_root() / "tenants" / tenant_storage_key(tenant_id) / run_id / "delivery"
    path.mkdir(parents=True, exist_ok=True)
    return path
