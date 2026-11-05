"""Google Drive through a service account, a full listing then the changes feed."""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote

from engine.kb_connectors.base import (
    ConfigError,
    Connector,
    Field,
    Page,
    RemoteItem,
    safe_filename,
)
from engine.kb_connectors.http import GuardedClient, check_url

API = "https://www.googleapis.com/drive/v3"
TOKEN = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/drive.readonly"
_FILE_FIELDS = (
    "id,name,mimeType,size,md5Checksum,headRevisionId,version,modifiedTime,trashed,"
    "parents,permissions(type,role,emailAddress,domain)"
)
_EXPORTS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
}
_FOLDER = "application/vnd.google-apps.folder"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _when(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def signed_jwt(
    account: dict[str, Any], subject: str = "", now: float | None = None
) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    issued = int(now if now is not None else time.time())
    claims: dict[str, Any] = {
        "iss": account["client_email"],
        "scope": SCOPE,
        "aud": account.get("token_uri") or TOKEN,
        "iat": issued,
        "exp": issued + 3600,
    }
    if subject:
        claims["sub"] = subject
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(claims).encode())
    key = serialization.load_pem_private_key(
        account["private_key"].encode(), password=None
    )
    sig = key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{_b64(sig)}"


class GoogleDriveConnector(Connector):
    kind = "google_drive"
    label = "Google Drive"
    complete_listing = False
    fields = [
        Field(
            "drive_id",
            "Shared drive id",
            help="Empty reads what the service account can see.",
        ),
        Field("folder_id", "Folder id", help="Only files directly in this folder."),
        Field(
            "subject",
            "Impersonate user",
            help="Needs domain wide delegation.",
        ),
        Field(
            "service_account_json",
            "Service account key JSON",
            kind="secret",
            secret=True,
            required=True,
        ),
    ]

    def __init__(self, config, secrets, **options) -> None:
        super().__init__(config, secrets, **options)
        self.http = GuardedClient(options.get("transport"))
        self.api = (self.cfg("api_url") or API).rstrip("/")
        self._token = ""
        self._expires = 0.0

    async def aclose(self) -> None:
        await self.http.aclose()

    def _account(self) -> dict[str, Any]:
        try:
            account = json.loads(self.secret("service_account_json"))
            assert account["client_email"] and account["private_key"]
        except (ValueError, KeyError, AssertionError, TypeError) as e:
            raise ConfigError("That is not a service account key JSON file.") from e
        return account

    async def validate(self) -> None:
        account = self._account()
        await check_url(self.api, "The Drive URL")
        await check_url(account.get("token_uri") or TOKEN, "The token URL")

    async def _headers(self) -> dict[str, str]:
        if not self._token or time.time() > self._expires - 60:
            account = self._account()
            resp = await self.http.request(
                "POST",
                account.get("token_uri") or TOKEN,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": signed_jwt(account, self.cfg("subject", "")),
                },
            )
            body = resp.json()
            self._token = body["access_token"]
            self._expires = time.time() + float(body.get("expires_in", 3600))
        return {"Authorization": f"Bearer {self._token}"}

    def _common(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "pageSize": 200,
        }
        if self.cfg("drive_id"):
            params["driveId"] = self.cfg("drive_id")
        return params

    def _in_scope(self, raw: dict[str, Any]) -> bool:
        folder = self.cfg("folder_id")
        return not folder or folder in (raw.get("parents") or [])

    def _item(self, raw: dict[str, Any]) -> RemoteItem | None:
        mime = raw.get("mimeType", "")
        if mime == _FOLDER or (
            mime.startswith("application/vnd.google-apps.") and mime not in _EXPORTS
        ):
            return None
        name = safe_filename(raw.get("name", ""), raw["id"])
        suffix = _EXPORTS.get(mime, ("", ""))[1]
        if suffix and not name.endswith(suffix):
            name += suffix
        perms = raw.get("permissions")
        acl = None
        if perms is not None:
            acl = {
                "public": any(p.get("type") == "anyone" for p in perms),
                "principals": [
                    {
                        "type": p.get("type"),
                        "email": p.get("emailAddress"),
                        "domain": p.get("domain"),
                        "role": p.get("role"),
                    }
                    for p in perms
                ],
            }
        return RemoteItem(
            external_id=raw["id"],
            name=name,
            version=raw.get("md5Checksum")
            or raw.get("headRevisionId")
            or raw.get("version")
            or raw.get("modifiedTime"),
            size=int(raw["size"]) if raw.get("size") else None,
            modified_at=_when(raw.get("modifiedTime")),
            acl=acl,
            meta={"mime": mime},
        )

    async def _first_pass(self, page_cursor, sync_cursor) -> Page:
        token = (page_cursor or {}).get("start")
        if not token:
            start_params = {"supportsAllDrives": "true"}
            if self.cfg("drive_id"):
                start_params["driveId"] = self.cfg("drive_id")
            resp = await self.http.request(
                "GET",
                f"{self.api}/changes/startPageToken",
                params=start_params,
                headers=await self._headers(),
            )
            token = resp.json()["startPageToken"]
        params = {
            **self._common(),
            "fields": f"nextPageToken,files({_FILE_FIELDS})",
            "q": "trashed = false",
        }
        if self.cfg("drive_id"):
            params["corpora"] = "drive"
        if self.cfg("folder_id"):
            params["q"] += f" and '{self.cfg('folder_id')}' in parents"
        if (page_cursor or {}).get("files"):
            params["pageToken"] = page_cursor["files"]
        resp = await self.http.request(
            "GET", f"{self.api}/files", params=params, headers=await self._headers()
        )
        body = resp.json()
        page = Page()
        for raw in body.get("files", []):
            item = self._item(raw)
            if item:
                page.items.append(item)
        if body.get("nextPageToken"):
            page.next_cursor = {"files": body["nextPageToken"], "start": token}
        else:
            page.finished = True
            page.sync_cursor = {"changes": token}
        return page

    async def list_page(self, page_cursor, sync_cursor) -> Page:
        if not (sync_cursor or {}).get("changes"):
            return await self._first_pass(page_cursor, sync_cursor)
        token = (page_cursor or {}).get("changes") or sync_cursor["changes"]
        params = {
            **self._common(),
            "pageToken": token,
            "fields": f"nextPageToken,newStartPageToken,changes(removed,fileId,file({_FILE_FIELDS}))",
        }
        resp = await self.http.request(
            "GET", f"{self.api}/changes", params=params, headers=await self._headers()
        )
        body = resp.json()
        page = Page()
        for change in body.get("changes", []):
            raw = change.get("file") or {}
            if change.get("removed") or raw.get("trashed") or not self._in_scope(raw):
                page.deleted.append(change["fileId"])
                continue
            item = self._item(raw)
            if item:
                page.items.append(item)
        if body.get("nextPageToken"):
            page.next_cursor = {"changes": body["nextPageToken"]}
        else:
            page.finished = True
            page.sync_cursor = {"changes": body.get("newStartPageToken") or token}
        return page

    async def fetch(self, item: RemoteItem, max_bytes: int) -> bytes:
        export = _EXPORTS.get(item.meta.get("mime", ""))
        fid = quote(item.external_id)
        if export:
            url = f"{self.api}/files/{fid}/export"
            params = {"mimeType": export[0]}
        else:
            url = f"{self.api}/files/{fid}"
            params = {"alt": "media", "supportsAllDrives": "true"}
        return await self.http.download(
            url, max_bytes, params=params, headers=await self._headers()
        )
