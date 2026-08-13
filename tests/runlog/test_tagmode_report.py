"""The tag-mode battery table (R250): windows, wantedness, honest absence."""

from pd2bot.runlog import tagmode_report


def _round(block, round_no, mode, t0, *, wanted=3, junk=1, kinds=(999,),
           collected=(), junk_collected_seen=(), end=None):
    events = [{
        "kind": "battery.round", "stage": "test_start", "t": t0,
        "block": block, "round_no": round_no, "mode": mode,
        "wanted_on_ground": wanted, "junk_on_ground": junk,
        "wanted_kinds": list(kinds),
    }]
    for dt in collected:
        events.append({"kind": "item.collected", "t": t0 + dt,
                       "item_kind": kinds[0], "unit_id": 1})
        events.append({"kind": "action.pickup_attempt", "t": t0 + dt,
                       "unit_id": 1})
    for dt in junk_collected_seen:
        events.append({"kind": "item.collected", "t": t0 + dt,
                       "item_kind": 555, "unit_id": 2})
    if end is not None:
        events.append({
            "kind": "battery.round", "stage": "test_end",
            "t": t0 + end["elapsed_s"], "block": block,
            "round_no": round_no, "mode": mode, **end,
        })
    return events


def test_rounds_window_the_item_stream_and_aggregate_by_block():
    events = (
        _round("A", 1, 1, 10.0, collected=(2.0, 5.0),
               junk_collected_seen=(6.0,),
               end={"elapsed_s": 30.0, "timed_out": True, "collected": 2,
                    "wanted_left": 1, "junk_collected": 1})
        + _round("B", 1, 2, 50.0, collected=(2.0, 3.0, 8.0),
                 end={"elapsed_s": 9.0, "timed_out": False, "collected": 3,
                      "wanted_left": 0, "junk_collected": 0})
    )
    # Wanted collections OUTSIDE any window must not be attributed.
    events.append({"kind": "item.collected", "t": 45.0,
                   "item_kind": 999, "unit_id": 9})
    text = "\n".join(tagmode_report(events))
    assert "TIMEOUT" in text
    assert "A (NO NAME TAGS): 1 round(s)  accuracy 2/3" in text
    assert "B (LOOT FILTER TAGS): 1 round(s)  accuracy 3/3 (100%)" in text
    assert "junk picked 1" in "\n".join(
        line for line in text.splitlines() if "NO NAME TAGS" in line
    )


def test_unclosed_rounds_consumption_and_early_stops_are_reported():
    events = _round("C", 2, 3, 100.0)  # a crash mid-round: no test_end
    events.append({"kind": "battery.consumed", "t": 115.0, "block": "C",
                   "round_no": 2, "item_kind": 605})
    events.append({"kind": "battery.loss", "t": 130.0, "block": "C",
                   "round_no": 2, "missing": {"999": 1}})
    events.append({"kind": "battery.end", "t": 131.0, "completed": False,
                   "why": "an item was lost"})
    text = "\n".join(tagmode_report(events))
    assert "OPEN" in text
    assert "CONSUMED BY SLIPPED CLICKS (1)" in text and "round 2C" in text
    assert "LOSS" in text
    assert "stopped early" in text
    assert "DEFAULT TAGS" not in text.split("per mode")[1].split("CONSUMED")[0], (
        "an unclosed round must not enter the aggregates"
    )


def test_no_rounds_is_said_plainly():
    assert tagmode_report([{"kind": "tick", "t": 1.0}]) == [
        "TAGMODE  no battery rounds in this log"
    ]
