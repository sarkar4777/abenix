"""GitHub REST API tool for repository inspection and code exploration."""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

from engine.tools.base import BaseTool, ToolResult

GITHUB_API_BASE = "https://api.github.com"
MAX_CONTENT_LENGTH = 100_000


class GitHubTool(BaseTool):
    name = "github_tool"
    description = (
        "Interact with the GitHub REST API to inspect repositories, read files, "
        "search code, list issues and pull requests, view commits, check CI workflows, "
        "and compare branches. Requires a GITHUB_TOKEN environment variable."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "get_repo",
                    "list_files",
                    "read_file",
                    "search_code",
                    "list_issues",
                    "list_pull_requests",
                    "get_commits",
                    "get_languages",
                    "get_workflows",
                    "compare_branches",
                ],
                "description": "GitHub operation to perform",
            },
            "owner": {
                "type": "string",
                "description": "Repository owner (user or org)",
            },
            "repo": {
                "type": "string",
                "description": "Repository name",
            },
            "path": {
                "type": "string",
                "description": "File path (for read_file)",
                "default": "",
            },
            "query": {
                "type": "string",
                "description": "Search query (for search_code)",
                "default": "",
            },
            "branch": {
                "type": "string",
                "description": "Branch name",
                "default": "main",
            },
            "state": {
                "type": "string",
                "enum": ["open", "closed", "all"],
                "default": "open",
            },
            "per_page": {
                "type": "integer",
                "description": "Results per page",
                "default": 30,
                "minimum": 1,
                "maximum": 100,
            },
            "base": {
                "type": "string",
                "description": "Base branch for comparison",
                "default": "main",
            },
            "head": {
                "type": "string",
                "description": "Head branch for comparison",
                "default": "",
            },
        },
        "required": ["operation", "owner", "repo"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        token = os.environ.get("GITHUB_TOKEN", "")
        operation = arguments.get("operation", "")

        # Public read-only operations work without auth (rate-limited to 60/hour/IP
        # for unauthenticated requests; 5000/hour with a token).
        PUBLIC_READ_OPS = {
            "get_repo",
            "list_files",
            "read_file",
            "get_commits",
            "get_languages",
            "get_workflows",
            "compare_branches",
            "list_issues",
            "list_pull_requests",
            "search_code",
        }
        if not token and operation not in PUBLIC_READ_OPS:
            return ToolResult(
                content=(
                    f"GITHUB_TOKEN environment variable is not set and "
                    f"operation '{operation}' requires authentication. "
                    f"Set GITHUB_TOKEN or use one of: {sorted(PUBLIC_READ_OPS)}"
                ),
                is_error=True,
            )

        operation = arguments.get("operation", "")
        owner = arguments.get("owner", "")
        repo = arguments.get("repo", "")

        if not operation or not owner or not repo:
            return ToolResult(
                content="Error: operation, owner, and repo are required",
                is_error=True,
            )

        handlers: dict[str, Any] = {
            "get_repo": self._get_repo,
            "list_files": self._list_files,
            "read_file": self._read_file,
            "search_code": self._search_code,
            "list_issues": self._list_issues,
            "list_pull_requests": self._list_pull_requests,
            "get_commits": self._get_commits,
            "get_languages": self._get_languages,
            "get_workflows": self._get_workflows,
            "compare_branches": self._compare_branches,
        }

        fn = handlers.get(operation)
        if not fn:
            return ToolResult(
                content=f"Unknown operation: {operation}",
                is_error=True,
            )

        start = time.monotonic()
        try:
            result = await fn(token, owner, repo, arguments)
            elapsed = round(time.monotonic() - start, 3)
            output = json.dumps(result, indent=2, default=str)
            return ToolResult(
                content=output,
                metadata={
                    "operation": operation,
                    "owner": owner,
                    "repo": repo,
                    "elapsed_seconds": elapsed,
                },
            )
        except Exception as e:
            elapsed = round(time.monotonic() - start, 3)
            return ToolResult(
                content=f"GitHub API error: {e}",
                is_error=True,
                metadata={
                    "operation": operation,
                    "owner": owner,
                    "repo": repo,
                    "elapsed_seconds": elapsed,
                },
            )

    # Internal helpers

    def _headers(self, token: str) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Abenix-GitHubTool/1.0",
        }
        # Only include Authorization when a token is provided
        # (public API works without auth but is rate-limited).
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _request(
        self,
        token: str,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Make an authenticated request to the GitHub API and return parsed JSON."""
        import httpx

        url = f"{GITHUB_API_BASE}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method,
                url,
                headers=self._headers(token),
                params=params,
            )

        if response.status_code == 404:
            raise ValueError(f"Repository/resource not found: {path}")
        if response.status_code == 403:
            raise ValueError(
                "GitHub API rate limit exceeded or insufficient permissions"
            )
        if response.status_code >= 400:
            text = response.text[:500]
            raise ValueError(f"GitHub API error ({response.status_code}): {text}")

        return response.json()

    # Operations

    async def _get_repo(
        self,
        token: str,
        owner: str,
        repo: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        data = await self._request(token, "GET", f"/repos/{owner}/{repo}")
        license_info = data.get("license") or {}
        return {
            "name": data.get("name"),
            "full_name": data.get("full_name"),
            "description": data.get("description"),
            "language": data.get("language"),
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "topics": data.get("topics", []),
            "default_branch": data.get("default_branch"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "license": license_info.get("spdx_id"),
            "is_archived": data.get("archived", False),
            "size": data.get("size", 0),
        }

    async def _list_files(
        self,
        token: str,
        owner: str,
        repo: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        branch = arguments.get("branch", "")
        per_page = min(max(arguments.get("per_page", 30), 1), 100)
        # Auto-detect default branch when not specified (handles main vs master)
        if not branch:
            repo_info = await self._request(token, "GET", f"/repos/{owner}/{repo}")
            branch = repo_info.get("default_branch", "main")
        data = await self._request(
            token,
            "GET",
            f"/repos/{owner}/{repo}/git/trees/{branch}",
            params={"recursive": "1"},
        )
        tree = data.get("tree", [])
        files = [
            {
                "path": item.get("path"),
                "type": item.get("type"),
                "size": item.get("size"),
            }
            for item in tree[:per_page]
        ]
        return {
            "files": files,
            "total_count": len(tree),
        }

    async def _read_file(
        self,
        token: str,
        owner: str,
        repo: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        path = arguments.get("path", "")
        branch = arguments.get("branch", "main")
        if not path:
            raise ValueError("path is required for read_file operation")

        data = await self._request(
            token,
            "GET",
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": branch},
        )

        encoding = data.get("encoding", "")
        raw_content = data.get("content", "")
        sha = data.get("sha", "")
        size = data.get("size", 0)

        content = ""
        if encoding == "base64" and raw_content:
            try:
                content = base64.b64decode(raw_content).decode(
                    "utf-8", errors="replace"
                )
            except Exception:
                content = "[Unable to decode file content]"
        else:
            content = raw_content

        # Truncate oversized content
        if len(content) > MAX_CONTENT_LENGTH:
            content = (
                content[:MAX_CONTENT_LENGTH]
                + f"\n[Truncated at {MAX_CONTENT_LENGTH:,} characters]"
            )

        return {
            "path": path,
            "content": content,
            "size": size,
            "sha": sha,
            "encoding": encoding,
        }

    async def _search_code(
        self,
        token: str,
        owner: str,
        repo: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        query = arguments.get("query", "")
        per_page = min(max(arguments.get("per_page", 30), 1), 100)
        if not query:
            raise ValueError("query is required for search_code operation")

        data = await self._request(
            token,
            "GET",
            "/search/code",
            params={
                "q": f"{query}+repo:{owner}/{repo}",
                "per_page": per_page,
            },
        )
        items = data.get("items", [])[:per_page]
        return {
            "total_count": data.get("total_count", 0),
            "items": [
                {
                    "path": item.get("path"),
                    "name": item.get("name"),
                    "score": item.get("score"),
                    "repository.full_name": (item.get("repository") or {}).get(
                        "full_name"
                    ),
                    "html_url": item.get("html_url"),
                }
                for item in items
            ],
        }

    async def _list_issues(
        self,
        token: str,
        owner: str,
        repo: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        state = arguments.get("state", "open")
        per_page = min(max(arguments.get("per_page", 30), 1), 100)

        data = await self._request(
            token,
            "GET",
            f"/repos/{owner}/{repo}/issues",
            params={"state": state, "per_page": per_page},
        )
        issues = [
            {
                "number": item.get("number"),
                "title": item.get("title"),
                "state": item.get("state"),
                "labels": [label.get("name") for label in item.get("labels", [])],
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "user.login": (item.get("user") or {}).get("login"),
                "comments": item.get("comments", 0),
            }
            for item in data[:per_page]
        ]
        return {
            "issues": issues,
            "total_count": len(issues),
        }

    async def _list_pull_requests(
        self,
        token: str,
        owner: str,
        repo: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        state = arguments.get("state", "open")
        per_page = min(max(arguments.get("per_page", 30), 1), 100)

        data = await self._request(
            token,
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={"state": state, "per_page": per_page},
        )
        pull_requests = [
            {
                "number": item.get("number"),
                "title": item.get("title"),
                "state": item.get("state"),
                "user.login": (item.get("user") or {}).get("login"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "merged_at": item.get("merged_at"),
                "head.ref": (item.get("head") or {}).get("ref"),
                "base.ref": (item.get("base") or {}).get("ref"),
                "draft": item.get("draft", False),
            }
            for item in data[:per_page]
        ]
        return {
            "pull_requests": pull_requests,
            "total_count": len(pull_requests),
        }

    async def _get_commits(
        self,
        token: str,
        owner: str,
        repo: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        per_page = min(max(arguments.get("per_page", 30), 1), 100)
        branch = arguments.get("branch", "main")

        data = await self._request(
            token,
            "GET",
            f"/repos/{owner}/{repo}/commits",
            params={"per_page": per_page, "sha": branch},
        )
        commits = [
            {
                "sha": (item.get("sha") or "")[:8],
                "message": ((item.get("commit") or {}).get("message") or "")[:200],
                "author": ((item.get("commit") or {}).get("author") or {}).get("name"),
                "date": ((item.get("commit") or {}).get("author") or {}).get("date"),
                "additions": (item.get("stats") or {}).get("additions"),
                "deletions": (item.get("stats") or {}).get("deletions"),
            }
            for item in data[:per_page]
        ]
        return {
            "commits": commits,
            "total_count": len(commits),
        }

    async def _get_languages(
        self,
        token: str,
        owner: str,
        repo: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        data = await self._request(
            token,
            "GET",
            f"/repos/{owner}/{repo}/languages",
        )
        total_bytes = sum(data.values()) if data else 0
        primary_language = max(data, key=data.get) if data else None  # type: ignore[arg-type]
        return {
            "languages": data,
            "total_bytes": total_bytes,
            "primary_language": primary_language,
        }

    async def _get_workflows(
        self,
        token: str,
        owner: str,
        repo: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        data = await self._request(
            token,
            "GET",
            f"/repos/{owner}/{repo}/actions/workflows",
        )
        workflows_raw = data.get("workflows", [])
        workflows = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "path": item.get("path"),
                "state": item.get("state"),
                "created_at": item.get("created_at"),
            }
            for item in workflows_raw
        ]
        return {
            "workflows": workflows,
            "total_count": data.get("total_count", len(workflows)),
        }

    async def _compare_branches(
        self,
        token: str,
        owner: str,
        repo: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        base = arguments.get("base", "main")
        head = arguments.get("head", "")
        if not head:
            raise ValueError("head is required for compare_branches operation")

        data = await self._request(
            token,
            "GET",
            f"/repos/{owner}/{repo}/compare/{base}...{head}",
        )
        files = data.get("files", [])
        changed_files = [
            {
                "filename": f.get("filename"),
                "status": f.get("status"),
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "changes": f.get("changes", 0),
            }
            for f in files
        ]
        return {
            "ahead_by": data.get("ahead_by", 0),
            "behind_by": data.get("behind_by", 0),
            "total_commits": data.get("total_commits", 0),
            "changed_files": changed_files,
        }
