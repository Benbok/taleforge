"""Story threads: kept short, refreshed after a few actions, and handed to the scene maker and the writer."""

from types import SimpleNamespace

from app.core.universal.threads import REFRESH_EVERY, THREAD_LIMIT, clean, due, note_action, renewed, threads_of


def test_threads_are_trimmed_to_what_is_used_and_limited():
    raw = {
        "threads": [{"hook": f"Линия {i}", "who": "Дзихэй", "reveals": "след", "junk": "x"} for i in range(5)]
        + [{"hook": "  "}, "not a dict"]
    }
    result = clean(raw)
    assert len(result) == THREAD_LIMIT and set(result[0]) == {"hook", "who", "reveals"}


def test_nothing_usable_gives_no_threads():
    assert clean({"threads": [{"who": "никто"}]}) == [] and clean("text") == [] and clean(None) == []


def test_threads_are_due_when_missing_and_after_a_few_actions():
    setting = {}
    assert due(setting)
    setting = renewed(setting, [{"hook": "h", "who": "w", "reveals": "r"}])
    assert not due(setting)
    for _ in range(REFRESH_EVERY):
        setting = note_action(setting)
    assert due(setting) and renewed(setting, setting["threads"])["threads_age"] == 0


def test_threads_of_reads_the_secret_and_survives_a_missing_one():
    assert threads_of(None) == []
    assert threads_of(SimpleNamespace(setting={"threads": [{"hook": "h"}, "bad"]})) == [{"hook": "h"}]
