from functools import lru_cache
from typing import Iterable, Optional, Tuple

from app.core.config import get_settings
from app.core.paths import tenant_storage_key


@lru_cache(maxsize=4)
def _client(endpoint_url: str, access_key: str, secret_key: str):
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )


class ObjectStorage:
    @property
    def enabled(self) -> bool:
        return get_settings().runtime_profile.lower() in {"homologation", "production"}

    @property
    def bucket(self) -> str:
        return get_settings().s3_bucket

    def run_prefix(self, tenant_id: str, run_id: str) -> str:
        return f"tenants/{tenant_storage_key(tenant_id)}/runs/{run_id}"

    def knowledge_prefix(self, tenant_id: str, knowledge_base_id: str) -> str:
        return f"tenants/{tenant_storage_key(tenant_id)}/knowledge/{knowledge_base_id}"

    def object_key(self, tenant_id: str, run_id: str, area: str, relative_path: str) -> str:
        clean = relative_path.strip("/")
        if not clean or clean == ".." or clean.startswith("../") or "/../" in clean:
            raise ValueError("Invalid object storage relative path")
        return f"{self.run_prefix(tenant_id, run_id)}/{area.strip('/')}/{clean}"

    def put_text(
        self,
        tenant_id: str,
        run_id: str,
        area: str,
        relative_path: str,
        content: str,
        *,
        content_type: str = "text/plain; charset=utf-8",
    ) -> Optional[str]:
        if not self.enabled:
            return None
        key = self.object_key(tenant_id, run_id, area, relative_path)
        settings = get_settings()
        _client(settings.s3_endpoint_url, settings.s3_access_key_id, settings.s3_secret_access_key).put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType=content_type,
        )
        return key

    def put_knowledge_text(
        self,
        tenant_id: str,
        knowledge_base_id: str,
        document_id: str,
        content: str,
        *,
        content_type: str = "text/markdown; charset=utf-8",
    ) -> Optional[str]:
        if not self.enabled:
            return None
        key = f"{self.knowledge_prefix(tenant_id, knowledge_base_id)}/documents/{document_id}.md"
        settings = get_settings()
        _client(settings.s3_endpoint_url, settings.s3_access_key_id, settings.s3_secret_access_key).put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType=content_type,
            Metadata={"tenant-id": tenant_storage_key(tenant_id), "knowledge-base-id": knowledge_base_id},
        )
        return key

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def probe(self) -> None:
        if not self.enabled:
            return
        settings = get_settings()
        _client(settings.s3_endpoint_url, settings.s3_access_key_id, settings.s3_secret_access_key).head_bucket(
            Bucket=settings.s3_bucket
        )

    def read_prefix(self, prefix: str) -> Iterable[Tuple[str, bytes]]:
        if not self.enabled:
            raise RuntimeError("Object storage reads are only available in homologation or production")
        settings = get_settings()
        client = _client(settings.s3_endpoint_url, settings.s3_access_key_id, settings.s3_secret_access_key)
        normalized = prefix.rstrip("/") + "/"
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=normalized):
            for item in page.get("Contents", []):
                key = str(item["Key"])
                relative_path = key[len(normalized) :]
                if not relative_path:
                    continue
                body = client.get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
                yield relative_path, body


object_storage = ObjectStorage()
