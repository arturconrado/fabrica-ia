from app.core.config import get_settings
from app.providers import object_storage as storage_module
from app.providers.object_storage import ObjectStorage


def test_object_storage_is_disabled_outside_operational_profiles(monkeypatch):
    monkeypatch.setenv("ASF_RUNTIME_PROFILE", "test")
    get_settings.cache_clear()
    storage = ObjectStorage()
    assert storage.put_text("tenant/a", "run-1", "workspace", "generated_app/app.py", "pass") is None
    get_settings.cache_clear()


def test_object_storage_key_is_tenant_and_run_prefixed(monkeypatch):
    monkeypatch.setenv("ASF_RUNTIME_PROFILE", "homologation")
    get_settings.cache_clear()
    storage = ObjectStorage()
    key = storage.object_key("tenant/a", "run-1", "delivery", "docs/report.md")
    assert key == "tenants/tenant%2Fa/runs/run-1/delivery/docs/report.md"
    get_settings.cache_clear()


def test_homologation_object_upload_uses_isolated_key(monkeypatch):
    uploads = []

    class FakeClient:
        def put_object(self, **kwargs):
            uploads.append(kwargs)

    monkeypatch.setenv("ASF_RUNTIME_PROFILE", "homologation")
    monkeypatch.setattr(storage_module, "_client", lambda *args: FakeClient())
    get_settings.cache_clear()
    storage = ObjectStorage()
    key = storage.put_text("tenant-a", "run-a", "artifacts", "report.md", "evidence")
    assert key == "tenants/tenant-a/runs/run-a/artifacts/report.md"
    assert uploads[0]["Bucket"] == get_settings().s3_bucket
    assert uploads[0]["Key"] == key
    assert uploads[0]["Body"] == b"evidence"
    get_settings.cache_clear()


def test_production_knowledge_upload_uses_tenant_base_prefix(monkeypatch):
    uploads = []

    class FakeClient:
        def put_object(self, **kwargs):
            uploads.append(kwargs)

    monkeypatch.setenv("ASF_RUNTIME_PROFILE", "production")
    monkeypatch.setattr(storage_module, "_client", lambda *args: FakeClient())
    get_settings.cache_clear()
    key = ObjectStorage().put_knowledge_text("client/a", "base-1", "doc-1", "private knowledge")
    assert key == "tenants/client%2Fa/knowledge/base-1/documents/doc-1.md"
    assert uploads[0]["Key"] == key
    assert uploads[0]["Body"] == b"private knowledge"
    assert uploads[0]["Metadata"]["tenant-id"] == "client%2Fa"
    get_settings.cache_clear()


def test_production_object_prefix_read_returns_relative_paths(monkeypatch):
    class Body:
        def read(self):
            return b"manifest"

    class Paginator:
        def paginate(self, **kwargs):
            assert kwargs["Prefix"] == "tenants/tenant-a/runs/run-a/delivery/"
            return [{"Contents": [{"Key": kwargs["Prefix"] + "manifest.json"}]}]

    class FakeClient:
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return Paginator()

        def get_object(self, **kwargs):
            return {"Body": Body()}

    monkeypatch.setenv("ASF_RUNTIME_PROFILE", "production")
    monkeypatch.setattr(storage_module, "_client", lambda *args: FakeClient())
    get_settings.cache_clear()
    files = list(ObjectStorage().read_prefix("tenants/tenant-a/runs/run-a/delivery"))
    assert files == [("manifest.json", b"manifest")]
    get_settings.cache_clear()
