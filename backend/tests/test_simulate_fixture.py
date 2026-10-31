import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "seed" / "demo_transcript.json"


def test_demo_transcript_fixture():
    lines = json.loads(FIXTURE.read_text())
    assert lines
    assert {line["speaker"] for line in lines} <= {"Misha", "Julian", "Dima"}
    assert all(line["text"].strip() and isinstance(line["at_s"], (int, float)) for line in lines)
    times = [line["at_s"] for line in lines]
    assert times == sorted(times)
    keys = {(line["speaker"], line["at_s"]) for line in lines}
    assert len(keys) == len(lines)  # unique (speaker, ts_start) like the DB constraint
    crew = [line for line in lines if line["text"].startswith("Crew,")]
    assert len(crew) == 3
