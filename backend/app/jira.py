"""Jira Cloud REST v3 client: the only module that talks to Jira.

Basic auth with email + API token (developer.atlassian.com, "Basic auth for REST APIs").
Base URL, email, token and project key come from runtime settings (web UI, env fallback).
M7.4: read a ticket for the in-call answer, create issues from action items (manual, post-call
auto-create, escalation timeout). Descriptions are ADF (v3 rejects a plain string).
"""

import asyncio
import logging
import re
from typing import Any

import httpx

from app import db, runtime

log = logging.getLogger(__name__)

TIMEOUT_S = 10.0
DESCRIPTION_MAX = 600
SUMMARY_MAX = 120
_FIELDS = "summary,status,assignee,duedate,description"


class JiraError(RuntimeError):
    """Jira could not be reached or answered with an error."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def configured() -> bool:
    return all(runtime.get(k) for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"))


def base_url() -> str:
    return runtime.get("JIRA_BASE_URL").strip().rstrip("/")


def project_key() -> str:
    return runtime.get("JIRA_PROJECT_KEY").strip().upper()


def browse_url(key: str) -> str:
    return f"{base_url()}/browse/{key}"


def _error_text(r: httpx.Response) -> str:
    """Jira's {errorMessages: [...], errors: {field: msg}} as one line, else ""."""
    try:
        body = r.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    parts = [str(m) for m in body.get("errorMessages") or []]
    errs = body.get("errors")
    if isinstance(errs, dict):
        parts += [f"{k}: {v}" for k, v in errs.items()]
    return "; ".join(parts)


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
        detail = _error_text(r)
        msg = f"Jira {path} -> {r.status_code}" + (f": {detail}" if detail else "")
        raise JiraError(msg, r.status_code)
    try:
        return r.json() if r.content else None
    except ValueError:
        raise JiraError(f"Jira {path}: response is not JSON", r.status_code) from None


async def myself() -> dict[str, Any]:
    """GET /rest/api/3/myself: {accountId, displayName, emailAddress, ...}."""
    return await _request("GET", "/rest/api/3/myself") or {}


# --- ADF ----------------------------------------------------------------------

_BLOCK_END = {"paragraph", "heading", "listItem", "blockquote", "codeBlock"}


def adf_text(doc: Any, limit: int = DESCRIPTION_MAX) -> str:
    """Atlassian Document Format -> plain text (text nodes, mention/emoji attrs.text,
    newline after blocks, hardBreak). A plain string passes through. Truncated to `limit`."""
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n)
            return
        if not isinstance(node, dict):
            return
        typ = node.get("type")
        if typ == "text":
            out.append(str(node.get("text") or ""))
        elif typ == "hardBreak":
            out.append("\n")
        elif typ in ("mention", "emoji", "inlineCard"):
            attrs = node.get("attrs") or {}
            out.append(str(attrs.get("text") or attrs.get("url") or ""))
        walk(node.get("content") or [])
        if typ in _BLOCK_END:
            out.append("\n")

    if isinstance(doc, str):
        text = doc
    else:
        walk(doc)
        text = "".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def adf_doc(text: str) -> dict[str, Any]:
    """Plain text -> ADF doc, one paragraph per non-empty line."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()] or ["-"]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": ln}]} for ln in lines
        ],
    }


# --- keys in a spoken question --------------------------------------------------

# Lazy prefix so "PTW12" is PTW-12, not PTW1-2.
KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9}?)[\s-]?(\d{1,6})\b", re.IGNORECASE)
_LITERAL_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-(\d{1,6})\b")  # "PTW-12" as Jira writes it
_WORD_RE = re.compile(
    r"\b(?:ticket|issue|task|story|bug)(?:\s+(?:number|no\.?))?\s*#?\s*(\d{1,6})\b",
    re.IGNORECASE,
)


def extract_keys(text: str, default_project: str | None = None) -> list[str]:
    """Jira keys in an ASR question, in order, deduped, uppercased.

    "PTW-12" always counts. Looser forms ("ptw 12", "PTW12") count only for the configured
    project or an all-caps prefix, so "Postgres 17" or "limit 100" never become keys.
    "ticket 12" / "issue number 12" -> <project>-12 when a default project is set.
    """
    text = text or ""
    project = (default_project or "").strip().upper()
    found: list[tuple[int, str]] = [
        (m.start(), f"{m.group(1)}-{int(m.group(2))}") for m in _LITERAL_RE.finditer(text)
    ]
    for m in KEY_RE.finditer(text):
        prefix, num = m.group(1), m.group(2)
        if prefix.upper() == project or prefix.isupper():
            found.append((m.start(), f"{prefix.upper()}-{int(num)}"))
    if project:
        found += [(m.start(), f"{project}-{int(m.group(1))}") for m in _WORD_RE.finditer(text)]
    return list(dict.fromkeys(key for _, key in sorted(found)))


# --- issues ---------------------------------------------------------------------


async def get_issue(key: str) -> dict[str, Any] | None:
    """{key, summary, status, assignee, due, description, url}, or None on 404."""
    try:
        raw = await _request("GET", f"/rest/api/3/issue/{key}", params={"fields": _FIELDS})
    except JiraError as e:
        if e.status == 404:
            return None
        raise
    raw = raw if isinstance(raw, dict) else {}
    f = raw.get("fields") or {}
    status = f.get("status")
    assignee = f.get("assignee")
    real_key = str(raw.get("key") or key)
    return {
        "key": real_key,
        "summary": str(f.get("summary") or ""),
        "status": status.get("name") if isinstance(status, dict) else None,
        "assignee": assignee.get("displayName") if isinstance(assignee, dict) else None,
        "due": f.get("duedate"),
        "description": adf_text(f.get("description")),
        "url": browse_url(real_key),
    }


async def find_account_id(email: str | None) -> str | None:
    """Best effort: accountId for an email (GET /rest/api/3/user/search), else None."""
    if not email:
        return None
    try:
        users = await _request("GET", "/rest/api/3/user/search", params={"query": email})
    except JiraError as e:
        log.info("jira user search failed for %s: %s", email, e)
        return None
    users = [u for u in users or [] if isinstance(u, dict) and u.get("accountId")]
    if not users:
        return None
    exact = [u for u in users if str(u.get("emailAddress") or "").lower() == email.lower()]
    return str((exact or users)[0]["accountId"])


async def _fallback_issuetype(project: str) -> dict[str, str] | None:
    """First non-subtask issue type of the project (when "Task" doesn't exist)."""
    data = await _request("GET", f"/rest/api/3/issue/createmeta/{project}/issuetypes")
    if isinstance(data, dict):
        data = data.get("issueTypes") or data.get("values") or []
    for t in data or []:
        if isinstance(t, dict) and not t.get("subtask") and t.get("id"):
            return {"id": str(t["id"])}
    return None


async def create_issue(
    summary: str,
    description: str,
    due: str | None = None,
    assignee_email: str | None = None,
) -> dict[str, str]:
    """POST /rest/api/3/issue in JIRA_PROJECT_KEY -> {"key", "url"}. Raises JiraError.
    Assignee is best effort: an unknown email leaves the issue unassigned."""
    project = project_key()
    if not project:
        raise JiraError("JIRA_PROJECT_KEY is not set")
    fields: dict[str, Any] = {
        "project": {"key": project},
        "issuetype": {"name": "Task"},
        "summary": " ".join((summary or "").split())[:SUMMARY_MAX] or "Follow-up",
        "description": adf_doc(description),
    }
    if due and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(due).strip()):
        fields["duedate"] = str(due).strip()
    account = await find_account_id(assignee_email)
    if account:
        fields["assignee"] = {"accountId": account}
    try:
        out = await _request("POST", "/rest/api/3/issue", json={"fields": fields})
    except JiraError as e:
        if e.status != 400 or "issuetype" not in str(e).lower():
            raise
        fallback = await _fallback_issuetype(project)
        if fallback is None:
            raise
        fields["issuetype"] = fallback
        out = await _request("POST", "/rest/api/3/issue", json={"fields": fields})
    key = str((out or {}).get("key") or "") if isinstance(out, dict) else ""
    if not key:
        raise JiraError("Jira returned no issue key")
    return {"key": key, "url": browse_url(key)}


# --- action items -> issues (manual, post-call auto-create, escalation timeout) ----

_locks: dict[str, asyncio.Lock] = {}
_tasks: set[asyncio.Task] = set()


def _lock(meeting_id: str) -> asyncio.Lock:
    return _locks.setdefault(meeting_id, asyncio.Lock())


def spawn(coro) -> asyncio.Task:
    """Fire-and-forget with a strong reference (asyncio keeps only weak ones)."""
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def item_description(meeting: dict[str, Any], item: dict[str, Any]) -> str:
    title = meeting.get("title") or "a call"
    return (
        f"From meeting {title} (Call Crew). Owner: {item.get('owner') or 'unassigned'}. "
        f"Due: {item.get('due') or 'not set'}."
    )


async def _expert_email(owner: Any) -> str | None:
    """Email of the expert whose name matches the item owner (assignee, best effort)."""
    name = str(owner or "").strip().lower()
    if not name:
        return None
    try:
        from app import escalation  # lazy: escalation -> speech -> meetings (cycle)

        for e in await escalation.load_experts():
            if e.name.strip().lower() == name:
                return e.email or None
    except Exception as e:
        log.info("jira assignee lookup failed: %s", e)
    return None


async def _create_and_save(meeting: dict[str, Any], item: dict[str, Any]) -> dict[str, str]:
    issue = await create_issue(
        str(item.get("text") or ""),
        item_description(meeting, item),
        due=item.get("due"),
        assignee_email=await _expert_email(item.get("owner")),
    )
    await db.set_action_item_jira(meeting["id"], item["id"], issue["key"], issue["url"])
    return issue


async def issue_for_item(meeting_id: str, item_id: str) -> dict[str, str] | None:
    """Idempotent: the item's existing {key, url}, or a new issue saved on the item.
    None if the meeting or item doesn't exist. Raises JiraError on Jira failure."""
    async with _lock(meeting_id):
        meeting = await db.get_meeting(meeting_id)
        if meeting is None:
            return None
        items = db.with_item_ids(meeting.get("action_items"))
        item = next((it for it in items if it["id"] == item_id), None)
        if item is None:
            return None
        if item.get("jira_key"):
            key = str(item["jira_key"])
            return {"key": key, "url": str(item.get("jira_url") or browse_url(key))}
        return await _create_and_save(meeting, item)


async def auto_create(meeting_id: str) -> int:
    """Post-call: an issue for every action item without jira_key. Idempotent (per-meeting
    lock, items re-read under it, keys saved one by one). Returns the count. Never raises."""
    created = 0
    try:
        async with _lock(meeting_id):
            meeting = await db.get_meeting(meeting_id)
            for item in db.with_item_ids((meeting or {}).get("action_items")):
                if item.get("jira_key") or not str(item.get("text") or "").strip():
                    continue
                try:
                    await _create_and_save(meeting, item)
                    created += 1
                except JiraError as e:
                    log.warning("jira auto-create %s/%s failed: %s", meeting_id, item["id"], e)
    except Exception:
        log.exception("jira auto-create failed for %s", meeting_id)
    log.info("jira auto-create %s: %d issue(s)", meeting_id, created)
    return created


async def followup_for_timeout(
    meeting_id: str, item_id: str, question: str, asked_by: str, expert: str
) -> None:
    """Escalation timeout: "Follow-up: <question>" issue saved on the action item. Never raises."""
    try:
        async with _lock(meeting_id):
            meeting = await db.get_meeting(meeting_id) or {}
            items = db.with_item_ids(meeting.get("action_items"))
            if any(it["id"] == item_id and it.get("jira_key") for it in items):
                return
            title = meeting.get("title") or "a call"
            issue = await create_issue(
                f"Follow-up: {question}",
                f"Asked in {title} by {asked_by}; {expert} didn't answer within 2 min.",
                assignee_email=await _expert_email(expert),
            )
            await db.set_action_item_jira(meeting_id, item_id, issue["key"], issue["url"])
            log.info("jira follow-up %s for %s/%s", issue["key"], meeting_id, item_id)
    except Exception as e:
        log.warning("jira follow-up for %s/%s failed: %s", meeting_id, item_id, e)
