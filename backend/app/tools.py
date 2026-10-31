"""Atlas in-call tools (M8.1): Responses API tool definitions + executors.

Built-in `web_search` runs on OpenAI's side. Function tools run here:
- search_knowledge(query): past-meeting facts and KB chunks searched separately (top 3
  each, so long KB chunks cannot crowd out a short expert answer); a fact is
  "<speaker> (meeting <date>): <text>", an expert answer also carries its question.
- create_doc(title, markdown): a NEW KB doc only; an existing title is refused (edits go
  through KB proposals, the agent never modifies existing docs).
Profile msp (M10) swaps web_search + search_knowledge for incident tools over in-memory JSON
(seed/msp/incidents.json, runbook-*.md): find_similar_incidents (deterministic symptom
overlap), get_incident, get_runbook, find_expert. Every msp result carries "citations"
(short strings the orchestrator posts to the meeting chat).
Executors never raise: errors come back to the model as {"error": "..."}.
"""

import asyncio
import json
import logging
import re
from typing import Any

from app import db, escalation, profile, rag

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


CREATE_DOC = next(f for f in FUNCTIONS if f["name"] == "create_doc")
TOP_INCIDENTS = 3
MAX_QUOTES = 3
QUOTE_CHARS = 110
HISTORICAL_NOTE = "Historical evidence only; the current incident's cause is not confirmed."


def _fn(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


def symptom_tags() -> dict[str, str]:
    tags = profile.incidents().get("symptom_tags") or {}
    return {str(k): str(v) for k, v in tags.items()} if isinstance(tags, dict) else {}


def msp_functions() -> list[dict[str, Any]]:
    """Built from incidents.json at call time: the symptom enum is the file's tags."""
    tags = symptom_tags()
    listed = "; ".join(f"{k} = {v}" for k, v in tags.items())
    return [
        _fn(
            "find_similar_incidents",
            "Find past incidents with the same symptoms (deterministic symptom overlap). "
            f"Pass every symptom reported for the current incident, at least one. Tags: {listed}",
            {
                "symptoms": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(tags) or ["unknown"]},
                    "description": "Symptom tags of the current incident.",
                }
            },
        ),
        _fn(
            "get_incident",
            "Details of one past incident: cause, fix, who resolved it, timed quotes, lesson.",
            {"incident_id": {"type": "string", "description": "Incident ID, e.g. INC-011."}},
        ),
        _fn(
            "get_runbook",
            "The best matching runbook: safe steps, owner and safety rule.",
            {"query": {"type": "string", "description": "What the runbook should cover."}},
        ),
        _fn(
            "find_expert",
            "Who knows a topic: role, areas, incidents they resolved, whether they approve "
            "mitigations and whether they can be reached now.",
            {"topic": {"type": "string", "description": "Topic, system or person name."}},
        ),
        CREATE_DOC,
    ]


def definitions() -> list[dict[str, Any]]:
    if profile.is_msp():
        return msp_functions()
    return [WEB_SEARCH, *FUNCTIONS]


# --- msp incident tools (M10) -----------------------------------------------------------


def _incidents() -> list[dict[str, Any]]:
    return [i for i in profile.incidents().get("incidents") or [] if isinstance(i, dict)]


def _short(text: str, n: int = QUOTE_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[: n - 3].rstrip() + "..."


def _quote_cite(inc_id: str, q: dict[str, Any]) -> str:
    who = q.get("speaker") or "Someone"
    return f'{inc_id} {q.get("time") or "?"} {who}: "{_short(q.get("text"))}"'


_KEY_QUOTE = re.compile(r"\b(?:confirm\w*|cause)\b", re.IGNORECASE)


def _ranked_quotes(inc: dict[str, Any]) -> list[dict[str, Any]]:
    """Quotes stating a (confirmed) cause first, the rest in time order (stable sort)."""
    qs = [
        {k: q.get(k) for k in ("time", "speaker", "role", "text")}
        for q in inc.get("quotes") or []
        if isinstance(q, dict)
    ]
    return sorted(qs, key=lambda q: not _KEY_QUOTE.search(str(q.get("text") or "")))


def _quotes(inc: dict[str, Any], limit: int = MAX_QUOTES) -> list[dict[str, Any]]:
    """Up to `limit` key quotes, in time order."""
    picked = _ranked_quotes(inc)[:limit]
    return sorted(picked, key=lambda q: str(q.get("time") or ""))


def _cites(inc: dict[str, Any], limit: int = MAX_QUOTES) -> list[str]:
    return [_quote_cite(str(inc.get("id")), q) for q in _ranked_quotes(inc)[:limit]]


def _detail(inc: dict[str, Any], quotes: int = MAX_QUOTES) -> dict[str, Any]:
    return {
        "id": inc.get("id"),
        "date": inc.get("date"),
        "title": inc.get("title"),
        "symptoms": list(inc.get("symptoms") or []),
        "prices_correct": inc.get("prices_correct"),
        "root_cause": inc.get("root_cause"),
        "resolution": inc.get("resolution"),
        "resolved_by": list(inc.get("resolved_by") or []),
        "runbook": inc.get("runbook"),
        "quotes": _quotes(inc, quotes),
        "lesson": inc.get("lesson"),
    }


def _missing_reason(tag: str, inc: dict[str, Any]) -> str:
    if tag == "wrong_prices" and inc.get("prices_correct"):
        return "prices were correct"
    return f"no {tag.replace('_', ' ')}"


def _verdict(inc: dict[str, Any], missing: list[str], extra: list[str]) -> str:
    if not missing:
        return "matches all reported symptoms"
    why = [_missing_reason(t, inc) for t in missing]
    why += [f"it also had {t.replace('_', ' ')}" for t in extra]
    return "partial match: " + "; ".join(why)


async def find_similar_incidents(symptoms: Any) -> dict[str, Any]:
    tags = symptom_tags()
    asked = [str(s).strip() for s in (symptoms if isinstance(symptoms, list) else [symptoms])]
    asked = list(dict.fromkeys(s for s in asked if s))
    unknown = [s for s in asked if s not in tags]
    asked = [t for t in tags if t in asked]  # canonical (file) order: same input, same output
    if not asked:
        return {"error": "pass at least one known symptom tag", "known_tags": list(tags)}
    want = set(asked)
    scored = []
    for inc in _incidents():
        have = list(inc.get("symptoms") or [])
        matched = [t for t in asked if t in have]
        if not matched:
            continue
        missing = [t for t in asked if t not in have]
        extra = [t for t in have if t not in want]
        day = str(inc.get("date") or "")
        scored.append((not missing, len(matched), day, inc, matched, missing, extra))
    # full matches first, then overlap, then the most recent
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    results = []
    for _, _, _, inc, matched, missing, extra in scored[:TOP_INCIDENTS]:
        results.append(
            {
                **_detail(inc),
                "matched": matched,
                "missing": missing,
                "extra": extra,
                "verdict": _verdict(inc, missing, extra),
            }
        )
    out: dict[str, Any] = {"note": HISTORICAL_NOTE, "results": results}
    if unknown:
        out["ignored_tags"] = unknown
    cites: list[str] = []
    if results:
        top = results[0]
        cites = _cites(next(i for i in _incidents() if i.get("id") == top["id"]))
        if top.get("runbook"):
            cites = [*cites[: MAX_QUOTES - 1], f"{top['runbook']} (runbook of {top['id']})"]
    else:
        out["note"] = "No past incident shares these symptoms. " + HISTORICAL_NOTE
    out["citations"] = cites
    return out


async def get_incident(incident_id: str) -> dict[str, Any]:
    want = profile.norm_key(incident_id)
    for inc in _incidents():
        if profile.norm_key(str(inc.get("id") or "")) == want:
            detail = _detail(inc, quotes=len(inc.get("quotes") or []))
            cites = _cites(inc)
            return {**detail, "citations": cites or [str(inc["id"])]}
    known = [str(i.get("id")) for i in _incidents()]
    return {"error": f"unknown incident {incident_id!r}", "known_ids": known, "citations": []}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2}


def _parse_runbook(text: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in text.splitlines()]
    title = next((ln.lstrip("# ").strip() for ln in lines if ln.startswith("#")), "")
    rid = re.split(r"\s+[-–—]\s+", title, maxsplit=1)[0].strip() if title else ""
    owner_m = re.search(r"Owner:\s*([^|\n]+)", text)
    steps = [ln for ln in lines if re.match(r"^\d+[.)]\s", ln)]
    safety = next((ln for ln in lines if ln.lower().startswith("safety rule")), "")
    return {
        "id": rid,
        "title": title,
        "owner": owner_m.group(1).strip() if owner_m else None,
        "steps": steps,
        "safety_rule": safety,
    }


async def get_runbook(query: str) -> dict[str, Any]:
    """File based: the runbook-*.md in the profile's seed dir with the best word overlap."""
    files = sorted(profile.seed_dir().glob("runbook-*.md"))
    if not files:
        return {"error": "no runbooks available", "citations": []}
    q = _words(query)
    texts = {f: f.read_text(encoding="utf-8") for f in files}
    best = max(files, key=lambda f: (len(q & _words(texts[f])), -files.index(f)))
    rb = _parse_runbook(texts[best])
    rid = rb["id"] or best.stem.upper()
    n = len(rb["steps"])
    cite = f"{rid} steps 1-{n}" if n else rid
    if rb["owner"]:
        cite += f", owner {rb['owner']}"
    return {**rb, "id": rid, "citations": [cite]}


def _contact(handle: Any) -> str | None:
    """ "@ola-integrations (fictional)" -> "Slack ola-integrations" (speakable)."""
    m = re.search(r"@?([\w.-]+)", str(handle or ""))
    return f"Slack {m.group(1)}" if m else None


async def find_expert(topic: str) -> dict[str, Any]:
    experts = [e for e in profile.incidents().get("experts") or [] if isinstance(e, dict)]
    if not experts:
        return {"error": "no expert directory", "citations": []}
    q = _words(topic)
    q_l = (topic or "").lower()
    scored = []
    for i, e in enumerate(experts):
        name = str(e.get("name") or "")
        hay = " ".join([name, str(e.get("role") or ""), *map(str, e.get("areas") or [])])
        score = len(q & _words(hay))
        if name and re.search(rf"(?<!\w){re.escape(name.lower())}(?!\w)", q_l):
            score += 10
        score += sum(2 for a in e.get("areas") or [] if str(a).lower() in q_l)
        scored.append((score, -i, e))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    hits = [e for score, _, e in scored if score > 0][:3]
    try:
        known = await escalation.load_experts()
    except Exception as ex:
        log.warning("find_expert: experts load failed: %r", ex)
        known = []
    reach = {
        k.name.strip().casefold(): bool(k.email or k.telegram_chat_id or k.slack_user_id)
        for k in known
    }
    out_items = []
    for e in hits or [e for _, _, e in scored]:
        name = str(e.get("name") or "")
        out_items.append(
            {
                "name": name,
                "role": e.get("role"),
                "areas": list(e.get("areas") or []),
                "resolved": list(e.get("resolved") or []),
                "handle": e.get("handle"),
                "contact": _contact(e.get("handle")),
                "approves": bool(e.get("approves")),
                "reachable": reach.get(name.casefold(), False),
            }
        )
    out: dict[str, Any] = {"experts": out_items}
    if not hits:
        out["note"] = "No expert lists this topic; the Incident Lead decides who helps."
    cites = []
    for e in out_items[:2] if hits else []:
        done = f"resolved {', '.join(e['resolved'])}" if e["resolved"] else e["role"] or ""
        cites.append(f"expert-directory: {e['name']} ({done})")
    out["citations"] = cites
    return out


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


_EXECUTORS = {
    "search_knowledge": search_knowledge,
    "create_doc": create_doc,
    "find_similar_incidents": find_similar_incidents,
    "get_incident": get_incident,
    "get_runbook": get_runbook,
    "find_expert": find_expert,
}
_ARGS = {
    "search_knowledge": ("query",),
    "create_doc": ("title", "markdown"),
    "find_similar_incidents": ("symptoms",),
    "get_incident": ("incident_id",),
    "get_runbook": ("query",),
    "find_expert": ("topic",),
}
_LIST_ARGS = {"symptoms"}


async def execute(name: str, arguments: str) -> str:
    """Run one function call; the JSON string goes back as function_call_output."""
    fn = _EXECUTORS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool {name!r}"})
    try:
        args = json.loads(arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("arguments are not an object")
        out = await fn(
            **{
                k: (v if k in _LIST_ARGS and isinstance(v, list) else str(v))
                for k, v in args.items()
                if k in _ARGS[name]
            }
        )
    except Exception as e:
        log.warning("tool %s failed: %r", name, e)
        out = {"error": f"{name} failed: {e.__class__.__name__}"}
    return json.dumps(out, ensure_ascii=False, default=str)
