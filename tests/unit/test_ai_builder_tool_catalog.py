from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.routers import ai_builder


def test_tool_with_missing_package_is_not_offered():
    catalog = [("browser_automation", "drive a browser"), ("http_client", "GET a URL")]

    async def policy(_tenant):
        return {"enabled": True}

    with (
        patch.object(ai_builder, "_get_tools", return_value=catalog),
        patch.object(ai_builder, "_get_sandbox_policy", policy),
        patch("importlib.util.find_spec", return_value=None),
    ):
        names = [n for n, _ in asyncio.run(ai_builder._get_tools_filtered("t"))]
    assert names == ["http_client"]


def test_tool_with_package_present_is_offered():
    catalog = [("browser_automation", "drive a browser")]

    async def policy(_tenant):
        return {"enabled": True}

    with (
        patch.object(ai_builder, "_get_tools", return_value=catalog),
        patch.object(ai_builder, "_get_sandbox_policy", policy),
        patch("importlib.util.find_spec", return_value=object()),
    ):
        names = [n for n, _ in asyncio.run(ai_builder._get_tools_filtered("t"))]
    assert names == ["browser_automation"]
