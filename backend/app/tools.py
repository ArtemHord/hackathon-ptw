"""Atlas in-call tools (M8.1): Responses API tool definitions + executors.

Built-in `web_search` runs on OpenAI's side. Function tools run here:
- search_knowledge(query): past-meeting facts and KB chunks searched separately (top 3
  each, so long KB chunks cannot crowd out a short expert answer); a fact is
  "<speaker> (meeting <date>): <text>", an expert answer also carries its question.
- create_doc(title, markdown): a NEW KB doc only; an existing title is refused (edits go
  through KB proposals, the agent never modifies existing docs).
Executors never raise: errors come back to the model as {"error": "..."}.
"""

import asyncio
import json
import logging
from typing import Any

from app import db, rag

log = logging.getLogger(__name__)

FACTS_K = 3
KB_K = 3
MAX_TITLE = 120
MAX_DOC_CHARS = 20000
_create_lock = asyncio.Lock()  # check-then-write is atomic within our single instance

WEB_SEARCH: dict[str, Any] = {"type": "web_search", "search_context_size": "low"}

FUNCTIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_knowledge",
        "description": (
            "Search the company knowledge base and facts from past meetings. Use it for "
            "internal questions the documents in the prompt do not answer."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What to look up."}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "create_doc",
        "description": (
            "Create a NEW document in the company knowledge base. Only when someone in the "
            "call explicitly asks for a document to be created. Cannot edit existing docs."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short document title."},
                "markdown": {"type": "string", "description": "Document body in Markdown."},
            },
            "required": ["title", "markdown"],
            "additionalProperties": False,
        },
    },
]


def definitions() -> list[dict[str, Any]]:
    return [WEB_SEARCH, *FUNCTIONS]


def _day(meeting: Any) -> str:
    m = meeting if isinstance(meeting, dict) else {}  # a failed lookup is an exception
    when = m.get("started_at") or m.get("created_at")
    return when.date().isoformat() if hasattr(when, "date") else "unknown date"


def _fact_text(it: dict[str, Any], day: str) -> str:
    speaker = it.get("speaker") or "Someone"
    text = str(it["text"]).strip()
    q, sep, a = text.partition("\nA:")
    if sep and q.startswith("Q:"):  # an expert's Slack answer (escalation.py stores Q/A)
        return f'{speaker} (meeting {day}), asked "{q[2:].strip()}", answered: {a.strip()}'
    return f"{speaker} (meeting {day}): {text}"


async def search_knowledge(query: str) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"error": "empty query"}
    found_facts, found_kb = await asyncio.gather(
        rag.search(query, k=FACTS_K * 2, kinds=("facts",)),  # x2: postcall repeats facts
        rag.search(query, k=KB_K, kinds=("kb",)),
    )
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for it in found_facts:
        key = (str(it.get("speaker") or ""), str(it["text"]).strip().casefold())
        if it["kind"] == "facts" and key not in seen and len(facts) < FACTS_K:
            seen.add(key)
            facts.append(it)
    ids = sorted({str(f["meeting_id"]) for f in facts if f.get("meeting_id")})
    looked = await asyncio.gather(*(db.get_meeting(i) for i in ids), return_exceptions=True)
    meetings = dict(zip(ids, looked, strict=True))
    results = []
    for f in facts:
        day = _day(meetings.get(f.get("meeting_id")))
        results.append({"title": "Past meeting fact", "text": _fact_text(f, day)})
    for it in [it for it in found_kb if it["kind"] == "kb"][:KB_K]:
        results.append({"title": it.get("doc_title") or "Untitled", "text": it["text"]})
    return {"results": results} if results else {"results": [], "note": "nothing found"}


async def create_doc(title: str, markdown: str) -> dict[str, Any]:
    title = (title or "").strip()[:MAX_TITLE]
    markdown = (markdown or "").strip()[:MAX_DOC_CHARS]
    if not title or not markdown:
        return {"error": "title and markdown are required"}
    async with _create_lock:
        key = title.casefold()
        taken = [d for d in await db.list_kb_docs() if str(d["title"]).strip().casefold() == key]
        if taken:
            existing = taken[0]["title"]
            return {"error": f"a doc titled {existing!r} exists; edits go through KB proposals"}
        doc = await rag.upsert_doc(title, markdown)
    log.info("agent created KB doc %r (id=%s)", title, doc.get("id"))
    return {"created": True, "title": title, "version": doc.get("version", 1)}


_EXECUTORS = {"search_knowledge": search_knowledge, "create_doc": create_doc}
_ARGS = {"search_knowledge": ("query",), "create_doc": ("title", "markdown")}


async def execute(name: str, arguments: str) -> str:
    """Run one function call; the JSON string goes back as function_call_output."""
    fn = _EXECUTORS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool {name!r}"})
    try:
        args = json.loads(arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("arguments are not an object")
        out = await fn(**{k: str(v) for k, v in args.items() if k in _ARGS[name]})
    except Exception as e:
        log.warning("tool %s failed: %r", name, e)
        out = {"error": f"{name} failed: {e.__class__.__name__}"}
    return json.dumps(out, ensure_ascii=False, default=str)
