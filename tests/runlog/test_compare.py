"""The human-vs-bot reducer (R255): both sample dialects, one profile."""

from pd2bot.runlog.compare import (
    IDLE_SPAN_S,
    reduce_run,
    render_comparison,
)


def tick(t, area, world, hostiles=0, area_name=None, kind="tick"):
    return {
        "kind": kind,
        "t": t,
        "area": area,
        "area_name": area_name or f"area {area}",
        "player": {"world": list(world)},
        "hostiles": hostiles,
    }


def sample(t, area, world, hostiles=0):
    return tick(t, area, world, hostiles=hostiles, kind="observe.sample")


def test_segments_split_on_area_and_both_dialects_count():
    events = [
        tick(0.0, 1, (100, 100)),
        tick(5.0, 1, (140, 100)),
        sample(10.0, 3, (200, 200)),
        sample(15.0, 3, (240, 200)),
    ]
    profile = reduce_run(events, label="mixed")
    assert [s.area for s in profile.segments] == [1, 3]
    assert profile.segments[0].samples == 2
    assert profile.segments[1].samples == 2
    assert profile.total_s == 15.0


def test_route_length_sums_walks_and_skips_loading_jumps():
    events = [
        sample(0.0, 3, (100, 100)),
        sample(1.0, 3, (110, 100)),  # 10 subtiles walked
        sample(2.0, 3, (300, 300)),  # a load jump: excluded
        sample(3.0, 3, (310, 300)),  # 10 more
    ]
    segment = reduce_run(events).segments[0]
    assert segment.route_subtiles == 20.0


def test_positions_never_bridge_an_area_transition():
    """The step from the waypoint to Cold Plains is a teleport, not a
    280-subtile sprint — it must join neither route nor speed."""
    events = [
        sample(0.0, 1, (100, 100)),
        sample(1.0, 3, (300, 300)),
        sample(2.0, 3, (310, 300)),
    ]
    profile = reduce_run(events)
    assert profile.segment_for(3).route_subtiles == 10.0


def test_idle_time_and_spans_are_separated_from_movement():
    events = [
        sample(0.0, 3, (100, 100)),
        sample(1.0, 3, (110, 100)),  # moving (10 st/s)
        sample(2.0, 3, (110, 100)),  # idle 1s
        sample(3.0, 3, (110, 100)),  # idle 2s -> one span
        sample(4.0, 3, (120, 100)),  # moving again
    ]
    segment = reduce_run(events).segments[0]
    assert segment.moving_s == 2.0
    assert segment.idle_s == 2.0
    assert segment.idle_spans == 1
    assert segment.longest_idle_s >= IDLE_SPAN_S


def test_an_idle_span_still_open_at_the_end_is_counted():
    events = [
        sample(0.0, 3, (100, 100)),
        sample(2.0, 3, (100, 100)),
        sample(4.0, 3, (100, 100)),
    ]
    segment = reduce_run(events).segments[0]
    assert segment.idle_spans == 1
    assert segment.longest_idle_s == 4.0


def test_combat_exposure_is_time_with_hostiles_present():
    events = [
        sample(0.0, 3, (100, 100), hostiles=0),
        sample(1.0, 3, (110, 100), hostiles=2),
        sample(3.0, 3, (120, 100), hostiles=1),
        sample(4.0, 3, (130, 100), hostiles=0),
    ]
    segment = reduce_run(events).segments[0]
    # hostile at t=1 covers 1->3, at t=3 covers 3->4; t=0's zero covers 0->1.
    assert segment.combat_s == 3.0


def test_pickups_count_both_emitters():
    events = [
        sample(0.0, 3, (100, 100)),
        {"kind": "observe.pickup", "t": 1.0, "area": 3, "item_kind": 522},
        {"kind": "item.collected", "t": 2.0, "area": 3, "item_kind": 611},
        sample(3.0, 3, (100, 110)),
    ]
    assert reduce_run(events).segments[0].pickups == 2


def test_render_pairs_areas_and_reports_missing_sides_honestly():
    human = reduce_run([sample(0.0, 1, (100, 100)), sample(5.0, 1, (140, 100))],
                       label="human")
    bot = reduce_run(
        [tick(0.0, 1, (100, 100)), tick(5.0, 3, (300, 300)),
         tick(10.0, 3, (340, 300))],
        label="cold-plains",
    )
    text = "\n".join(render_comparison(human, bot))
    assert "Cold Plains" not in text  # names come from events, not guesses
    assert "area 3" in text
    assert "-" in text  # the human never reached area 3
