"""Headless browser automation via Playwright."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from engine.tools.base import BaseTool, ToolResult


def _domain_allowed(url: str) -> tuple[bool, str]:
    """Returns (ok, host). '*' allow-list = anything (dev default)."""
    raw = os.environ.get("BROWSER_AUTOMATION_ALLOWED_HOSTS", "*").strip()
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False, ""
    if raw == "*" or not raw:
        return True, host
    allowed = {h.strip().lower() for h in raw.split(",") if h.strip()}
    # Allow exact match OR any parent-domain match (e.g. "example.com" allows "www.example.com").
    for a in allowed:
        if host == a or host.endswith("." + a):
            return True, host
    return False, host


class BrowserAutomationTool(BaseTool):
    name = "browser_automation"
    description = (
        "Headless Chromium via Playwright for sites that need JS rendering, "
        "login flows, or click-throughs. Operations: get_text (full visible "
        "text of a page), get_html (rendered HTML), screenshot (PNG bytes "
        "base64), click_and_get (navigate + click a CSS selector + extract). "
        "Domains gated via BROWSER_AUTOMATION_ALLOWED_HOSTS env (comma list, "
        "or '*' in dev). Requires `pip install playwright && playwright install chromium`."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["get_text", "get_html", "screenshot", "click_and_get"],
                "default": "get_text",
            },
            "url": {
                "type": "string",
                "description": "Target URL (must pass the allow-list).",
            },
            "wait_for_selector": {
                "type": "string",
                "description": "Optional CSS selector to wait for before extracting.",
            },
            "click_selector": {
                "type": "string",
                "description": "click_and_get only — the CSS selector to click first.",
            },
            "timeout_ms": {
                "type": "integer",
                "default": 15000,
                "minimum": 1000,
                "maximum": 60000,
            },
            "max_chars": {
                "type": "integer",
                "default": 6000,
                "minimum": 100,
                "maximum": 50000,
                "description": "Cap text/HTML output to keep token cost sane.",
            },
        },
        "required": ["operation", "url"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        url = arguments.get("url", "").strip()
        op = arguments.get("operation", "get_text")
        timeout = int(arguments.get("timeout_ms", 15000))
        max_chars = int(arguments.get("max_chars", 6000))
        wait_sel = arguments.get("wait_for_selector")
        click_sel = arguments.get("click_selector")

        if not url:
            return ToolResult(content="url is required", is_error=True)
        if not url.startswith(("http://", "https://")):
            return ToolResult(
                content="url must start with http:// or https://", is_error=True
            )

        ok, host = _domain_allowed(url)
        if not ok:
            return ToolResult(
                content=(
                    f"Domain '{host}' is not in BROWSER_AUTOMATION_ALLOWED_HOSTS. "
                    f"Set the env var to '*' (dev) or a comma list of allowed hosts."
                ),
                is_error=True,
            )

        try:
            from playwright.async_api import async_playwright  # type: ignore
        except ImportError:
            return ToolResult(
                content=(
                    "Playwright is not installed. Run:\n"
                    "  pip install playwright\n"
                    "  playwright install chromium\n"
                    "and restart the agent runtime."
                ),
                is_error=True,
                metadata={"reason": "playwright_not_installed"},
            )

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                ctx = await browser.new_context()
                page = await ctx.new_page()
                page.set_default_timeout(timeout)
                await page.goto(url, wait_until="networkidle")
                if wait_sel:
                    try:
                        await page.wait_for_selector(wait_sel, timeout=timeout)
                    except Exception:
                        pass
                if op == "click_and_get" and click_sel:
                    try:
                        await page.click(click_sel, timeout=timeout)
                        await page.wait_for_load_state("networkidle")
                    except Exception as e:
                        return ToolResult(content=f"click failed: {e}", is_error=True)

                if op == "screenshot":
                    img_bytes = await page.screenshot(type="png", full_page=False)
                    import base64

                    b64 = base64.b64encode(img_bytes).decode()
                    await browser.close()
                    return ToolResult(
                        content=f"Screenshot captured ({len(img_bytes):,} bytes PNG, base64 in metadata).",
                        metadata={"png_base64": b64, "url": url, "host": host},
                    )

                if op == "get_html":
                    html = await page.content()
                    await browser.close()
                    return ToolResult(
                        content=html[:max_chars]
                        + ("…(truncated)" if len(html) > max_chars else ""),
                        metadata={"url": url, "host": host, "full_length": len(html)},
                    )

                # default: get_text + click_and_get text-extract
                text = await page.evaluate("() => document.body.innerText")
                await browser.close()
                text = text.strip()
                return ToolResult(
                    content=text[:max_chars]
                    + ("…(truncated)" if len(text) > max_chars else ""),
                    metadata={"url": url, "host": host, "full_length": len(text)},
                )
        except Exception as e:
            return ToolResult(content=f"Browser error: {e}", is_error=True)
