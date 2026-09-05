"""GitHub — issues and pull requests assigned to you, as work items.

Uses a fine-grained personal access token with read-only access. The token is
stored encrypted; the search is scoped to things assigned to or opened by you.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.connectors.base import (
    Connector,
    ConnectorCategory,
    ConnectorError,
    ConnectorField,
    ConnectorMode,
    FieldType,
    SyncContext,
    SyncResult,
)
from app.connectors.registry import register
from app.models.tasks import Area, TaskStatus
from app.services.upserts import upsert_task

API = "https://api.github.com"


@register
class GitHubWorkConnector(Connector):
    slug = "github_work"
    name = "GitHub issues & PRs"
    category = ConnectorCategory.work
    mode = ConnectorMode.pull
    description = "Open issues and pull requests assigned to you become work tasks."
    provides = ("tasks",)
    docs_url = "https://github.com/settings/tokens"
    fields = (
        ConnectorField(
            key="token",
            label="Personal access token",
            type=FieldType.password,
            secret=True,
            help="Fine-grained token, read-only on issues and pull requests.",
        ),
        ConnectorField(key="username", label="GitHub username"),
        ConnectorField(
            key="include_prs",
            label="Include pull requests",
            type=FieldType.checkbox,
            required=False,
            default=True,
        ),
    )

    def sync(self, ctx: SyncContext) -> SyncResult:
        token = ctx.secrets.get("token", "")
        username = ctx.opt("username", "")
        if not token or not username:
            raise ConnectorError("Token and username are both required.")

        query = f"assignee:{username} state:open"
        if not ctx.opt("include_prs", True):
            query += " type:issue"

        try:
            response = httpx.get(
                f"{API}/search/issues",
                params={"q": query, "per_page": 50, "sort": "updated"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Could not reach GitHub: {exc}") from exc

        if response.status_code == 401:
            raise ConnectorError("GitHub rejected the token (401). Regenerate it.")
        if response.status_code >= 400:
            raise ConnectorError(f"GitHub error {response.status_code}: {response.text[:200]}")

        result = SyncResult()
        for item in response.json().get("items", []):
            is_pr = "pull_request" in item
            repo = item.get("repository_url", "").rsplit("/", 2)[-2:]
            repo_name = "/".join(repo) if len(repo) == 2 else ""
            milestone = item.get("milestone") or {}
            due = milestone.get("due_on")

            created = upsert_task(
                ctx.db,
                user_id=ctx.user_id,
                connection_id=ctx.connection_id,
                external_id=str(item["id"]),
                defaults={
                    "title": f"{'PR' if is_pr else 'Issue'} {repo_name}#{item['number']}: {item['title']}",
                    "notes": (item.get("body") or "")[:2000],
                    "area": Area.work,
                    "status": TaskStatus.todo,
                    "source": "github",
                    "priority": 2 if is_pr else 3,
                    "url": item.get("html_url", ""),
                    "due_at": _parse(due),
                    "tags": ["github", "pr" if is_pr else "issue"],
                },
            )
            result.created += int(created)
            result.updated += int(not created)

        result.message = f"{result.created} new, {result.updated} updated from GitHub"
        return result


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
