"""SharePoint document libraries and OneDrive through Microsoft Graph delta queries."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from urllib.parse import quote

from engine.kb_connectors.base import (
    ConfigError,
    Connector,
    Field,
    Gone,
    Page,
    RemoteItem,
    safe_filename,
)
from engine.kb_connectors.http import GuardedClient, check_url

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
_SELECT = "id,name,eTag,cTag,size,file,folder,deleted,lastModifiedDateTime"


def _when(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


class GraphConnector(Connector):
    kind = "sharepoint"
    label = "SharePoint or OneDrive"
    complete_listing = False
    fields = [
        Field("tenant_id", "Microsoft Entra tenant id", required=True),
        Field("client_id", "Application client id", required=True),
        Field(
            "site_id",
            "SharePoint site id",
            help="For a site's default library. Or give a drive id or a user below.",
        ),
        Field("drive_id", "Drive id", help="Any library or OneDrive by its id."),
        Field("user", "OneDrive user", help="User id or principal name."),
        Field(
            "capture_acl",
            "Capture permissions",
            kind="bool",
            default=True,
            help="One extra call per changed file.",
        ),
        Field(
            "client_secret", "Client secret", kind="secret", secret=True, required=True
        ),
    ]

    def __init__(self, config, secrets, **options) -> None:
        super().__init__(config, secrets, **options)
        self.http = GuardedClient(options.get("transport"))
        self.graph = (self.cfg("graph_url") or GRAPH).rstrip("/")
        self.login = (self.cfg("login_url") or LOGIN).rstrip("/")
        self._token = ""
        self._expires = 0.0
        self._drive: str | None = self.cfg("drive_id")

    async def aclose(self) -> None:
        await self.http.aclose()

    async def validate(self) -> None:
        if not (self.cfg("site_id") or self.cfg("drive_id") or self.cfg("user")):
            raise ConfigError(
                "Give a SharePoint site id, a drive id or a OneDrive user."
            )
        await check_url(self.graph, "The Graph URL")
        await check_url(self.login, "The sign in URL")

    async def _headers(self) -> dict[str, str]:
        if not self._token or time.time() > self._expires - 60:
            resp = await self.http.request(
                "POST",
                f"{self.login}/{quote(self.cfg('tenant_id'))}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.cfg("client_id"),
                    "client_secret": self.secret("client_secret"),
                    "scope": f"{self.graph.rsplit('/', 1)[0]}/.default",
                },
            )
            body = resp.json()
            self._token = body["access_token"]
            self._expires = time.time() + float(body.get("expires_in", 3600))
        return {"Authorization": f"Bearer {self._token}"}

    async def _drive_id(self) -> str:
        if self._drive:
            return self._drive
        if self.cfg("site_id"):
            url = f"{self.graph}/sites/{quote(self.cfg('site_id'), safe=',')}/drive"
        else:
            url = f"{self.graph}/users/{quote(self.cfg('user'))}/drive"
        resp = await self.http.request("GET", url, headers=await self._headers())
        self._drive = resp.json()["id"]
        return self._drive

    async def _acl(self, drive: str, item_id: str) -> dict[str, Any]:
        resp = await self.http.request(
            "GET",
            f"{self.graph}/drives/{drive}/items/{item_id}/permissions",
            headers=await self._headers(),
        )
        public = False
        principals: list[dict[str, Any]] = []
        for p in resp.json().get("value", []):
            if (p.get("link") or {}).get("scope") == "anonymous":
                public = True
            grantees = list(p.get("grantedToIdentitiesV2") or [])
            if p.get("grantedToV2"):
                grantees.append(p["grantedToV2"])
            for g in grantees:
                who = g.get("user") or g.get("group") or g.get("siteUser") or {}
                principals.append(
                    {
                        "type": "group" if g.get("group") else "user",
                        "id": who.get("id"),
                        "email": who.get("email") or who.get("loginName"),
                        "name": who.get("displayName"),
                        "role": ",".join(p.get("roles") or []),
                    }
                )
        return {"public": public, "principals": principals}

    async def list_page(self, page_cursor, sync_cursor) -> Page:
        drive = await self._drive_id()
        first = f"{self.graph}/drives/{drive}/root/delta?$select={_SELECT}&$top=200"
        url = (
            (page_cursor or {}).get("next") or (sync_cursor or {}).get("delta") or first
        )
        await check_url(url, "The next page URL")
        try:
            resp = await self.http.request("GET", url, headers=await self._headers())
        except Gone:
            # Graph drops old delta tokens, the answer is a fresh full listing
            resp = await self.http.request("GET", first, headers=await self._headers())
        body = resp.json()
        page = Page()
        for raw in body.get("value", []):
            if raw.get("deleted") is not None:
                page.deleted.append(raw["id"])
                continue
            if "file" not in raw:
                continue
            page.items.append(
                RemoteItem(
                    external_id=raw["id"],
                    name=safe_filename(raw.get("name", ""), raw["id"]),
                    version=raw.get("cTag") or raw.get("eTag"),
                    size=int(raw.get("size") or 0),
                    modified_at=_when(raw.get("lastModifiedDateTime")),
                    acl=(
                        await self._acl(drive, raw["id"])
                        if self.cfg("capture_acl", True)
                        else None
                    ),
                    meta={"drive": drive},
                )
            )
        if body.get("@odata.nextLink"):
            page.next_cursor = {"next": body["@odata.nextLink"]}
        else:
            page.finished = True
            page.sync_cursor = {"delta": body.get("@odata.deltaLink")}
        return page

    async def fetch(self, item: RemoteItem, max_bytes: int) -> bytes:
        drive = item.meta.get("drive") or await self._drive_id()
        return await self.http.download(
            f"{self.graph}/drives/{drive}/items/{item.external_id}/content",
            max_bytes,
            headers=await self._headers(),
        )
