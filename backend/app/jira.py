"""Jira Cloud REST v3 client: the only module that talks to Jira.

Basic auth with email + API token (developer.atlassian.com, "Basic auth for REST APIs").
Base URL, email, token and project key come from runtime settings (web UI, env fallback).
"""

from typing import Any

import httpx

from app import runtime

TIMEOUT_S = 10.0


class JiraError(RuntimeError):
    """Jira could not be reached or answered with an error."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def configured() -> bool:
    return all(runtime.get(k) for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"))


def base_url() -> str:
    return runtime.get("JIRA_BASE_URL").strip().rstrip("/")


async def _request(method: str, path: str, **kw: Any) -> Any:
    if not configured():
        raise JiraError("Jira is not configured")
    auth = (runtime.get("JIRA_EMAIL"), runtime.get("JIRA_API_TOKEN"))
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, auth=auth) as client:
            r = await client.request(
                method, f"{base_url()}{path}", headers={"Accept": "application/json"}, **kw
            )
    except httpx.HTTPError as e:
        raise JiraError(f"Jira request failed: {e.__class__.__name__}") from None
    if r.status_code >= 400:
        raise JiraError(f"Jira {path} -> {r.status_code}", r.status_code)
    return r.json() if r.content else None


async def myself() -> dict[str, Any]:
    """GET /rest/api/3/myself: {accountId, displayName, emailAddress, ...}."""
    return await _request("GET", "/rest/api/3/myself") or {}
