"""Azure Blob Storage over its REST API, with a SAS token or a shared key."""

from __future__ import annotations

import base64
import hashlib
import hmac
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import formatdate, parsedate_to_datetime
from urllib.parse import parse_qsl, quote, urlparse

from engine.kb_connectors.base import (
    ConfigError,
    Connector,
    Field,
    Page,
    RemoteItem,
    safe_filename,
)
from engine.kb_connectors.http import GuardedClient, check_url

API_VERSION = "2021-08-06"


def parse_connection_string(raw: str) -> dict[str, str]:
    parts = dict(p.split("=", 1) for p in raw.split(";") if "=" in p)
    name = parts.get("AccountName", "")
    url = parts.get("BlobEndpoint") or (
        f"{parts.get('DefaultEndpointsProtocol', 'https')}://{name}.blob."
        f"{parts.get('EndpointSuffix', 'core.windows.net')}"
        if name
        else ""
    )
    return {
        "account_url": url.rstrip("/"),
        "account_name": name,
        "account_key": parts.get("AccountKey", ""),
        "sas_token": parts.get("SharedAccessSignature", ""),
    }


class AzureBlobConnector(Connector):
    kind = "azure_blob"
    label = "Azure Blob Storage"
    verified_live = True
    fields = [
        Field("container", "Container", required=True),
        Field("prefix", "Prefix", help="Only blobs under this prefix."),
        Field(
            "account_url",
            "Account URL",
            help="https://account.blob.core.windows.net, not needed with a connection string.",
        ),
        Field("connection_string", "Connection string", kind="secret", secret=True),
        Field("sas_token", "SAS token", kind="secret", secret=True),
    ]

    def __init__(self, config, secrets, **options) -> None:
        super().__init__(config, secrets, **options)
        self.http = GuardedClient(options.get("transport"))
        parsed = parse_connection_string(self.secret("connection_string"))
        self.account_url = (self.cfg("account_url") or parsed["account_url"]).rstrip(
            "/"
        )
        self.account_name = parsed["account_name"]
        self.account_key = parsed["account_key"]
        self.sas = (self.secret("sas_token") or parsed["sas_token"]).lstrip("?")

    async def aclose(self) -> None:
        await self.http.aclose()

    async def validate(self) -> None:
        if not self.account_url:
            raise ConfigError("Give an account URL or a connection string.")
        if not (self.account_key or self.sas):
            raise ConfigError("Give a connection string with a key, or a SAS token.")
        await check_url(self.account_url, "This account URL")

    def _url(self, path: str, query: dict[str, str]) -> str:
        pairs = dict(query)
        if self.sas:
            pairs.update(parse_qsl(self.sas, keep_blank_values=True))
        qs = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in pairs.items())
        return f"{self.account_url}/{path}" + (f"?{qs}" if qs else "")

    def _signed_headers(self, url: str) -> dict[str, str]:
        headers = {
            "x-ms-date": formatdate(usegmt=True),
            "x-ms-version": API_VERSION,
        }
        if self.sas:
            return headers
        u = urlparse(url)
        canonical_query = "".join(
            f"\n{k.lower()}:{v}"
            for k, v in sorted(parse_qsl(u.query, keep_blank_values=True))
        )
        canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
        to_sign = (
            "GET\n\n\n\n\n\n\n\n\n\n\n\n"
            + canonical_headers
            + f"/{self.account_name}{u.path}"
            + canonical_query
        )
        mac = hmac.new(
            base64.b64decode(self.account_key), to_sign.encode(), hashlib.sha256
        ).digest()
        headers["Authorization"] = (
            f"SharedKey {self.account_name}:{base64.b64encode(mac).decode()}"
        )
        return headers

    async def list_page(self, page_cursor, sync_cursor) -> Page:
        query = {"restype": "container", "comp": "list", "maxresults": "500"}
        if self.cfg("prefix"):
            query["prefix"] = self.cfg("prefix")
        if page_cursor and page_cursor.get("marker"):
            query["marker"] = page_cursor["marker"]
        url = self._url(quote(self.cfg("container")), query)
        resp = await self.http.request("GET", url, headers=self._signed_headers(url))
        root = ET.fromstring(resp.text)
        items = []
        for blob in root.iter("Blob"):
            name = blob.findtext("Name") or ""
            props = blob.find("Properties")
            if props is None:
                continue
            stamp = props.findtext("Last-Modified")
            modified: datetime | None = None
            if stamp:
                modified = parsedate_to_datetime(stamp).astimezone(timezone.utc)
            items.append(
                RemoteItem(
                    external_id=name,
                    name=safe_filename(name),
                    version=(props.findtext("Etag") or "").strip('"') or None,
                    size=int(props.findtext("Content-Length") or 0),
                    modified_at=modified,
                    # blob access is set on the container, it says nothing per person
                    acl={
                        "public": None,
                        "principals": [],
                        "scope": "container",
                        "access_tier": props.findtext("AccessTier"),
                    },
                )
            )
        marker = root.findtext("NextMarker")
        if marker:
            return Page(items=items, next_cursor={"marker": marker})
        return Page(items=items, finished=True)

    async def fetch(self, item: RemoteItem, max_bytes: int) -> bytes:
        path = f"{quote(self.cfg('container'))}/{quote(item.external_id)}"
        url = self._url(path, {})
        return await self.http.download(
            url, max_bytes, headers=self._signed_headers(url)
        )
