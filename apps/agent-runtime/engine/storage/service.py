"""StorageService — Unified file storage with pluggable backends.

Configured via environment variables:
  STORAGE_BACKEND=local|s3|azure  (default: local)
  STORAGE_LOCAL_DIR=/data/uploads  (for local backend)
  STORAGE_S3_BUCKET=abenix-files
  STORAGE_S3_REGION=us-east-1
  STORAGE_S3_ENDPOINT=http://localhost:9000  (for MinIO)
  STORAGE_S3_ACCESS_KEY=...
  STORAGE_S3_SECRET_KEY=...
  STORAGE_AZURE_CONNECTION_STRING=...
  STORAGE_AZURE_CONTAINER=abenix-files
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local")
STORAGE_LOCAL_DIR = os.environ.get("STORAGE_LOCAL_DIR", os.environ.get("UPLOAD_DIR", "./data/uploads"))

# S3-compatible (AWS, MinIO, R2, GCS S3-compat, DigitalOcean Spaces)
STORAGE_S3_BUCKET = os.environ.get("STORAGE_S3_BUCKET", os.environ.get("S3_BUCKET", "abenix-files"))
STORAGE_S3_REGION = os.environ.get("STORAGE_S3_REGION", os.environ.get("AWS_REGION", "us-east-1"))
STORAGE_S3_ENDPOINT = os.environ.get("STORAGE_S3_ENDPOINT", "")  # MinIO: http://minio:9000
STORAGE_S3_ACCESS_KEY = os.environ.get("STORAGE_S3_ACCESS_KEY", os.environ.get("AWS_ACCESS_KEY_ID", ""))
STORAGE_S3_SECRET_KEY = os.environ.get("STORAGE_S3_SECRET_KEY", os.environ.get("AWS_SECRET_ACCESS_KEY", ""))

# Azure Blob
STORAGE_AZURE_CONN_STR = os.environ.get("STORAGE_AZURE_CONNECTION_STRING", "")
STORAGE_AZURE_CONTAINER = os.environ.get("STORAGE_AZURE_CONTAINER", "abenix-files")


class StorageService:
    """Unified file storage interface. Use get_storage() to get the configured instance."""

    def __init__(self, backend: str = STORAGE_BACKEND):
        self.backend = backend.lower()
        logger.info("StorageService initialized with backend: %s", self.backend)

    async def upload(
        self,
        tenant_id: str,
        path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Upload a file and return its URI (file:// or s3:// or az://)."""
        key = f"{tenant_id}/{path}"

        if self.backend == "s3":
            return await self._s3_upload(key, data, content_type, metadata)
        elif self.backend == "azure":
            return await self._azure_upload(key, data, content_type, metadata)
        else:
            return await self._local_upload(key, data)

    async def download(self, uri: str) -> bytes:
        """Download a file by its URI."""
        if uri.startswith("s3://"):
            return await self._s3_download(uri)
        elif uri.startswith("az://"):
            return await self._azure_download(uri)
        elif uri.startswith("file://"):
            return await self._local_download(uri)
        else:
            # Legacy path — treat as local file
            return await self._local_download_path(uri)

    async def get_download_url(self, uri: str, expires: int = 3600) -> str:
        """Get a presigned download URL (for S3/Azure) or a direct path (local)."""
        if uri.startswith("s3://"):
            return await self._s3_presigned_url(uri, expires)
        elif uri.startswith("az://"):
            return await self._azure_sas_url(uri, expires)
        else:
            # Local: return API endpoint path
            # The API will serve the file via GET /api/files/{encoded_path}
            import base64
            encoded = base64.urlsafe_b64encode(uri.encode()).decode()
            return f"/api/files/{encoded}"

    async def delete(self, uri: str) -> bool:
        """Delete a file by its URI."""
        try:
            if uri.startswith("s3://"):
                return await self._s3_delete(uri)
            elif uri.startswith("az://"):
                return await self._azure_delete(uri)
            elif uri.startswith("file://"):
                return await self._local_delete(uri)
            else:
                return await self._local_delete_path(uri)
        except Exception as e:
            logger.warning("Failed to delete %s: %s", uri, e)
            return False

    async def exists(self, uri: str) -> bool:
        """Check if a file exists."""
        try:
            if uri.startswith("s3://"):
                return await self._s3_exists(uri)
            elif uri.startswith("az://"):
                return await self._azure_exists(uri)
            else:
                path = uri.replace("file://", "") if uri.startswith("file://") else uri
                return Path(path).exists()
        except Exception:
            return False

    async def list_files(self, tenant_id: str, prefix: str = "") -> list[dict[str, Any]]:
        """List files for a tenant with optional prefix filter."""
        full_prefix = f"{tenant_id}/{prefix}" if prefix else f"{tenant_id}/"

        if self.backend == "s3":
            return await self._s3_list(full_prefix)
        elif self.backend == "azure":
            return await self._azure_list(full_prefix)
        else:
            return await self._local_list(full_prefix)

    async def _local_upload(self, key: str, data: bytes) -> str:
        base = Path(STORAGE_LOCAL_DIR)
        filepath = base / key
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_bytes(data)
        return f"file://{filepath.resolve()}"

    async def _local_download(self, uri: str) -> bytes:
        path = uri.replace("file://", "")
        return Path(path).read_bytes()

    async def _local_download_path(self, path: str) -> bytes:
        return Path(path).read_bytes()

    async def _local_delete(self, uri: str) -> bool:
        path = Path(uri.replace("file://", ""))
        if path.exists():
            path.unlink()
            return True
        return False

    async def _local_delete_path(self, path: str) -> bool:
        p = Path(path)
        if p.exists():
            p.unlink()
            return True
        return False

    async def _local_list(self, prefix: str) -> list[dict[str, Any]]:
        base = Path(STORAGE_LOCAL_DIR)
        prefix_path = base / prefix
        files = []
        if prefix_path.exists():
            for f in prefix_path.rglob("*"):
                if f.is_file():
                    files.append({
                        "key": str(f.relative_to(base)),
                        "size": f.stat().st_size,
                        "modified": f.stat().st_mtime,
                        "uri": f"file://{f.resolve()}",
                    })
        return files

    def _get_s3_client(self):
        import boto3
        kwargs: dict[str, Any] = {
            "region_name": STORAGE_S3_REGION,
        }
        if STORAGE_S3_ACCESS_KEY and STORAGE_S3_SECRET_KEY:
            kwargs["aws_access_key_id"] = STORAGE_S3_ACCESS_KEY
            kwargs["aws_secret_access_key"] = STORAGE_S3_SECRET_KEY
        if STORAGE_S3_ENDPOINT:
            kwargs["endpoint_url"] = STORAGE_S3_ENDPOINT
        return boto3.client("s3", **kwargs)

    async def _s3_upload(self, key: str, data: bytes, content_type: str, metadata: dict | None) -> str:
        import io
        client = self._get_s3_client()
        extra_args: dict[str, Any] = {"ContentType": content_type}
        if metadata:
            extra_args["Metadata"] = metadata
        client.upload_fileobj(io.BytesIO(data), STORAGE_S3_BUCKET, key, ExtraArgs=extra_args)
        return f"s3://{STORAGE_S3_BUCKET}/{key}"

    async def _s3_download(self, uri: str) -> bytes:
        import io
        client = self._get_s3_client()
        bucket, key = self._parse_s3_uri(uri)
        buf = io.BytesIO()
        client.download_fileobj(bucket, key, buf)
        return buf.getvalue()

    async def _s3_presigned_url(self, uri: str, expires: int) -> str:
        client = self._get_s3_client()
        bucket, key = self._parse_s3_uri(uri)
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires,
        )

    async def _s3_delete(self, uri: str) -> bool:
        client = self._get_s3_client()
        bucket, key = self._parse_s3_uri(uri)
        client.delete_object(Bucket=bucket, Key=key)
        return True

    async def _s3_exists(self, uri: str) -> bool:
        client = self._get_s3_client()
        bucket, key = self._parse_s3_uri(uri)
        try:
            client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False

    async def _s3_list(self, prefix: str) -> list[dict[str, Any]]:
        client = self._get_s3_client()
        response = client.list_objects_v2(Bucket=STORAGE_S3_BUCKET, Prefix=prefix, MaxKeys=1000)
        files = []
        for obj in response.get("Contents", []):
            files.append({
                "key": obj["Key"],
                "size": obj["Size"],
                "modified": obj["LastModified"].timestamp(),
                "uri": f"s3://{STORAGE_S3_BUCKET}/{obj['Key']}",
            })
        return files

    @staticmethod
    def _parse_s3_uri(uri: str) -> tuple[str, str]:
        """Parse s3://bucket/key into (bucket, key)."""
        without_scheme = uri[5:]  # Remove "s3://"
        parts = without_scheme.split("/", 1)
        return parts[0], parts[1] if len(parts) > 1 else ""

    def _get_azure_client(self):
        from azure.storage.blob import BlobServiceClient
        return BlobServiceClient.from_connection_string(STORAGE_AZURE_CONN_STR)

    async def _azure_upload(self, key: str, data: bytes, content_type: str, metadata: dict | None) -> str:
        from azure.storage.blob import ContentSettings
        client = self._get_azure_client()
        blob = client.get_blob_client(STORAGE_AZURE_CONTAINER, key)
        blob.upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
            metadata=metadata,
        )
        return f"az://{STORAGE_AZURE_CONTAINER}/{key}"

    async def _azure_download(self, uri: str) -> bytes:
        client = self._get_azure_client()
        container, key = self._parse_azure_uri(uri)
        blob = client.get_blob_client(container, key)
        return blob.download_blob().readall()

    async def _azure_sas_url(self, uri: str, expires: int) -> str:
        from azure.storage.blob import generate_blob_sas, BlobSasPermissions
        from datetime import datetime, timedelta, timezone
        client = self._get_azure_client()
        container, key = self._parse_azure_uri(uri)
        sas = generate_blob_sas(
            account_name=client.account_name,
            container_name=container,
            blob_name=key,
            account_key=client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(seconds=expires),
        )
        return f"{client.url}{container}/{key}?{sas}"

    async def _azure_delete(self, uri: str) -> bool:
        client = self._get_azure_client()
        container, key = self._parse_azure_uri(uri)
        blob = client.get_blob_client(container, key)
        blob.delete_blob()
        return True

    async def _azure_exists(self, uri: str) -> bool:
        client = self._get_azure_client()
        container, key = self._parse_azure_uri(uri)
        blob = client.get_blob_client(container, key)
        try:
            blob.get_blob_properties()
            return True
        except Exception:
            return False

    async def _azure_list(self, prefix: str) -> list[dict[str, Any]]:
        client = self._get_azure_client()
        container_client = client.get_container_client(STORAGE_AZURE_CONTAINER)
        files = []
        for blob in container_client.list_blobs(name_starts_with=prefix):
            files.append({
                "key": blob.name,
                "size": blob.size,
                "modified": blob.last_modified.timestamp() if blob.last_modified else 0,
                "uri": f"az://{STORAGE_AZURE_CONTAINER}/{blob.name}",
            })
        return files

    @staticmethod
    def _parse_azure_uri(uri: str) -> tuple[str, str]:
        """Parse az://container/key into (container, key)."""
        without_scheme = uri[5:]  # Remove "az://"
        parts = without_scheme.split("/", 1)
        return parts[0], parts[1] if len(parts) > 1 else ""


_instance: StorageService | None = None


def get_storage() -> StorageService:
    """Get the global StorageService instance (lazy singleton)."""
    global _instance
    if _instance is None:
        _instance = StorageService(STORAGE_BACKEND)
    return _instance
