"""The "Atlas, ..." trigger (SPEC "Głos: ElevenLabs w rozmowie", steps 2-6).

utterance -> wake word in the first 6 words + 2-word question? -> delegate mode, not
speaking, not busy -> context (last 120 s, brief, seed docs, experts) -> LLM JSON {answer,
confidence, needs_expert, topic} -> filler if slow -> say() -> agent_said row + WS event.
"""

import asyncio
import json
import logging
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from app import (
    agent_voice,
    db,
    escalation,
    hub,
    jira,
    llm,
    profile,
    recall,
    runtime,
    speech,
    tools,
)

log = logging.getLogger(__name__)

FILLER_AFTER_S = 1.5
CONTEXT_WINDOW_S = 120.0
MIN_CONFIDENCE = 0.6
JIRA_LOOKUP_S = 2.5  # overall cap on the in-call ticket lookup (M7.4)
JIRA_MAX_KEYS = 2
# Tool calling (M8.1, setting AGENT_TOOLS): Responses API loop, at most TOOL_ROUNDS function
# rounds within TOOLS_CAP_S overall; any error/timeout -> the plain chat_json path.
TOOLS_CAP_S = 9.0
TOOL_ROUNDS = 2
# Tool cap + fallback together stay within ANSWER_BUDGET_S (fallback gets what is left,
# at least FALLBACK_MIN_S); a fallback timeout ends in the silent-failure path of _answer.
ANSWER_BUDGET_S = 14.0
FALLBACK_MIN_S = 3.0
MAX_SOURCE_LINKS = 2
MAX_SOURCE_REFS = 3  # M10: tool citations ("INC-011 14:19 Ola: ...") posted to the chat
CHAT_MAX_CHARS = 500  # Recall chat message cap
SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

# Wake word (M6.3): AGENT_NAME ("Atlas") as a whole word within the first WAKE_MAX_WORDS
# words (Recall merges sentences: "blah. Atlas, what..."), then at least 2 words of question.
WAKE_MAX_WORDS = 6
MIN_QUESTION_WORDS = 2
# HACK: ASR spellings of "Atlas" heard in tests; extras for other names go here.
_ALIAS_EXTRA = {"atlas": ("atlass", "atlis")}
_SEGMENT_START_ALIAS = {"atlas": ("at last",)}  # too common mid-sentence: only as first words
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.IGNORECASE)
_SHORT = "question shorter than"
# "Armed" wake word (M6.6): "Okay Atlas." alone arms (meeting, speaker) for ARMED_S; that
# speaker's next utterance with >= MIN_QUESTION_WORDS words is the question.
ARMED_S = 6.0
_armed: dict[tuple[str, str], float] = {}  # (meeting_id, speaker) -> monotonic deadline
# Partial question (M6.3b): Deepgram splits "Atlas, what did" | "Artem finish this week?".
# A question under PARTIAL_MAX_WORDS words without "?" waits PARTIAL_WAIT_S for the same
# speaker's next utterance, then is merged with it, or answered as is on timeout.
PARTIAL_MAX_WORDS = 4
PARTIAL_WAIT_S = 2.5
# (meeting_id, speaker) -> (partial question, its utterance, timeout task)
_pending: dict[tuple[str, str], tuple[str, dict[str, Any], asyncio.Task]] = {}


def _now() -> float:
    return time.monotonic()


def wake_aliases(name: str | None = None) -> tuple[str, ...]:
    """Every alias, the one place they are built: name, hey/okay/ok name, ASR spellings."""
    n = (name or runtime.get("AGENT_NAME")).strip().lower()
    return (f"hey {n}", f"okay {n}", f"ok {n}", n, *_ALIAS_EXTRA.get(n, ()))


@lru_cache
def _wake_res(name: str) -> tuple[re.Pattern[str], re.Pattern[str] | None]:
    def alt(aliases) -> str:
        parts = sorted(aliases, key=len, reverse=True)  # "hey atlas" wins over "atlas"
        return "|".join(r"[\s,]+".join(map(re.escape, a.split())) for a in parts)

    anywhere = re.compile(rf"(?<![\w'])(?:{alt(wake_aliases(name))})(?![\w'])", re.IGNORECASE)
    start_only = _SEGMENT_START_ALIAS.get(name.strip().lower())
    start = (
        re.compile(rf"^[\W_]*(?:{alt(start_only)})(?![\w'])", re.IGNORECASE) if start_only else None
    )
    return anywhere, start


ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"type": "number"},
        "needs_expert": {"type": "boolean"},
        "topic": {"type": "string"},
    },
    "required": ["answer", "confidence", "needs_expert", "topic"],
    "additionalProperties": False,
}

# Owner and agent names come from runtime settings (web UI, env fallback).
SYSTEM_PROMPT = """You are {agent}, {owner}'s delegate in this call.
People in the call address you as "{agent}". Your words are spoken aloud in the call.

Rules:
- The question comes from noisy live speech recognition: interpret it charitably using the \
brief and the documents ("what the tartan finish" = "what did {owner} finish"). If it is \
still unclear what was asked, reply with ONE short clarifying question.
- Answer ONLY from the context below: the owner's brief, the company documents and the \
recent transcript. Never guess or invent facts.
- At most 2 short spoken sentences, in English. No markdown, no lists.
- NEVER make commitments, promises, estimates or deadlines on behalf of the owner. For any \
question asking you to commit, agree, promise or give a date for the owner, set \
needs_expert=true and topic="owner".
- If the context does not contain the answer, set needs_expert=true and topic to the best \
matching expert topic from the list below (or "owner" if none fits).
- confidence: 0-1, how sure you are the answer is fully supported by the context.
- topic: "" when needs_expert is false.
- If a "## Jira" section is in the user message, answer the ticket question from it: \
status, assignee and due date, briefly. If it says a ticket was not found, say so; that \
alone is not a reason to set needs_expert.

## Owner's brief
{brief}

## Experts (name: topics)
{experts}

## Company documents
{docs}
"""

# Appended to the system prompt on the tool path only (the chat_json fallback has no tools).
TOOLS_PROMPT = """
## Tools
- web_search: ONLY for public, external facts: technology, software versions, news, \
standards, public companies. NEVER search for anything internal to the company or the \
owner (plans, dates, deadlines, migrations, decisions, people, projects, roadmaps): if the \
context does not answer an internal question, set needs_expert=true as above, no search.
- search_knowledge: the company knowledge base and facts from past meetings. Use it for an \
internal question the documents above do not answer. Call it at most ONCE per question; \
if it finds nothing relevant, set needs_expert=true right away.
- create_doc: ONLY when someone explicitly asks you to create or write a document. Then \
answer "I created the doc <title>." If it reports that the title exists, say so; you never \
edit existing documents.
- Facts returned by these tools count as context you may answer from.
- If search_knowledge returns an expert's earlier answer to the question being asked, \
answer from it and attribute it ("Dima said Thursday."): quoting what an expert already \
said is not a commitment, so set needs_expert=false. If the expert answered a different \
question, say what they were asked and answered instead of applying it to this question.
- Never put URLs, links, source names in brackets or markdown in the answer: it is spoken. \
Sources are posted to the meeting chat separately.
"""

# M10, profile msp: appended to the system prompt on both paths (tools and chat_json).
MSP_PROMPT = """
## Incident response rules (MSP war room)
- This is a live incident call. The owner's brief is the CURRENT incident ticket.
- Past incidents are evidence, not a diagnosis of the current incident. State the current \
incident's cause only as a hypothesis to verify, until someone in this call confirms it in \
the recent transcript. Never say the current cause is confirmed or certain.
- When you answer from a past incident, always name the incident ID and the time of the \
quote you rely on, e.g. "In INC-011 at 14:19 Ola confirmed ...".
- Never give money, loss, revenue, cost or SLA figures that no source contains: say there \
is no data on that.
- Never offer or claim to disable plugins, rotate or change tokens, deploy or change \
production yourself: an authorized engineer does that after the Incident Lead approves.
- Do not mix incidents: when asked whether a similar-looking incident had the same cause, \
compare it with the past incident that matches ALL reported symptoms and name both IDs: \
"No: INC-A was <its cause> with <its symptoms>, while INC-B, which matched all symptoms, was \
<its cause>." Never compare only with the current incident.
- When someone asks you to ask or contact a named person, set needs_expert=true and topic \
to that person's name.
- "There is no data on that", "that is not confirmed yet" or "no, I can't do that" are \
complete answers: needs_expert=false with high confidence. This overrides the rule to set \
needs_expert when the context lacks the answer.
"""

# M10, profile msp: the tool section instead of TOOLS_PROMPT (no web_search, no KB search).
MSP_TOOLS_PROMPT = """
## Tools
- find_similar_incidents: whenever someone asks about similar, earlier or past incidents, or \
what happened before. Pass the symptom tags reported in this call and in the brief. Answer \
from the best full match; mention a partial match only to say why it differs.
- get_incident: details and timed quotes of one incident named by its ID (e.g. INC-010).
- get_runbook: safe checks and steps, the runbook owner and its safety rule. ALWAYS call it \
for questions about what to check, mitigation, what is allowed, or whether you or anyone \
may disable, change or deploy something; base the answer on its safety rule.
- find_expert: who knows a topic, which incidents they resolved and whether they can be \
reached. Use it for "who should help with X"; name the person and how to reach them (the \
contact, e.g. "on Slack as ola-integrations").
- create_doc: ONLY when someone explicitly asks you to create a document.
- Questions about past incidents, runbooks, permissions or people need a tool call first; \
only the current incident's status (brief, transcript) or a missing figure needs none.
- Tool results count as context you may answer from. Name the incident ID and the quote \
time from the tool's citations. One tool round is usually enough; never call the same tool \
twice for one question.
- Never put URLs, links or markdown in the answer: it is spoken. Citations are posted to \
the meeting chat separately.
"""

_docs_cache: dict[str, str] = {}  # profile -> prompt docs
_experts_cache: str | None = None
_busy: set[str] = set()  # meeting_ids with an answer in progress


async def on_needs_expert(
    meeting_id: str, question: str, topic: str, asked_by: str
) -> str | dict[str, Any] | None:
    """Escalation hook (M3.3): escalation.start. Returns None, an expert name, or
    {"expert": name, "escalation_id": id}."""
    return await escalation.start(meeting_id, question, topic, asked_by)


def match_trigger(text: str) -> tuple[str | None, str]:
    """(question, reason). Question is the text after the wake word, or None + why not."""
    text = (text or "").replace("\u2019", "'")
    anywhere, start = _wake_res(runtime.get("AGENT_NAME").strip().lower())
    m = start.match(text) if start else None
    if m is None:
        m = anywhere.search(text)
        if m is None:
            return None, "no wake word"
        before = len(_WORD.findall(text[: m.start()]))
        if before >= WAKE_MAX_WORDS:
            return None, f"wake word is word {before + 1}, after the first {WAKE_MAX_WORDS}"
    question = re.sub(r"^[\W_]+", "", text[m.end() :]).strip()
    if len(_WORD.findall(question)) < MIN_QUESTION_WORDS:
        return None, f"{_SHORT} {MIN_QUESTION_WORDS} words: {question!r}"
    return question, "trigger"


def parse_trigger(text: str) -> str | None:
    """The question after the wake word, or None (no wake word / too short). Pure."""
    return match_trigger(text)[0]


def seed_docs() -> str:
    """HACK: the profile's prompt docs straight into the prompt (acme: all seed/*.md, msp:
    client + expert directory). Read once per profile."""
    name = profile.current()
    if name not in _docs_cache:
        base = profile.seed_dir()
        parts = [
            f"### {n}\n{(base / n).read_text(encoding='utf-8').strip()}"
            for n in profile.prompt_doc_names()
        ]
        _docs_cache[name] = "\n\n".join(parts)
    return _docs_cache[name]


async def experts_text() -> str:
    """Expert list for the prompt, from escalation.load_experts() (DB when configured, seed
    file otherwise). Cached; experts CRUD (settings_api) resets _experts_cache."""
    global _experts_cache
    profile.current()  # drops a cache of the previous profile
    if _experts_cache is None:
        experts = await escalation.load_experts()
        lines = [f"- {e.name}: {', '.join(e.topics or [])}" for e in experts]
        _experts_cache = "\n".join(lines) or "(none)"
    return _experts_cache


def build_messages(
    brief: str,
    recent: list[dict[str, Any]],
    speaker: str,
    question: str,
    experts: str = "(none)",
    jira_issues: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    system = SYSTEM_PROMPT.format(
        agent=runtime.get("AGENT_NAME"),
        owner=profile.owner_name(),
        brief=brief.strip() or "(no brief)",
        experts=experts,
        docs=seed_docs(),
    )
    if profile.is_msp():
        system += MSP_PROMPT
    transcript = "\n".join(f"{u['speaker']}: {u['text']}" for u in recent) or "(empty)"
    user = f"Recent transcript (last 2 minutes):\n{transcript}\n\n{speaker} asks you: {question}"
    if jira_issues:
        user += "\n\n## Jira\n" + "\n\n".join(jira_section(i) for i in jira_issues)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def jira_section(issue: dict[str, Any]) -> str:
    """One ticket for the prompt; {"key", "not_found": True} for a missing one."""
    if issue.get("not_found"):
        return f"{issue['key']}: not found in Jira."
    lines = [
        f"{issue['key']}: {issue.get('summary') or '(no summary)'}",
        f"Status: {issue.get('status') or 'unknown'}",
        f"Assignee: {issue.get('assignee') or 'unassigned'}",
        f"Due: {issue.get('due') or 'no due date'}",
    ]
    if issue.get("description"):
        lines.append(f"Description: {issue['description']}")
    return "\n".join(lines)


async def jira_context(question: str) -> list[dict[str, Any]]:
    """Tickets named in the question (max JIRA_MAX_KEYS, fetched concurrently, JIRA_LOOKUP_S
    overall). [] when Jira isn't configured, no key is found or the lookup fails. Never raises."""
    if not jira.configured():
        return []
    keys = jira.extract_keys(question, jira.project_key())
    incident_ids = profile.incident_ids()  # msp: INC-011 is an incident, not a Jira ticket
    keys = [k for k in keys if profile.norm_key(k) not in incident_ids][:JIRA_MAX_KEYS]
    if not keys:
        return []
    try:
        found = await asyncio.wait_for(
            asyncio.gather(*(jira.get_issue(k) for k in keys)), JIRA_LOOKUP_S
        )
    except Exception as e:
        log.warning("jira lookup %s failed, answering without it: %r", keys, e)
        return []
    log.info("jira lookup %s: %d found", keys, sum(1 for i in found if i))
    return [i or {"key": k, "not_found": True} for k, i in zip(keys, found, strict=True)]


_MD_CITE = re.compile(r"\s*\(\[[^\]]*\]\([^)]*\)\)")  # " ([python.org](https://...))"
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"\s*\(?https?://[^\s)]+\)?")


def spoken(text: str) -> str:
    """Strip what must not be spoken: markdown links/citations, bare URLs, emphasis."""
    text = _MD_CITE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        confidence = min(1.0, max(0.0, float(raw.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "answer": spoken(str(raw.get("answer") or "")),
        "confidence": confidence,
        "needs_expert": bool(raw.get("needs_expert")),
        "topic": str(raw.get("topic") or "").strip(),
    }


def _ms(a: float, b: float) -> int:
    return int((b - a) * 1000)


async def _safe(coro, default):
    try:
        return await coro
    except Exception as e:
        log.warning("orchestrator context fetch failed: %s", e)
        return default


async def handle(meeting_id: str, utterance: dict[str, Any]) -> None:
    """Entry point from the transcript webhook task. Never raises."""
    text = str(utterance.get("text") or "")
    log.info("utterance %s %s: %s", meeting_id, utterance.get("speaker"), text[:80])
    key = (meeting_id, str(utterance.get("speaker") or ""))
    question, reason = match_trigger(text)
    pending = _pending.pop(key, None)
    if pending is not None:
        partial, first, timer = pending
        timer.cancel()
        if question is None:  # the rest of the held question: merge and answer now
            merged = f"{partial} {_strip_lead(text)}".strip()
            log.info("partial merged in %s: %r", meeting_id, merged)
            await ask(meeting_id, first, merged)
            return
        # a new full trigger from the same speaker replaces the held partial
    if question is None and reason.startswith(_SHORT):
        _armed[key] = _now() + ARMED_S
        log.info("armed %s %s for %.0fs: %s", meeting_id, key[1], ARMED_S, reason)
        return
    if question is None:
        question = _armed_question(key, text)
        if question is None:
            log.info("no trigger in %s: %s", meeting_id, reason)
            return
        log.info("armed → question in %s: %r", meeting_id, question)
    else:
        _armed.pop(key, None)
        log.info("trigger in %s: %r", meeting_id, question)
    if _is_partial(question):
        timer = asyncio.create_task(_answer_partial_later(key, utterance, question))
        _pending[key] = (question, utterance, timer)
        log.info("partial → waiting %.1fs in %s: %r", PARTIAL_WAIT_S, meeting_id, question)
        return
    await ask(meeting_id, utterance, question)


def _strip_lead(text: str) -> str:
    return re.sub(r"^[\W_]+", "", text).strip()


def _is_partial(question: str) -> bool:
    q = question.rstrip()
    return len(_WORD.findall(q)) < PARTIAL_MAX_WORDS and not q.endswith("?")


async def _answer_partial_later(
    key: tuple[str, str], utterance: dict[str, Any], question: str
) -> None:
    """Never stay silent: no follow-up within PARTIAL_WAIT_S -> answer the partial as is."""
    await asyncio.sleep(PARTIAL_WAIT_S)
    entry = _pending.get(key)
    if entry is None or entry[2] is not asyncio.current_task():
        return
    _pending.pop(key, None)
    log.info("partial timeout in %s, answering: %r", key[0], question)
    await ask(key[0], utterance, question)


def _armed_question(key: tuple[str, str], text: str) -> str | None:
    """The whole utterance as the question if this speaker is armed and it has 2+ words.
    Disarms on use or expiry; a too-short utterance keeps the window open."""
    deadline = _armed.get(key)
    if deadline is None:
        return None
    if _now() > deadline:
        _armed.pop(key, None)
        log.info("armed expired %s %s", *key)
        return None
    question = _strip_lead(text)
    if len(_WORD.findall(question)) < MIN_QUESTION_WORDS:
        return None
    _armed.pop(key, None)
    return question


def is_busy(meeting_id: str) -> bool:
    """An answer is in progress or the agent is speaking (POST /meetings/{id}/ask -> 409)."""
    return meeting_id in _busy or agent_voice.is_speaking(meeting_id)


async def manual_question(meeting_id: str, text: str | None) -> tuple[dict[str, Any], str] | None:
    """(utterance, question) for a button trigger (POST /meetings/{id}/ask, /debug/ask): the
    given text, or the latest human utterance. None if there is nothing to answer."""
    from app.webhooks_recall import is_bot_speaker  # lazy: webhooks_recall -> orchestrator

    last = [
        u
        for u in await db.get_last_utterances(meeting_id, 10)
        if not is_bot_speaker(str(u.get("speaker") or ""))
    ]
    latest = last[-1] if last else None
    text = (text or "").strip()
    if not text:
        if latest is None:
            return None
        text = str(latest.get("text") or "").strip()
    question = parse_trigger(text) or text
    utterance = {
        "id": latest.get("id") if latest else None,
        "speaker": (latest or {}).get("speaker") or "Someone",
        "text": text,
        "ts": int(float((latest or {}).get("ts_start") or 0.0)),
    }
    return utterance, question


async def ask(meeting_id: str, utterance: dict[str, Any], question: str) -> bool:
    """Answer flow without the wake-word check (also POST /debug/ask). Keeps the speaking,
    busy and delegate-mode guards. False if dropped by a guard or failed. Never raises."""
    try:
        if agent_voice.is_speaking(meeting_id):
            log.info("trigger ignored (agent speaking) in %s", meeting_id)
            return False
        if meeting_id in _busy:
            log.info("trigger dropped (answer in progress) in %s: %r", meeting_id, question)
            return False
        _busy.add(meeting_id)
        try:
            return await _answer(meeting_id, utterance, question)
        finally:
            _busy.discard(meeting_id)
    except Exception:
        log.exception("orchestrator failed for meeting %s", meeting_id)
        return False


def _new_meta() -> dict[str, Any]:
    # citations/sources: web_search URLs; refs: "citations" of function results (M10)
    return {"path": "chat", "tools": [], "rounds": 0, "citations": [], "sources": [], "refs": []}


def _refs(output: str) -> list[str]:
    """The "citations" list of one function result (JSON string), [] otherwise."""
    try:
        data = json.loads(output or "")
    except ValueError:
        return []
    cites = data.get("citations") if isinstance(data, dict) else None
    if not isinstance(cites, list):
        return []
    return [str(c).strip() for c in cites if str(c).strip()]


async def _tool_loop(messages: list[dict[str, str]], meta: dict[str, Any]) -> dict[str, Any]:
    """Responses API: web_search (server side) + function tools, then the ANSWER_SCHEMA JSON.
    After TOOL_ROUNDS function rounds the last request forbids tools (tool_choice none)."""
    items: list[dict[str, Any]] = [dict(m) for m in messages]
    items[0]["content"] += MSP_TOOLS_PROMPT if profile.is_msp() else TOOLS_PROMPT
    defs = tools.definitions()
    prev: str | None = None
    for rnd in range(TOOL_ROUNDS + 1):
        last = rnd == TOOL_ROUNDS
        r = await llm.respond(
            items,
            tools=defs,
            schema_name="agent_answer",
            schema=ANSWER_SCHEMA,
            previous_response_id=prev,
            tool_choice="none" if last else None,
        )
        meta["tools"].extend(["web_search"] * r["web_search"])
        meta["citations"].extend(r["citations"])
        meta["sources"].extend({"url": u} for u in r.get("sources") or [])
        if not r["function_calls"]:
            return llm.parse_json_object(r["text"])
        if last:
            raise llm.LLMError("tool rounds exhausted")
        meta["rounds"] += 1
        outputs: list[dict[str, Any]] = []
        for call in r["function_calls"]:
            meta["tools"].append(call["name"])
            out = await tools.execute(call["name"], call["arguments"])
            log.info("agent tool %s(%s) -> %s", call["name"], call["arguments"][:120], out[:160])
            meta["refs"].extend(_refs(out))
            outputs.append(
                {"type": "function_call_output", "call_id": call["call_id"], "output": out}
            )
        items, prev = outputs, r["id"]
    raise llm.LLMError("unreachable")


async def _think(meeting_id: str, messages: list[dict[str, str]]) -> tuple[dict[str, Any], dict]:
    """(raw answer JSON, meta). Tool path when AGENT_TOOLS, else / on any failure chat_json."""
    meta = _new_meta()
    t0 = time.monotonic()
    if runtime.get_bool("AGENT_TOOLS"):
        try:
            raw = await asyncio.wait_for(_tool_loop(messages, meta), TOOLS_CAP_S)
            meta["path"] = "tools"
            return raw, meta
        except Exception as e:  # TimeoutError included
            log.warning("agent tools failed in %s, falling back to chat_json: %r", meeting_id, e)
            meta = {**_new_meta(), "path": "fallback", "tools": meta["tools"]}
            budget = max(FALLBACK_MIN_S, ANSWER_BUDGET_S - (time.monotonic() - t0))
            fallback = llm.chat_json(messages, "agent_answer", ANSWER_SCHEMA)
            return await asyncio.wait_for(fallback, budget), meta
    return await llm.chat_json(messages, "agent_answer", ANSWER_SCHEMA), meta


def source_links(citations: list[dict[str, str]], limit: int = MAX_SOURCE_LINKS) -> list[str]:
    """Up to `limit` distinct URLs (OpenAI's utm_source tag dropped)."""
    out: list[str] = []
    for c in citations:
        url = re.sub(r"[?&]utm_source=openai$", "", str(c.get("url") or "").strip())
        if url.startswith(("http://", "https://")) and url not in out:
            out.append(url)
        if len(out) >= limit:
            break
    return out


def source_refs(refs: list[str], limit: int = MAX_SOURCE_REFS) -> list[str]:
    """Up to `limit` distinct tool citations, each kept short for the chat."""
    out: list[str] = []
    for r in refs:
        r = re.sub(r"\s+", " ", str(r)).strip()
        r = r if len(r) <= 160 else r[:157].rstrip() + '..."'
        if r and r not in out:
            out.append(r)
        if len(out) >= limit:
            break
    return out


def sources_text(links: list[str], refs: list[str]) -> str:
    """ "Sources: <url> <url>" (web, as before M10), tool citations joined by " | "; "" if
    none. Capped at the Recall chat limit."""
    if not links and not refs:
        return ""
    text = "Sources: " + (" | ".join([*links, *refs]) if refs else " ".join(links))
    return text if len(text) <= CHAT_MAX_CHARS else text[: CHAT_MAX_CHARS - 3].rstrip() + "..."


def is_escalated(result: dict[str, Any]) -> bool:
    """The normalized answer goes to an expert instead of being spoken."""
    return bool(
        result["needs_expert"] or result["confidence"] < MIN_CONFIDENCE or not result["answer"]
    )


async def answer_question(
    question: str,
    *,
    meeting_id: str = "offline",
    brief: str = "",
    transcript: list[dict[str, Any]] | None = None,
    speaker: str = "Someone",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(normalized answer, meta) through the same prompt + think path as a call, without
    speaking, escalating or touching the meeting (scripts/eval_msp.py). Raises on LLM failure."""
    experts, issues = await asyncio.gather(
        _safe(experts_text(), "(none)"), _safe(jira_context(question), [])
    )
    messages = build_messages(brief, transcript or [], speaker, question, experts, issues)
    raw, meta = await _think(meeting_id, messages)
    return _normalize(raw), meta


_bg: set[asyncio.Task] = set()


async def _post_sources(meeting_id: str, text: str) -> None:
    """Best effort: the sources line (web URLs or tool citations) to the meeting chat."""
    try:
        meeting = await db.get_meeting(meeting_id) or {}
        ok = await recall.send_chat_message(meeting.get("recall_bot_id"), text)
        log.info("agent sources to chat in %s: %s (posted=%s)", meeting_id, text, ok)
    except Exception as e:
        log.warning("agent sources post failed in %s: %r", meeting_id, e)


async def _orb(coro) -> None:
    """Orb visuals are best effort: bounded, never raises, never blocks the voice path."""
    try:
        await asyncio.wait_for(coro, 0.3)
    except Exception as e:
        log.info("orb signal failed: %s", e.__class__.__name__)


async def _answer(meeting_id: str, utterance: dict[str, Any], question: str) -> bool:
    t0 = time.monotonic()
    if await db.get_meeting_mode(meeting_id) != "delegate":
        return False  # notetaker: listen only
    await _orb(agent_voice.send_state(meeting_id, "thinking"))
    asked_by = str(utterance.get("speaker") or "Someone")
    call_ts = float(utterance.get("ts") or 0.0)

    context = asyncio.gather(
        _safe(db.get_brief(meeting_id), ""),
        _safe(db.get_recent_utterances(meeting_id, call_ts - CONTEXT_WINDOW_S), []),
        _safe(experts_text(), "(none)"),
        _safe(jira_context(question), []),  # [] unless Jira is set up and a key was said
    )
    filler = False
    done, _ = await asyncio.wait({context}, timeout=FILLER_AFTER_S)
    if not done:  # slow context (a Jira lookup): the filler covers it
        filler = True
        await speech.say_filler(meeting_id)
    brief, recent, experts, issues = await context
    messages = build_messages(brief, recent, asked_by, question, experts, issues)
    task = asyncio.create_task(_think(meeting_id, messages))

    if not filler:
        wait_s = max(0.0, FILLER_AFTER_S - (time.monotonic() - t0))
        done, _ = await asyncio.wait({task}, timeout=wait_s)
        if not done:
            filler = True
            await speech.say_filler(meeting_id)
    try:
        raw, meta = await task
        result = _normalize(raw)
    except Exception as e:
        log.warning("agent LLM failed in %s, staying silent: %s", meeting_id, e)
        await _orb(agent_voice.send_state(meeting_id, "idle"))
        return False
    t_llm = time.monotonic()

    escalation_id: str | None = None
    escalated = is_escalated(result)
    if escalated:
        expert: str | None = None
        try:
            hooked = await on_needs_expert(
                meeting_id, question, result["topic"] or "owner", asked_by
            )
        except Exception:
            log.exception("on_needs_expert failed in %s", meeting_id)
            hooked = None
        if isinstance(hooked, dict):
            expert = hooked.get("expert") or None
            escalation_id = hooked.get("escalation_id") or None
        elif isinstance(hooked, str) and hooked.strip():
            expert = hooked.strip()
        text = (
            f"I don't know, asking {expert} now."
            if expert
            else ("I don't know yet, I'll ask the team.")
        )
    else:
        text = result["answer"]

    delivered = await speech.say(meeting_id, text)
    t_played = time.monotonic()
    # cited URLs first, then the pages web_search looked at
    links = [] if escalated else source_links(meta["citations"] + meta["sources"])
    refs = [] if escalated else source_refs(meta.get("refs") or [])
    chat_line = sources_text(links, refs)
    if chat_line and delivered:
        bg = asyncio.create_task(_post_sources(meeting_id, chat_line))
        _bg.add(bg)
        bg.add_done_callback(_bg.discard)
    log.info(
        "agent latency %s: trigger->llm %dms, llm->tts+push %dms, total %dms (filler=%s, "
        "delivered=%s, conf=%.2f, needs_expert=%s, topic=%r, path=%s, tools=%s, rounds=%d)",
        meeting_id,
        _ms(t0, t_llm),
        _ms(t_llm, t_played),
        _ms(t0, t_played),
        filler,
        delivered,
        result["confidence"],
        result["needs_expert"],
        result["topic"],
        meta["path"],
        ",".join(meta["tools"]) or "-",
        meta["rounds"],
    )

    ts = int(round(call_ts + (t_played - t0)))
    row = await db.insert_agent_said(meeting_id, text, float(ts), escalation_id)
    await hub.publish(
        meeting_id,
        "agent_said",
        {"id": row["id"], "text": text, "ts": ts, "in_reply_to": escalation_id},
    )
    return True
