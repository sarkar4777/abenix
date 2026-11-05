"""S3 and anything that speaks its API, MinIO, R2, Ceph and the rest."""

from __future__ import annotations

import asyncio
from typing import Any

from engine.kb_connectors.base import (
    AuthError,
    ConfigError,
    Connector,
    ConnectorError,
    Field,
    Page,
    RemoteItem,
    TooLarge,
    TransientError,
    safe_filename,
    with_retries,
)
from engine.kb_connectors.http import check_url

_ALL_USERS = "http://acs.amazonaws.com/groups/global/AllUsers"
_AUTH_CODES = {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "403"}


class S3Connector(Connector):
    kind = "s3"
    label = "S3 compatible object storage"
    verified_live = True
    fields = [
        Field("bucket", "Bucket", required=True),
        Field("prefix", "Prefix", help="Only keys under this prefix."),
        Field(
            "endpoint_url",
            "Endpoint URL",
            help="Leave empty for AWS. MinIO and others give their URL.",
        ),
        Field("region", "Region", default="us-east-1"),
        Field(
            "capture_acl",
            "Capture object ACLs",
            kind="bool",
            help="One extra call per object.",
        ),
        Field("access_key", "Access key", kind="secret", secret=True),
        Field(
            "secret_key",
            "Secret key",
            kind="secret",
            secret=True,
            help="Leave both empty to use the worker's role.",
        ),
    ]

    def __init__(self, config, secrets, **options) -> None:
        super().__init__(config, secrets, **options)
        self._client: Any = options.get("client")

    async def validate(self) -> None:
        endpoint = self.cfg("endpoint_url")
        if endpoint:
            await check_url(endpoint, "This endpoint")

    def _s3(self) -> Any:
        if self._client is None:
            import boto3
            from botocore.config import Config

            kw: dict[str, Any] = {
                "region_name": self.cfg("region", "us-east-1"),
                "config": Config(
                    retries={"max_attempts": 1},
                    connect_timeout=15,
                    read_timeout=60,
                    s3=(
                        {"addressing_style": "path"}
                        if self.cfg("endpoint_url")
                        else None
                    ),
                ),
            }
            if self.cfg("endpoint_url"):
                kw["endpoint_url"] = self.cfg("endpoint_url")
            if self.secret("access_key"):
                kw["aws_access_key_id"] = self.secret("access_key")
                kw["aws_secret_access_key"] = self.secret("secret_key")
            self._client = boto3.client("s3", **kw)
        return self._client

    async def _call(self, fn: Any, **kw: Any) -> Any:
        from botocore.exceptions import (
            BotoCoreError,
            ClientError,
            EndpointConnectionError,
        )

        async def once() -> Any:
            try:
                return await asyncio.to_thread(fn, **kw)
            except ClientError as e:
                code = str(e.response.get("Error", {}).get("Code", ""))
                status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
                if code in _AUTH_CODES:
                    raise AuthError(f"The storage refused these credentials ({code}).")
                if code == "NoSuchBucket":
                    raise ConfigError(
                        f"The bucket {self.cfg('bucket')} does not exist."
                    )
                if (
                    code in ("SlowDown", "Throttling", "RequestTimeout")
                    or status >= 500
                ):
                    raise TransientError(f"The storage answered {code}.")
                raise ConnectorError(f"The storage answered {code}.")
            except (EndpointConnectionError, BotoCoreError) as e:
                raise TransientError(f"Could not reach the storage: {e}")

        return await with_retries(once)

    async def _acl(self, key: str) -> dict[str, Any]:
        resp = await self._call(
            self._s3().get_object_acl, Bucket=self.cfg("bucket"), Key=key
        )
        public = False
        principals = []
        for grant in resp.get("Grants", []):
            who = grant.get("Grantee", {})
            if who.get("URI") == _ALL_USERS:
                public = True
            principals.append(
                {
                    "type": who.get("Type", "").lower(),
                    "id": who.get("ID") or who.get("URI"),
                    "email": who.get("EmailAddress"),
                    "role": grant.get("Permission"),
                }
            )
        # S3 grantees are account ids, none of them maps to a person here
        return {"public": None if not public else True, "principals": principals}

    async def list_page(self, page_cursor, sync_cursor) -> Page:
        kw: dict[str, Any] = {"Bucket": self.cfg("bucket"), "MaxKeys": 500}
        if self.cfg("prefix"):
            kw["Prefix"] = self.cfg("prefix")
        if page_cursor and page_cursor.get("token"):
            kw["ContinuationToken"] = page_cursor["token"]
        resp = await self._call(self._s3().list_objects_v2, **kw)
        items = []
        for o in resp.get("Contents", []):
            key = o["Key"]
            if key.endswith("/"):
                continue
            items.append(
                RemoteItem(
                    external_id=key,
                    name=safe_filename(key),
                    version=str(o.get("ETag", "")).strip('"') or None,
                    size=int(o.get("Size") or 0),
                    modified_at=o.get("LastModified"),
                    acl=await self._acl(key) if self.cfg("capture_acl") else None,
                )
            )
        token = resp.get("NextContinuationToken")
        if token:
            return Page(items=items, next_cursor={"token": token})
        return Page(items=items, finished=True)

    async def fetch(self, item: RemoteItem, max_bytes: int) -> bytes:
        resp = await self._call(
            self._s3().get_object, Bucket=self.cfg("bucket"), Key=item.external_id
        )
        body = resp["Body"]
        try:
            data = await asyncio.to_thread(body.read, max_bytes + 1)
        finally:
            body.close()
        if len(data) > max_bytes:
            raise TooLarge(f"It is larger than the limit of {max_bytes} bytes.")
        return data
