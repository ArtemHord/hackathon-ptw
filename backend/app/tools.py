"""Atlas in-call tools (M8.1): Responses API tool definitions + executors.

Built-in `web_search` runs on OpenAI's side. Function tools run here:
- search_knowledge(query): KB chunks + past-meeting facts (rag.search), top 4 with titles.
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

SEARCH_K = 4
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


async def search_knowledge(query: str) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"error": "empty query"}
    items = await rag.search(query, k=SEARCH_K, kinds=("kb", "facts"))
    results = []
    for it in items[:SEARCH_K]:
        title = it.get("doc_title") if it["kind"] == "kb" else "Past meeting fact"
        results.append({"title": title or "Untitled", "text": it["text"]})
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
