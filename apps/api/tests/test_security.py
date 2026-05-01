from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.sanitize import is_safe_url, sanitize_input, strip_html


# ── Sanitization unit tests ──────────────────────────────────


def test_strip_html_removes_script_tags():
    assert strip_html('<script>alert("xss")</script>hello') == "hello"


def test_strip_html_removes_nested_tags():
    assert strip_html("<b><i>bold italic</i></b>") == "bold italic"


def test_strip_html_unescapes_entities():
    assert strip_html("&amp; &lt;tag&gt;") == "& <tag>"


def test_sanitize_input_strips_script():
    result = sanitize_input('<script>document.cookie</script>clean text')
    assert "<script>" not in result
    assert "clean text" in result


def test_sanitize_input_strips_event_handlers():
    result = sanitize_input('<img onerror="alert(1)" src="x">')
    assert "onerror" not in result


def test_sanitize_input_strips_html_tags():
    result = sanitize_input('<div class="bad">hello</div>')
    assert "<div" not in result
    assert "hello" in result


def test_sanitize_input_empty():
    assert sanitize_input("") == ""
    assert sanitize_input(None) == ""


def test_sanitize_input_preserves_plain_text():
    text = "Hello, this is a normal message with numbers 123."
    assert sanitize_input(text) == text


def test_is_safe_url_blocks_javascript():
    assert is_safe_url("javascript:alert(1)") is False
    assert is_safe_url("JAVASCRIPT:alert(1)") is False
    assert is_safe_url(" javascript:void(0)") is False


def test_is_safe_url_blocks_data():
    assert is_safe_url("data:text/html,<script>alert(1)</script>") is False


def test_is_safe_url_blocks_vbscript():
    assert is_safe_url("vbscript:MsgBox") is False


def test_is_safe_url_allows_https():
    assert is_safe_url("https://example.com/image.png") is True


def test_is_safe_url_allows_http():
    assert is_safe_url("http://example.com/image.png") is True


# ── Auth required tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_agents_requires_auth(client: AsyncClient):
    resp = await client.get("/api/agents")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_knowledge_requires_auth(client: AsyncClient):
    resp = await client.get("/api/knowledge-bases")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mcp_requires_auth(client: AsyncClient):
    resp = await client.get("/api/mcp/connections")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_settings_requires_auth(client: AsyncClient):
    resp = await client.get("/api/settings/profile")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_api_keys_requires_auth(client: AsyncClient):
    resp = await client.get("/api/api-keys")
    assert resp.status_code == 401


# ── Body size limit tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_body_size_limit_rejects_oversized(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        content=b"x" * (11 * 1024 * 1024),
        headers={"Content-Length": str(11 * 1024 * 1024), "Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error"]["code"] == 413


@pytest.mark.asyncio
async def test_body_size_allows_normal_request(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        json={"email": "x@x.com", "password": "pass"},
    )
    assert resp.status_code != 413


# ── XSS in agent creation ────────────────────────────────────


@pytest.mark.asyncio
async def test_create_agent_sanitizes_name(client: AsyncClient):
    reg_resp = await client.post("/api/auth/register", json={
        "email": "xss-agent@example.com",
        "password": "securepass123",
        "full_name": "XSS Tester",
    })
    token = reg_resp.json()["data"]["access_token"]

    resp = await client.post(
        "/api/agents",
        json={
            "name": '<script>alert("xss")</script>My Agent',
            "description": '<img onerror="alert(1)">desc',
            "system_prompt": "You are helpful.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert "<script>" not in data["name"]
    assert "onerror" not in data["description"]


@pytest.mark.asyncio
async def test_create_agent_rejects_unsafe_icon_url(client: AsyncClient):
    reg_resp = await client.post("/api/auth/register", json={
        "email": "xss-icon@example.com",
        "password": "securepass123",
        "full_name": "Icon Tester",
    })
    token = reg_resp.json()["data"]["access_token"]

    resp = await client.post(
        "/api/agents",
        json={
            "name": "Safe Agent",
            "icon_url": "javascript:alert(1)",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "Invalid icon URL" in resp.json()["error"]["message"]


# ── CORS headers ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cors_does_not_allow_wildcard_origin(client: AsyncClient):
    resp = await client.options(
        "/api/health",
        headers={
            "Origin": "https://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    allow_origin = resp.headers.get("access-control-allow-origin", "")
    assert allow_origin != "*"
