"""Live fact-check (SPEC "Fact-check i aktualizacja bazy na zywo", pipeline 1-6).

check() runs for every utterance (both modes): free regex filter -> one strict-JSON LLM
call (extract + judge) against KB/facts -> store -> `fact_check` WS event -> Heads-up in
the Meet chat when contradicted with high confidence. A confident "change" also creates a
kb_update_proposals row (approved in the app).
"""

import logging
import re
import time
from typing import Any

from app import db, hub, llm, orchestrator, rag, recall

log = logging.getLogger(__name__)

MIN_POST_CONFIDENCE = 0.8
MIN_PROPOSAL_CONFIDENCE = 0.7
POST_COOLDOWN_S = 60.0

_UNITS = (
    r"rps|qps|%|percent|ms|milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|"
    r"requests?|per\s+(?:second|minute|hour|day|month)|\$|usd|eur|dollars?|euros?|"
    r"kb|mb|gb|tb|"
    r"jan(?:uary)?|feb(?:ruary)?|march|apr(?:il)?|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next\s+week"
)
_BASE_FILTER = rf"\d|\b(?:{_UNITS})\b|[%$€]"
_filter_cache: re.Pattern[str] | None = None

_last_post: dict[str, float] = {}  # meeting_id -> monotonic time of the last Heads-up


def _team_names() -> list[str]:
    """First column of the team.md table (Artem, Dima, ...)."""
    names: list[str] = []
    try:
        text = (orchestrator.SEED_DIR / "team.md").read_text()
    except OSError:
        return names
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] not in ("Name", "") and "---" not in cells[0]:
            names.append(cells[0])
    return names


def _filter() -> re.Pattern[str]:
    global _filter_cache
    if _filter_cache is None:
        names = "|".join(re.escape(n) for n in _team_names())
        pattern = _BASE_FILTER + (rf"|\b(?:{names})\b" if names else "")
        _filter_cache = re.compile(pattern, re.IGNORECASE)
    return _filter_cache


def worth_checking(text: str) -> bool:
    return bool(_filter().search(text or ""))


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim": {"type": ["string", "null"]},
        "verdict": {"type": "string", "enum": ["supported", "contradicted", "change", "unknown"]},
        "confidence": {"type": "number"},
        "source_title": {"type": ["string", "null"]},
        "correction": {"type": ["string", "null"]},
        "chat_message": {"type": ["string", "null"]},
        "old_text": {"type": ["string", "null"]},
        "new_text": {"type": ["string", "null"]},
    },
    "required": [
        "claim",
        "verdict",
        "confidence",
        "source_title",
        "correction",
        "chat_message",
        "old_text",
        "new_text",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You fact-check one sentence from a live meeting against company documents.
1. Extract the single checkable factual claim (a number, date, limit, owner, status). If the \
sentence has none, set claim=null, verdict="unknown", confidence=0.
2. Judge it ONLY against the documents below. Verdicts:
- "supported": the documents confirm the claim.
- "contradicted": the speaker states a CURRENT fact that conflicts with the documents.
- "change": the speaker announces a decision or a future change (e.g. "we will raise the limit \
to 200"). This is not an error, even if it differs from the documents.
- "unknown": the documents do not cover the claim.
Never guess. confidence is 0-1.
For "contradicted": source_title = the document title (e.g. "api.md"), correction = the correct \
value only (e.g. "50 rps"), chat_message = one short English line such as "Heads-up: api.md says \
the rate limit is 50 rps, not 100 (updated 12 Oct)". Include the update date only if the \
documents show one. Otherwise set source_title, correction and chat_message to null.
For "change": source_title = the document that would need updating, old_text = the EXACT line or \
sentence copied verbatim from that document which the change replaces, new_text = that same line \
rewritten with the new value (keep wording and format). If you cannot copy the exact old line, \
set old_text and new_text to null. For other verdicts set old_text and new_text to null.

## Documents
{docs}
"""

VERDICT_MAP = {
    "supported": "confirmed",
    "contradicted": "contradicted",
    "change": "unverified",
    "unknown": "unverified",
}


async def _context(text: str) -> str:
    try:
        items = await rag.search(text, k=6, kinds=("kb", "facts"))
    except Exception as e:
        log.warning("factcheck rag failed, using seed docs: %s", e)
        items = []
    if items:
        return "\n\n".join(f"### {i.get('doc_title') or i['kind']}\n{i['text']}" for i in items)
    return orchestrator.seed_docs()


def _confidence(raw: Any) -> float:
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0


async def _check(meeting_id: str, utterance: dict[str, Any]) -> None:
    text = str(utterance.get("text") or "").strip()
    if not text or orchestrator.parse_trigger(text) is not None or not worth_checking(text):
        return
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(docs=await _context(text))},
        {"role": "user", "content": f"{utterance.get('speaker') or 'Someone'}: {text}"},
    ]
    result = await llm.chat_json(messages, "fact_check", SCHEMA)
    claim = (result.get("claim") or "").strip()
    if not claim:
        return
    verdict = VERDICT_MAP.get(str(result.get("verdict")), "unverified")
    confidence = _confidence(result.get("confidence"))
    correction = result.get("correction") or None
    source = result.get("source_title") or None
    message = (result.get("chat_message") or "").strip()
    ts = int(utterance.get("ts") or 0)
    kb_chunk_id = None
    if source:
        try:
            kb_chunk_id = await db.kb_chunk_for_title(str(source))
        except Exception as e:
            log.warning("factcheck chunk lookup failed: %s", e)

    proposal_id = None
    if str(result.get("verdict")) == "change" and confidence >= MIN_PROPOSAL_CONFIDENCE and source:
        old_text = (result.get("old_text") or "").strip()
        new_text = (result.get("new_text") or "").strip()
        # HACK: short old_text (e.g. "50") would match anywhere
        if len(old_text) >= 10 and new_text and old_text != new_text:
            try:
                hit = await db.kb_chunk_with_text(str(source), old_text)
                if hit:
                    kb_chunk_id = hit["chunk_id"]
                    proposal_id = await db.insert_proposal(
                        meeting_id,
                        doc_id=hit["doc_id"],
                        chunk_id=hit["chunk_id"],
                        old_text=old_text,
                        new_text=new_text,
                        speaker=utterance.get("speaker"),
                        ts=float(ts),
                    )
                    short = new_text if len(new_text) <= 80 else new_text[:77] + "..."
                    message = f"Noted: {short}. I'll propose an update to {source}."
            except Exception as e:
                log.warning("factcheck proposal failed: %s", e)

    posted = False
    if (
        (verdict == "contradicted" and confidence >= MIN_POST_CONFIDENCE and message) or proposal_id
    ) and message:
        last = _last_post.get(meeting_id)
        if last is None or time.monotonic() - last >= POST_COOLDOWN_S:
            meeting = await db.get_meeting(meeting_id)
            bot_id = (meeting or {}).get("recall_bot_id")
            if await recall.send_chat_message(bot_id, message):
                posted = True
                _last_post[meeting_id] = time.monotonic()

    row = await db.insert_fact_check(
        meeting_id,
        utterance_id=utterance.get("id"),
        claim=claim,
        verdict=verdict,
        confidence=confidence,
        correction=correction,
        posted=posted,
        ts=float(ts),
        kb_chunk_id=kb_chunk_id,
        proposal_id=proposal_id,
    )
    await hub.publish(
        meeting_id,
        "fact_check",
        {
            "id": row["id"],
            "claim": claim,
            "verdict": verdict,
            "source": source,
            "correction": correction,
            "ts": ts,
            "proposal_id": proposal_id,
        },
    )


async def check(meeting_id: str, utterance: dict[str, Any]) -> None:
    """Never raises."""
    try:
        await _check(meeting_id, utterance)
    except Exception:
        log.exception("fact-check failed for meeting %s", meeting_id)
