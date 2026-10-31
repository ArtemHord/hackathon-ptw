import json

import pytest

from app import escalation
from app.notifier.base import get_notifier


@pytest.fixture
def experts():
    return escalation._seed_experts()


@pytest.mark.parametrize(
    "topic,name",
    [
        ("infra", "Dima"),
        ("database migration", "Dima"),
        ("postgres", "Dima"),
        ("Postgres 17 upgrade", "Dima"),
        ("api", "Julian"),
        ("mobile", "Misha"),
        ("owner", "Artem"),
        ("", "Artem"),
        ("weather", "Artem"),
    ],
)
def test_match(experts, topic, name):
    assert escalation.match_expert(topic, experts).name == name


def test_seed_valid_and_owner(experts):
    assert json.loads(escalation.SEED_PATH.read_text())["_note"]
    assert [e.name for e in experts if e.is_owner] == ["Artem"]


def test_registry_empty_for_unknown():
    assert get_notifier("nope") is None
