"""Confluence Cloud and Data Center pages in a space, stored as plain text."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from engine.kb_connectors.base import (
    ConfigError,
    Connector,
    Field,
    Page,
    RemoteItem,
    safe_filename,
)
from engine.kb_connectors.http import GuardedClient, basic_auth, check_url
from engine.sources.normalize import html_text

_EXPAND = "version,body.storage,restrictions.read.restrictions.user"


def _when(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class ConfluenceConnector(Connector):
    kind = "confluence"
    label = "Confluence"
    fields = [
        Field(
            "base_url",
            "Site URL",
            required=True,
            help="https://yoursite.atlassian.net/wiki, or your server URL.",
        ),
        Field("space_key", "Space key", required=True),
        Field("email", "Account email", help="Cloud only. Empty uses a bearer token."),
        Field("api_token", "API token", kind="secret", secret=True, required=True),
    ]

    def __init__(self, config, secrets, **options) -> None:
        super().__init__(config, secrets, **options)
        self.http = GuardedClient(options.get("transport"))
        self.base = (self.cfg("base_url") or "").rstrip("/")

    async def aclose(self) -> None:
        await self.http.aclose()

    async def validate(self) -> None:
        if not self.base.startswith(("http://", "https://")):
            raise ConfigError("The site URL must start with https://")
        await check_url(self.base, "This site URL")

    def _headers(self) -> dict[str, str]:
        token = self.secret("api_token")
        if self.cfg("email"):
            return {"Authorization": basic_auth(self.cfg("email"), token)}
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _acl(raw: dict[str, Any]) -> dict[str, Any]:
        read = ((raw.get("restrictions") or {}).get("read") or {}).get(
            "restrictions"
        ) or {}
        users = (read.get("user") or {}).get("results") or []
        # no restriction on the page itself means the space decides, and that is not read here
        if not users:
            return {"public": None, "principals": [], "scope": "space"}
        return {
            "public": False,
            "principals": [
                {
                    "type": "user",
                    "id": u.get("accountId") or u.get("username"),
                    "email": u.get("email"),
                    "name": u.get("displayName"),
                    "role": "read",
                }
                for u in users
            ],
        }

    async def list_page(self, page_cursor, sync_cursor) -> Page:
        url = (page_cursor or {}).get("next")
        if url:
            url = urljoin(self.base + "/", url.lstrip("/"))
            params = None
        else:
            url = f"{self.base}/rest/api/content"
            params = {
                "spaceKey": self.cfg("space_key"),
                "type": "page",
                "status": "current",
                "limit": 50,
                "expand": _EXPAND,
            }
        resp = await self.http.request(
            "GET", url, params=params, headers=self._headers()
        )
        body = resp.json()
        items = []
        for raw in body.get("results", []):
            html = ((raw.get("body") or {}).get("storage") or {}).get("value") or ""
            title = raw.get("title") or raw["id"]
            text = f"# {title}\n\n{html_text(html.encode('utf-8')).text}"
            version = raw.get("version") or {}
            data = text.encode("utf-8")
            items.append(
                RemoteItem(
                    external_id=str(raw["id"]),
                    name=safe_filename(title.replace("/", "-"), str(raw["id"])) + ".md",
                    version=str(version.get("number", "")) or None,
                    size=len(data),
                    modified_at=_when(version.get("when")),
                    acl=self._acl(raw),
                    content=data,
                )
            )
        links = body.get("_links") or {}
        if links.get("next"):
            return Page(items=items, next_cursor={"next": links["next"]})
        return Page(items=items, finished=True)
