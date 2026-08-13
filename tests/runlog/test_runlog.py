"""The run event log: envelope, the four rules, and the renderer."""

import json

from pd2bot.runlog import (
    SCHEMA_VERSION,
    NullRunLog,
    RunLog,
    latest_run,
    load,
    render,
    summarize,
)


class Clock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_log(tmp_path, clock=None, **kw):
    clock = clock or Clock()
    return RunLog(
        "countess",
        root=tmp_path,
        clock=clock,
        wall=lambda: 1786000000.0,
        **kw,
    ), clock


# -- the directory and header ------------------------------------------------


def test_a_run_gets_its_own_directory_with_a_header(tmp_path):
    log, _ = make_log(tmp_path, header={"seed": 0x4E52715F, "chicken": 35.0})
    log.event("run.start")
    header = json.loads((log.directory / "run.json").read_text(encoding="utf-8"))
    assert header["schema"] == SCHEMA_VERSION
    assert header["run"] == "countess"
    assert header["seed"] == 0x4E52715F
    assert header["chicken"] == 35.0
    assert log.directory.parent == tmp_path
    assert log.path.name == "events.jsonl"


def test_the_run_name_is_sanitised_into_the_directory_name(tmp_path):
    log = RunLog("m6/descent one", root=tmp_path, wall=lambda: 1786000000.0)
    assert "/" not in log.directory.name
    assert log.directory.name.endswith("m6-descent-one")


# -- the envelope --------------------------------------------------------------


def test_every_event_carries_seq_both_clocks_and_the_area(tmp_path):
    log, clock = make_log(tmp_path)
    log.area(20, "Forgotten Tower")
    log.event("action.move", target=[10002, 8013])
    clock.advance(1.5)
    log.event("action.interact", target=[10002, 8013])

    events = load(log.directory)
    assert [e["seq"] for e in events] == [1, 2]
    assert [e["t"] for e in events] == [0.0, 1.5]
    assert all(e["area"] == 20 for e in events)
    assert all(e["area_name"] == "Forgotten Tower" for e in events)
    # Wall clock is ISO with milliseconds — what the operator saw.
    assert events[0]["at"].startswith("20")
    assert "T" in events[0]["at"]


def test_a_field_named_kind_cannot_clobber_the_event_kind(tmp_path):
    """THE 2026-08-10 pilot bug: every pickup.order_* event was written
    with an item-kind NUMBER as its event kind, because the record merge
    let a field called "kind" overwrite the envelope's. Kind-filtered
    readers saw no order events at all, and a working order system was
    misread live as never booking. The envelope's identity keys are
    inviolable; a colliding field is preserved under field_<name>."""
    log, _ = make_log(tmp_path)
    log.event("pickup.order_open", unit_id=604, kind=685, position=[5232, 5663])
    events = load(log.directory)
    assert events[0]["kind"] == "pickup.order_open"
    assert events[0]["field_kind"] == 685  # renamed, never dropped
    assert events[0]["unit_id"] == 604


def test_the_area_stamp_follows_the_last_transition(tmp_path):
    log, _ = make_log(tmp_path)
    log.area(6, "Black Marsh")
    log.event("action.move")
    log.area(20, "Forgotten Tower")
    log.event("action.move")
    events = load(log.directory)
    assert [e["area_name"] for e in events] == ["Black Marsh", "Forgotten Tower"]


def test_events_before_any_area_is_known_are_not_given_a_fake_one(tmp_path):
    # Honest absence (rule 4): no area is better than a guessed area.
    log, _ = make_log(tmp_path)
    log.event("run.start")
    assert "area" not in load(log.directory)[0]


# -- the four rules -------------------------------------------------------------


def test_a_write_failure_never_raises_and_disables_itself_once(tmp_path):
    warnings = []
    log, _ = make_log(tmp_path, warn=warnings.append)
    # Make the file unwritable by putting a directory where it belongs.
    log.path.unlink(missing_ok=True)
    log.path.mkdir(parents=True, exist_ok=True)

    log.event("action.move")  # must not raise
    log.event("action.move")
    log.event("action.move")

    assert len(warnings) == 1, f"warned {len(warnings)} times: {warnings}"
    assert "logging disabled" in warnings[0]


def test_an_unopenable_directory_never_raises(tmp_path):
    warnings = []
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    log = RunLog("x", root=blocker, warn=warnings.append)
    log.event("anything")  # must not raise
    assert warnings


def test_the_file_is_readable_while_the_run_is_still_going(tmp_path):
    # Rule 2: append and flush per event — the run you most want to read
    # is the one that died, so nothing may be buffered until close.
    log, _ = make_log(tmp_path)
    log.event("tick", n=1)
    assert len(load(log.directory)) == 1
    log.event("tick", n=2)
    assert len(load(log.directory)) == 2


def test_a_truncated_line_does_not_lose_the_rest_of_the_log(tmp_path):
    log, _ = make_log(tmp_path)
    log.event("tick", n=1)
    with open(log.path, "a", encoding="utf-8") as fh:
        fh.write('{"kind": "tick", "n": 2\n')  # a crash mid-write
    log.event("tick", n=3)
    events = load(log.directory)
    assert [e["n"] for e in events] == [1, 3]


def test_arbitrary_fields_survive_without_a_schema_migration(tmp_path):
    log, _ = make_log(tmp_path)
    log.event("action.interact", click_screen=[812, 344], nested={"a": 1})
    event = load(log.directory)[0]
    assert event["click_screen"] == [812, 344]
    assert event["nested"] == {"a": 1}


def test_unserialisable_values_do_not_break_the_write(tmp_path):
    class Odd:
        def __repr__(self):
            return "<odd>"

    log, _ = make_log(tmp_path)
    log.event("weird", thing=Odd())
    assert load(log.directory)[0]["thing"] == "<odd>"


# -- the null sink ---------------------------------------------------------------


def test_the_null_log_is_silent_and_writes_nothing(tmp_path):
    log = NullRunLog()
    log.area(20, "Forgotten Tower")
    log.event("action.move", target=[1, 2])
    log.close(outcome="done")
    assert log.path is None
    assert not list(tmp_path.iterdir())


# -- the renderer ------------------------------------------------------------------


def test_consecutive_identical_events_collapse_with_a_count_and_span(tmp_path):
    # The T71 lesson, as a test: a per-tick clock inside the label made
    # every line unique and nothing collapsed, burying the reader.
    log, clock = make_log(tmp_path)
    log.area(20, "Forgotten Tower")
    for _ in range(40):
        log.event("step.decision", note="waiting out the last click (11 away)")
        clock.advance(0.85)
    lines = render(load(log.directory))
    assert len(lines) == 1, "did not collapse:\n" + "\n".join(lines[:5])
    assert "x40" in lines[0]
    assert "33.1s" in lines[0]


def test_volatile_fields_do_not_defeat_collapsing(tmp_path):
    log, clock = make_log(tmp_path)
    for n in range(5):
        log.event("tick", n=n, dur_s=0.8 + n / 100, step="traverse")
        clock.advance(1.0)
    assert len(render(load(log.directory))) == 1


def test_different_events_do_not_collapse_together(tmp_path):
    log, _ = make_log(tmp_path)
    log.event("step.decision", note="a")
    log.event("step.decision", note="b")
    log.event("step.decision", note="a")
    assert len(render(load(log.directory))) == 3


def test_a_coordinate_payload_renders_compactly(tmp_path):
    log, _ = make_log(tmp_path)
    log.event(
        "action.interact",
        target={
            "world": [10002, 8013], "local": [2, 13],
            "rel": [-4, 11], "dist": 11, "bearing": "SE",
        },
    )
    line = render(load(log.directory))[0]
    assert "(10002, 8013)" in line
    assert "local(2, 13)" in line
    assert "11 away" in line
    assert "SE" in line


def test_the_summary_reports_ticks_areas_and_counts(tmp_path):
    log, clock = make_log(tmp_path)
    log.area(6, "Black Marsh")
    log.event("tick", n=1, dur_s=0.5)
    clock.advance(10.0)
    log.area(20, "Forgotten Tower")
    log.event("tick", n=2, dur_s=1.5)
    clock.advance(100.0)
    log.event("run.end", outcome="failed")

    text = "\n".join(summarize(load(log.directory)))
    assert "duration" in text and "110" in text
    assert "ticks" in text and "max 1.500s" in text
    # Where the run spent itself — the first question about a slow run.
    assert "Forgotten Tower" in text
    assert "tick" in text


def test_summarising_an_empty_log_says_so(tmp_path):
    assert summarize([]) == ["(no events)"]


def test_latest_run_finds_the_newest_directory(tmp_path):
    (tmp_path / "20260805-210000-a").mkdir()
    (tmp_path / "20260805-213000-b").mkdir()
    assert latest_run(tmp_path).name == "20260805-213000-b"
    assert latest_run(tmp_path / "empty") is None


def test_loading_a_missing_run_returns_nothing_rather_than_raising(tmp_path):
    assert load(tmp_path / "nope") == []


# -- the pickup census ----------------------------------------------------------
#
# Answering "were any whitelisted items not picked up" took a throwaway
# correlation script on 2026-08-06, because eleven of that run's thirteen
# misses emitted no event. The join belongs in the tool.


def attempt(uid, item, area, pos, n=1):
    return [
        {
            "kind": "action.pickup_attempt", "unit_id": uid, "item": item,
            "area_name": area, "target": {"world": list(pos)}, "attempt": i,
        }
        for i in range(n)
    ]


def test_the_pickup_report_counts_wanted_against_collected():
    from pd2bot.runlog import pickup_report

    events = (
        attempt(1, "hel_rune", "Cellar 5", (10, 10), n=2)
        + attempt(2, "nef_rune", "Cellar 5", (11, 10), n=8)
        + [{"kind": "item.collected", "unit_id": 1, "item": "hel_rune",
            "position": {"world": [10, 10]}}]
    )
    text = "\n".join(pickup_report(events))
    assert "1/2 collected (50%)" in text
    assert "nef_rune" in text and "8 clicks" in text
    assert "MISSED (1)" in text


def test_the_pickup_report_carries_the_write_off_reason_and_neighbours():
    from pd2bot.runlog import pickup_report

    events = attempt(2, "nef_rune", "Cellar 5", (11, 10), n=8) + [
        {"kind": "item.abandoned", "unit_id": 2, "item": "nef_rune",
         "reason": "clicks did not land", "clicks": 8, "neighbours": 3},
    ]
    text = "\n".join(pickup_report(events))
    assert "clicks did not land" in text
    assert "3 neighbour(s)" in text


def test_the_pickup_report_is_honest_about_what_an_older_log_lacks():
    """The baseline run predates the write-off event, and a report that
    defaulted its absence to zero would invent the very number the fix is
    measured against."""
    from pd2bot.runlog import pickup_report

    text = "\n".join(pickup_report(attempt(2, "nef_rune", "C5", (11, 10), n=8)))
    assert "no write-off event" in text
    assert "neighbours unknown" in text
    assert "0 neighbour" not in text


def test_the_pickup_report_notices_an_item_that_came_up_unattempted():
    # The "clicked A, got B" tell, at report level.
    from pd2bot.runlog import pickup_report

    events = attempt(1, "potion", "C1", (10, 10), n=8) + [
        {"kind": "item.collected", "unit_id": 99, "item": "rune",
         "position": {"world": [11, 10]}},
    ]
    text = "\n".join(pickup_report(events))
    assert "no attempt recorded" in text


def test_the_pickup_report_says_so_when_there_is_nothing_to_report():
    from pd2bot.runlog import pickup_report

    assert pickup_report([]) == ["PICKUP  no pickup attempts in this log"]
