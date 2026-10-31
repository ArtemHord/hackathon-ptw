import json
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent / "seed"


def test_history_json_is_clean():
    raw = (SEED / "history.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert {m["id"] for m in data["meetings"]} == {"m_hist_northwind", "m_hist_weekly"}
    low = (raw + (SEED / "customers.md").read_text(encoding="utf-8")).lower()
    for banned in ("postgres 17", "cache", "ttl"):
        assert banned not in low
