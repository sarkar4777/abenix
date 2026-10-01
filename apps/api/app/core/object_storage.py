"""Object storage with local, S3 and Azure backends.

Backend selection follows the files router and engine.storage:
  STORAGE_BACKEND=local|s3|azure
  STORAGE_S3_BUCKET / STORAGE_S3_REGION / STORAGE_S3_ENDPOINT
  STORAGE_S3_ACCESS_KEY / STORAGE_S3_SECRET_KEY
  STORAGE_AZURE_CONNECTION_STRING / STORAGE_AZURE_CONTAINER
Local objects live under OBJECT_STORAGE_LOCAL_ROOT unless a caller names a root.
"""

from __future__ import annotations

import asyncio
import logging
import os
import posixpath
import uuid
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024
# S3 multipart parts must be at least 5 MiB, except the last one
S3_PART_SIZE = 8 * 1024 * 1024
AZURE_BLOCK_SIZE = 8 * 1024 * 1024
DEFAULT_CONTENT_TYPE = "application/octet-stream"

_SENTINEL = object()


class ObjectNotFound(FileNotFoundError):
    pass


class BadKey(ValueError):
    pass


def clean_key(key: str) -> str:
    """Reject anything that could escape the root or confuse a bucket listing."""
    if not isinstance(key, str) or not key or key.startswith("/") or "\\" in key:
        raise BadKey(f"bad object key: {key!r}")
    parts = key.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise BadKey(f"bad object key: {key!r}")
    return posixpath.normpath(key)


async def iter_chunks(source: Any, size: int = CHUNK_SIZE) -> AsyncIterator[bytes]:
    """Turn bytes, a file object, or any (async) iterable of bytes into chunks."""
    if isinstance(source, (bytes, bytearray, memoryview)):
        view = memoryview(source)
        for i in range(0, len(view), size):
            yield bytes(view[i : i + size])
        return
    if hasattr(source, "read"):
        while True:
            chunk = await asyncio.to_thread(source.read, size)
            if not chunk:
                return
            yield chunk
        return
    if isinstance(source, AsyncIterable):
        async for chunk in source:
            if chunk:
                yield bytes(chunk)
        return
    if isinstance(source, Iterable):
        for chunk in source:
            if chunk:
                yield bytes(chunk)
        return
    raise TypeError(f"unsupported source {type(source).__name__}")


async def _aiter_sync(it: Iterator[bytes]) -> AsyncIterator[bytes]:
    """Pull a blocking iterator one item at a time off the event loop."""
    while True:
        chunk = await asyncio.to_thread(next, it, _SENTINEL)
        if chunk is _SENTINEL:
            return
        if chunk:
            yield chunk


async def _regroup(chunks: AsyncIterator[bytes], size: int) -> AsyncIterator[bytes]:
    """Re-chunk a stream into pieces of exactly `size`, last one smaller."""
    buf = bytearray()
    async for chunk in chunks:
        buf += chunk
        while len(buf) >= size:
            yield bytes(buf[:size])
            del buf[:size]
    if buf:
        yield bytes(buf)


class ObjectStorage(Protocol):
    backend: str

    async def put(
        self, key: str, source: Any, content_type: str = DEFAULT_CONTENT_TYPE
    ) -> int: ...

    def get_stream(self, key: str) -> AsyncIterator[bytes]: ...

    async def delete(self, key: str) -> bool: ...

    async def exists(self, key: str) -> bool: ...

    def url_for(self, key: str) -> str: ...


class LocalObjectStorage:
    backend = "local"

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path_for(self, key: str) -> Path:
        return self.root / clean_key(key)

    async def put(
        self, key: str, source: Any, content_type: str = DEFAULT_CONTENT_TYPE
    ) -> int:
        target = self.path_for(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the target and rename so a reader never sees a half file
        part = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.part")
        written = 0
        try:
            with open(part, "wb") as fh:
                async for chunk in iter_chunks(source):
                    await asyncio.to_thread(fh.write, chunk)
                    written += len(chunk)
            os.replace(part, target)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        return written

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        path = self.path_for(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        with open(path, "rb") as fh:
            while True:
                chunk = await asyncio.to_thread(fh.read, CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk

    async def delete(self, key: str) -> bool:
        path = self.path_for(key)
        if not path.is_file():
            return False
        path.unlink()
        return True

    async def exists(self, key: str) -> bool:
        return self.path_for(key).is_file()

    def url_for(self, key: str) -> str:
        return f"file://{self.path_for(key).resolve().as_posix()}"


class S3ObjectStorage:
    backend = "s3"

    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        endpoint: str = "",
        access_key: str = "",
        secret_key: str = "",
    ):
        self.bucket = bucket
        self.region = region
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self._client = None

    def _c(self):
        if self._client is None:
            import boto3

            kwargs: dict[str, Any] = {"region_name": self.region}
            if self.access_key and self.secret_key:
                kwargs["aws_access_key_id"] = self.access_key
                kwargs["aws_secret_access_key"] = self.secret_key
            if self.endpoint:
                kwargs["endpoint_url"] = self.endpoint
            self._client = boto3.client("s3", **kwargs)
        return self._client

    async def put(
        self, key: str, source: Any, content_type: str = DEFAULT_CONTENT_TYPE
    ) -> int:
        key = clean_key(key)
        c = self._c()
        parts: list[dict[str, Any]] = []
        upload_id: str | None = None
        written = 0
        first: bytes | None = None
        try:
            async for piece in _regroup(iter_chunks(source), S3_PART_SIZE):
                written += len(piece)
                if first is None and upload_id is None:
                    first = piece
                    continue
                if upload_id is None:
                    mp = await asyncio.to_thread(
                        c.create_multipart_upload,
                        Bucket=self.bucket,
                        Key=key,
                        ContentType=content_type,
                    )
                    upload_id = mp["UploadId"]
                    assert first is not None
                    parts.append(await self._part(c, key, upload_id, 1, first))
                    first = None
                parts.append(await self._part(c, key, upload_id, len(parts) + 1, piece))
            if upload_id is None:
                await asyncio.to_thread(
                    c.put_object,
                    Bucket=self.bucket,
                    Key=key,
                    Body=first or b"",
                    ContentType=content_type,
                )
            else:
                await asyncio.to_thread(
                    c.complete_multipart_upload,
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
        except BaseException:
            if upload_id is not None:
                try:
                    await asyncio.to_thread(
                        c.abort_multipart_upload,
                        Bucket=self.bucket,
                        Key=key,
                        UploadId=upload_id,
                    )
                except Exception:
                    logger.warning("abort multipart %s failed", key, exc_info=True)
            raise
        return written

    async def _part(self, c, key: str, upload_id: str, n: int, body: bytes) -> dict:
        res = await asyncio.to_thread(
            c.upload_part,
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
            PartNumber=n,
            Body=body,
        )
        return {"ETag": res["ETag"], "PartNumber": n}

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        key = clean_key(key)
        c = self._c()
        try:
            obj = await asyncio.to_thread(c.get_object, Bucket=self.bucket, Key=key)
        except Exception as e:
            if getattr(e, "response", {}).get("Error", {}).get("Code") in (
                "NoSuchKey",
                "404",
            ):
                raise ObjectNotFound(key) from e
            raise
        async for chunk in _aiter_sync(iter(obj["Body"].iter_chunks(CHUNK_SIZE))):
            yield chunk

    async def delete(self, key: str) -> bool:
        key = clean_key(key)
        if not await self.exists(key):
            return False
        await asyncio.to_thread(self._c().delete_object, Bucket=self.bucket, Key=key)
        return True

    async def exists(self, key: str) -> bool:
        key = clean_key(key)
        try:
            await asyncio.to_thread(self._c().head_object, Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def url_for(self, key: str) -> str:
        return f"s3://{self.bucket}/{clean_key(key)}"


class AzureObjectStorage:
    backend = "azure"

    def __init__(self, connection_string: str, container: str):
        self.connection_string = connection_string
        self.container = container
        self._client = None

    def _container(self):
        if self._client is None:
            from azure.storage.blob import BlobServiceClient

            svc = BlobServiceClient.from_connection_string(self.connection_string)
            self._client = svc.get_container_client(self.container)
        return self._client

    def _blob(self, key: str):
        return self._container().get_blob_client(clean_key(key))

    async def put(
        self, key: str, source: Any, content_type: str = DEFAULT_CONTENT_TYPE
    ) -> int:
        from azure.storage.blob import BlobBlock, ContentSettings

        blob = self._blob(key)
        block_ids: list[str] = []
        written = 0
        async for piece in _regroup(iter_chunks(source), AZURE_BLOCK_SIZE):
            bid = uuid.uuid4().hex
            await asyncio.to_thread(blob.stage_block, bid, piece)
            block_ids.append(bid)
            written += len(piece)
        await asyncio.to_thread(
            blob.commit_block_list,
            [BlobBlock(block_id=b) for b in block_ids],
            content_settings=ContentSettings(content_type=content_type),
        )
        return written

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        blob = self._blob(key)
        try:
            downloader = await asyncio.to_thread(blob.download_blob)
        except Exception as e:
            if type(e).__name__ == "ResourceNotFoundError":
                raise ObjectNotFound(key) from e
            raise
        async for chunk in _aiter_sync(iter(downloader.chunks())):
            yield chunk

    async def delete(self, key: str) -> bool:
        blob = self._blob(key)
        if not await asyncio.to_thread(blob.exists):
            return False
        await asyncio.to_thread(blob.delete_blob)
        return True

    async def exists(self, key: str) -> bool:
        try:
            return bool(await asyncio.to_thread(self._blob(key).exists))
        except Exception:
            return False

    def url_for(self, key: str) -> str:
        return f"az://{self.container}/{clean_key(key)}"


def get_object_storage(local_root: str | Path | None = None) -> ObjectStorage:
    """Build the backend named by STORAGE_BACKEND. Env is read per call so tests can swap it."""
    backend = os.environ.get("STORAGE_BACKEND", "local").lower()
    if backend == "s3":
        return S3ObjectStorage(
            bucket=os.environ.get(
                "STORAGE_S3_BUCKET", os.environ.get("S3_BUCKET", "abenix-files")
            ),
            region=os.environ.get(
                "STORAGE_S3_REGION", os.environ.get("AWS_REGION", "us-east-1")
            ),
            endpoint=os.environ.get("STORAGE_S3_ENDPOINT", ""),
            access_key=os.environ.get(
                "STORAGE_S3_ACCESS_KEY", os.environ.get("AWS_ACCESS_KEY_ID", "")
            ),
            secret_key=os.environ.get(
                "STORAGE_S3_SECRET_KEY", os.environ.get("AWS_SECRET_ACCESS_KEY", "")
            ),
        )
    if backend == "azure":
        return AzureObjectStorage(
            connection_string=os.environ.get("STORAGE_AZURE_CONNECTION_STRING", ""),
            container=os.environ.get("STORAGE_AZURE_CONTAINER", "abenix-files"),
        )
    root = local_root or os.environ.get("OBJECT_STORAGE_LOCAL_ROOT", "/data")
    return LocalObjectStorage(root)
