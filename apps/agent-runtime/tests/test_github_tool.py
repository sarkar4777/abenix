"""Tests for the GitHub REST API tool with mocked httpx responses."""

from __future__ import annotations

import base64
import json
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.tools.github_tool import GitHubTool


# ── Helpers ───────────────────────────────────────────────────────


def mock_response(data: Any, status_code: int = 200) -> MagicMock:
    """Create a mock httpx Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = json.dumps(data) if isinstance(data, (dict, list)) else str(data)
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


def _build_mock_client(response: MagicMock) -> MagicMock:
    """Build a mock httpx.AsyncClient context manager that returns the given response."""
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=response)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def tool() -> GitHubTool:
    with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token-123"}):
        yield GitHubTool()


# ── Tests ─────────────────────────────────────────────────────────


class TestGitHubTool:
    @pytest.mark.asyncio
    async def test_get_repo_metadata(self, tool: GitHubTool) -> None:
        """get_repo returns stars, forks, language from the API response."""
        api_data = {
            "name": "abenix",
            "full_name": "owner/abenix",
            "description": "AI agent marketplace",
            "language": "Python",
            "stargazers_count": 100,
            "forks_count": 50,
            "open_issues_count": 5,
            "topics": ["ai", "agents"],
            "default_branch": "main",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-06-01T00:00:00Z",
            "license": {"spdx_id": "MIT"},
            "archived": False,
            "size": 12345,
        }

        mock_cm = _build_mock_client(mock_response(api_data))

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token-123"}), \
             patch("httpx.AsyncClient", return_value=mock_cm):
            result = await tool.execute({
                "operation": "get_repo",
                "owner": "owner",
                "repo": "abenix",
            })

        assert not result.is_error
        parsed = json.loads(result.content)
        assert parsed["stars"] == 100
        assert parsed["forks"] == 50
        assert parsed["language"] == "Python"
        assert parsed["name"] == "abenix"

    @pytest.mark.asyncio
    async def test_list_files_recursive(self, tool: GitHubTool) -> None:
        """list_files returns the file tree from the API."""
        api_data = {
            "tree": [
                {"path": "README.md", "type": "blob", "size": 1024},
                {"path": "src/main.py", "type": "blob", "size": 2048},
                {"path": "src", "type": "tree", "size": None},
            ]
        }

        mock_cm = _build_mock_client(mock_response(api_data))

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token-123"}), \
             patch("httpx.AsyncClient", return_value=mock_cm):
            result = await tool.execute({
                "operation": "list_files",
                "owner": "owner",
                "repo": "abenix",
                "branch": "main",
            })

        assert not result.is_error
        parsed = json.loads(result.content)
        assert "files" in parsed
        assert len(parsed["files"]) == 3
        paths = [f["path"] for f in parsed["files"]]
        assert "README.md" in paths
        assert "src/main.py" in paths

    @pytest.mark.asyncio
    async def test_read_file_decodes_base64(self, tool: GitHubTool) -> None:
        """read_file correctly decodes base64-encoded content."""
        encoded = base64.b64encode(b"Hello World").decode("utf-8")
        api_data = {
            "content": encoded,
            "encoding": "base64",
            "sha": "abc123def",
            "size": 11,
        }

        mock_cm = _build_mock_client(mock_response(api_data))

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token-123"}), \
             patch("httpx.AsyncClient", return_value=mock_cm):
            result = await tool.execute({
                "operation": "read_file",
                "owner": "owner",
                "repo": "abenix",
                "path": "README.md",
            })

        assert not result.is_error
        parsed = json.loads(result.content)
        assert parsed["content"] == "Hello World"
        assert parsed["encoding"] == "base64"
        assert parsed["sha"] == "abc123def"

    @pytest.mark.asyncio
    async def test_search_code_returns_matches(self, tool: GitHubTool) -> None:
        """search_code returns matching code results."""
        api_data = {
            "total_count": 2,
            "items": [
                {
                    "path": "src/engine.py",
                    "name": "engine.py",
                    "score": 1.5,
                    "repository": {"full_name": "owner/abenix"},
                    "html_url": "https://github.com/owner/abenix/blob/main/src/engine.py",
                },
                {
                    "path": "src/tools.py",
                    "name": "tools.py",
                    "score": 1.2,
                    "repository": {"full_name": "owner/abenix"},
                    "html_url": "https://github.com/owner/abenix/blob/main/src/tools.py",
                },
            ],
        }

        mock_cm = _build_mock_client(mock_response(api_data))

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token-123"}), \
             patch("httpx.AsyncClient", return_value=mock_cm):
            result = await tool.execute({
                "operation": "search_code",
                "owner": "owner",
                "repo": "abenix",
                "query": "PipelineExecutor",
            })

        assert not result.is_error
        parsed = json.loads(result.content)
        assert parsed["total_count"] == 2
        assert len(parsed["items"]) == 2
        assert parsed["items"][0]["path"] == "src/engine.py"

    @pytest.mark.asyncio
    async def test_list_issues_with_state_filter(
        self, tool: GitHubTool
    ) -> None:
        """list_issues returns issues filtered by state."""
        api_data = [
            {
                "number": 42,
                "title": "Bug report",
                "state": "open",
                "labels": [{"name": "bug"}],
                "created_at": "2025-03-01T00:00:00Z",
                "updated_at": "2025-03-15T00:00:00Z",
                "user": {"login": "tester"},
                "comments": 3,
            },
            {
                "number": 43,
                "title": "Feature request",
                "state": "open",
                "labels": [{"name": "enhancement"}],
                "created_at": "2025-03-05T00:00:00Z",
                "updated_at": "2025-03-10T00:00:00Z",
                "user": {"login": "dev"},
                "comments": 1,
            },
        ]

        mock_cm = _build_mock_client(mock_response(api_data))

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token-123"}), \
             patch("httpx.AsyncClient", return_value=mock_cm):
            result = await tool.execute({
                "operation": "list_issues",
                "owner": "owner",
                "repo": "abenix",
                "state": "open",
            })

        assert not result.is_error
        parsed = json.loads(result.content)
        assert parsed["total_count"] == 2
        assert parsed["issues"][0]["number"] == 42
        assert parsed["issues"][0]["state"] == "open"
        assert "bug" in parsed["issues"][0]["labels"]

    @pytest.mark.asyncio
    async def test_list_pull_requests(self, tool: GitHubTool) -> None:
        """list_pull_requests returns PRs from the API."""
        api_data = [
            {
                "number": 101,
                "title": "Add pipeline engine",
                "state": "open",
                "user": {"login": "contributor"},
                "created_at": "2025-04-01T00:00:00Z",
                "updated_at": "2025-04-05T00:00:00Z",
                "merged_at": None,
                "head": {"ref": "feature/pipeline"},
                "base": {"ref": "main"},
                "draft": False,
            },
        ]

        mock_cm = _build_mock_client(mock_response(api_data))

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token-123"}), \
             patch("httpx.AsyncClient", return_value=mock_cm):
            result = await tool.execute({
                "operation": "list_pull_requests",
                "owner": "owner",
                "repo": "abenix",
            })

        assert not result.is_error
        parsed = json.loads(result.content)
        assert parsed["total_count"] == 1
        pr = parsed["pull_requests"][0]
        assert pr["number"] == 101
        assert pr["title"] == "Add pipeline engine"
        assert pr["head.ref"] == "feature/pipeline"
        assert pr["base.ref"] == "main"

    @pytest.mark.asyncio
    async def test_get_commits_with_limit(self, tool: GitHubTool) -> None:
        """get_commits returns limited commits when per_page is specified."""
        api_data = [
            {
                "sha": "abc12345",
                "commit": {
                    "message": "Initial commit",
                    "author": {"name": "Dev", "date": "2025-01-01T00:00:00Z"},
                },
                "stats": {"additions": 100, "deletions": 0},
            },
            {
                "sha": "def67890",
                "commit": {
                    "message": "Add tests",
                    "author": {"name": "Dev", "date": "2025-01-02T00:00:00Z"},
                },
                "stats": {"additions": 50, "deletions": 10},
            },
        ]

        mock_cm = _build_mock_client(mock_response(api_data))

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token-123"}), \
             patch("httpx.AsyncClient", return_value=mock_cm):
            result = await tool.execute({
                "operation": "get_commits",
                "owner": "owner",
                "repo": "abenix",
                "per_page": 5,
            })

        assert not result.is_error
        parsed = json.loads(result.content)
        assert parsed["total_count"] == 2
        assert parsed["commits"][0]["sha"] == "abc12345"[:8]
        assert parsed["commits"][0]["message"] == "Initial commit"

    @pytest.mark.asyncio
    async def test_get_languages(self, tool: GitHubTool) -> None:
        """get_languages returns language breakdown."""
        api_data = {"Python": 50000, "JavaScript": 30000}

        mock_cm = _build_mock_client(mock_response(api_data))

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token-123"}), \
             patch("httpx.AsyncClient", return_value=mock_cm):
            result = await tool.execute({
                "operation": "get_languages",
                "owner": "owner",
                "repo": "abenix",
            })

        assert not result.is_error
        parsed = json.loads(result.content)
        assert parsed["languages"]["Python"] == 50000
        assert parsed["languages"]["JavaScript"] == 30000
        assert parsed["total_bytes"] == 80000
        assert parsed["primary_language"] == "Python"

    @pytest.mark.asyncio
    async def test_missing_token_returns_error(self) -> None:
        """When GITHUB_TOKEN is not set, the tool returns an error."""
        with patch.dict(os.environ, {"GITHUB_TOKEN": ""}, clear=False):
            tool = GitHubTool()
            result = await tool.execute({
                "operation": "get_repo",
                "owner": "owner",
                "repo": "abenix",
            })

        assert result.is_error
        assert "GITHUB_TOKEN" in result.content

    @pytest.mark.asyncio
    async def test_api_error_returns_error(self, tool: GitHubTool) -> None:
        """A 404 API response returns a proper error."""
        error_response = mock_response(
            {"message": "Not Found"}, status_code=404
        )
        mock_cm = _build_mock_client(error_response)

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token-123"}), \
             patch("httpx.AsyncClient", return_value=mock_cm):
            result = await tool.execute({
                "operation": "get_repo",
                "owner": "owner",
                "repo": "nonexistent",
            })

        assert result.is_error
        assert "error" in result.content.lower() or "not found" in result.content.lower()
