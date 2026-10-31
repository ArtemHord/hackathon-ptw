"""Demo profile (M10): "acme" (the stand-up demo, default) or "msp" (NovaStore INC-024 war room).

Runtime setting DEMO_PROFILE (web UI → Agent). The profile picks the seed directory, the docs
in the prompt, the meeting brief default, the simulate fixture and the incident data behind
the msp tools. Caches that depend on it are dropped by reset(), called by PUT /settings and
automatically when current() sees the value change.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from app import runtime

log = logging.getLogger(__name__)

PROFILES = ("acme", "msp")
DEFAULT = "acme"
SEED_ROOT = Path(__file__).resolve().parent.parent / "seed"
MSP_PROMPT_DOCS = ("client-novastore.md", "expert-directory.md")
MSP_SIM_REPLY = (
    "Check the CRM Bridge logs for auth_failure and token expired first, then reproduce on "
    "staging before touching production."
)
ACME_SIM_REPLY = "Thursday"
ACME_BRIEF = (
    "This week Artem finished the Slack escalation flow and the Postgres 16 tuning. "
    "He is working on the auth token cache. He cannot promise dates."
)

_last: str | None = None
_incidents: dict[str, dict[str, Any]] = {}  # seed dir -> parsed incidents.json


def current() -> str:
    """The active profile; an unknown value counts as the default."""
    global _last
    value = (runtime.get("DEMO_PROFILE") or "").strip().lower()
    value = value if value in PROFILES else DEFAULT
    if _last is not None and value != _last:
        log.info("demo profile %s -> %s: resetting caches", _last, value)
        _last = value
        reset()
    _last = value
    return value


def is_msp() -> bool:
    return current() == "msp"


def seed_dir(name: str | None = None) -> Path:
    return SEED_ROOT / "msp" if (name or current()) == "msp" else SEED_ROOT


def prompt_doc_names() -> list[str]:
    """Docs put straight into the prompt: acme every seed/*.md, msp the two small ones."""
    if is_msp():
        return [n for n in MSP_PROMPT_DOCS if (seed_dir() / n).exists()]
    return sorted(p.name for p in SEED_ROOT.glob("*.md"))


def default_brief() -> str | None:
    """msp: the INC-024 ticket (brief.md, never indexed); acme: None (no default)."""
    if not is_msp():
        return None
    try:
        return (seed_dir() / "brief.md").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def sim_brief() -> str:
    return default_brief() or ACME_BRIEF


def fixture_path() -> Path:
    if is_msp():
        return seed_dir() / "transcript_inc024.json"
    return SEED_ROOT / "demo_transcript.json"


def sim_title() -> str:
    return "INC-024 NovaStore SEV1 war room" if is_msp() else "Simulated stand-up"


def sim_default_reply() -> str:
    return MSP_SIM_REPLY if is_msp() else ACME_SIM_REPLY


def experts_seed_path(name: str | None = None) -> Path:
    return seed_dir(name) / "experts.json"


def incidents() -> dict[str, Any]:
    """Parsed incidents.json of the current profile ({} when absent: acme). Cached."""
    path = seed_dir() / "incidents.json"
    key = str(path)
    if key not in _incidents:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            if path.exists():
                log.warning("incidents.json unreadable: %s", e)
            data = {}
        _incidents[key] = data if isinstance(data, dict) else {}
    return _incidents[key]


_ID = re.compile(r"^([A-Za-z][A-Za-z0-9]*)-0*(\d+)$")


def norm_key(key: str) -> str:
    """ "INC-011" -> "INC-11" (jira.extract_keys drops leading zeros the same way)."""
    m = _ID.match((key or "").strip())
    return f"{m.group(1).upper()}-{int(m.group(2))}" if m else (key or "").strip().upper()


def incident_ids() -> set[str]:
    """Normalized incident IDs of the current profile (empty on acme)."""
    return {norm_key(str(i.get("id") or "")) for i in incidents().get("incidents") or []}


def owner_name() -> str:
    """Whose delegate the agent is: msp the Incident Lead from experts.json, else OWNER_NAME."""
    if is_msp():
        try:
            data = json.loads(experts_seed_path().read_text(encoding="utf-8"))["experts"]
            owner = next((e["name"] for e in data if e.get("is_owner")), None)
            if owner:
                return str(owner)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return runtime.get("OWNER_NAME")


def reset() -> None:
    """Drop every profile-dependent cache (lazy imports: those modules import us)."""
    from app import escalation, factcheck, orchestrator

    _incidents.clear()
    orchestrator._docs_cache.clear()  # noqa: SLF001
    orchestrator._experts_cache = None  # noqa: SLF001
    factcheck._filter_cache = None  # noqa: SLF001
    escalation._cache = None  # noqa: SLF001
