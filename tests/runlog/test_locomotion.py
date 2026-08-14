"""The locomotion report (R257 P1): duty cycle, spans, slow ticks, plans."""

from pd2bot.runlog.locomotion import analyze, render


def tick(t, area, world, step=None, dur_s=None, hostiles=0):
    event = {
        "kind": "tick",
        "t": t,
        "area": area,
        "area_name": f"area {area}",
        "player": {"world": list(world)},
        "hostiles": hostiles,
    }
    if step is not None:
        event["step"] = step
    if dur_s is not None:
        event["dur_s"] = dur_s
    return event


def test_gross_vs_net_and_duty_cycle():
    events = [
        tick(0.0, 3, (100, 100)),
        tick(1.0, 3, (110, 100)),   # out 10
        tick(2.0, 3, (100, 100)),   # and back 10: gross 20, net 0
        tick(3.0, 3, (100, 100)),   # 1s idle
    ]
    seg = analyze(events).segments[0]
    assert seg.gross_route == 20.0
    assert seg.net_displacement == 0.0
    assert seg.moving_s == 2.0
    assert seg.idle_s == 1.0
    assert 0.6 < seg.duty_cycle < 0.7


def test_idle_spans_carry_the_step_that_owned_them():
    events = [
        tick(0.0, 3, (100, 100), step="clear_radius"),
        tick(2.0, 3, (100, 100), step="clear_radius"),
        tick(4.0, 3, (100, 100), step="clear_radius"),
        tick(5.0, 3, (120, 100), step="pickup"),  # movement closes the span
    ]
    seg = analyze(events).segments[0]
    assert len(seg.idle_spans) == 1
    span = seg.idle_spans[0]
    assert span.duration_s == 4.0
    assert span.step == "pickup"  # the sample that ENDED it names the step


def test_slow_ticks_list_the_nav_events_inside_their_window():
    events = [
        tick(0.0, 3, (100, 100), step="clear_radius"),
        {"kind": "nav.plan", "t": 20.0, "outcome": "no_path", "duration_s": 19.5},
        {"kind": "nav.failed", "t": 21.0, "detail": "no path from a to b"},
        tick(21.0, 3, (100, 100), step="clear_radius", dur_s=21.0),
    ]
    report = analyze(events, slow_tick_s=4.0)
    assert len(report.slow_ticks) == 1
    slow = report.slow_ticks[0]
    assert slow.dur_s == 21.0
    assert slow.step == "clear_radius"
    assert any("nav.plan no_path" in line for line in slow.inside)
    assert any("nav.failed" in line for line in slow.inside)


def test_plan_summary_counts_outcomes_and_budget_stops():
    events = [
        tick(0.0, 3, (100, 100)),
        {"kind": "nav.plan", "t": 1.0, "outcome": "path", "duration_s": 0.01},
        {"kind": "nav.plan", "t": 2.0, "outcome": "path", "duration_s": 0.02},
        {"kind": "nav.plan", "t": 3.0, "outcome": "no_path", "duration_s": 0.05,
         "budget_exhausted": True},
        tick(4.0, 3, (110, 100)),
    ]
    report = analyze(events)
    assert report.plans == 3
    assert report.plan_outcomes == {"path": 2, "no_path": 1}
    assert report.plan_budget_exhausted == 1
    assert abs(report.plan_time_s - 0.08) < 1e-9
    assert report.plan_worst_s == 0.05


def test_open_idle_span_at_run_end_is_counted():
    events = [
        tick(0.0, 3, (100, 100)),
        tick(2.0, 3, (100, 100)),
        tick(4.0, 3, (100, 100)),
    ]
    seg = analyze(events).segments[0]
    assert len(seg.idle_spans) == 1
    assert seg.idle_spans[0].duration_s == 4.0


def test_human_dialect_reports_without_ticks():
    events = [
        {"kind": "observe.sample", "t": 0.0, "area": 3, "area_name": "Cold Plains",
         "player": {"world": [100, 100]}},
        {"kind": "observe.sample", "t": 1.0, "area": 3, "area_name": "Cold Plains",
         "player": {"world": [112, 100]}},
        {"kind": "observe.pickup", "t": 1.5, "area": 3, "item_kind": 522},
    ]
    report = analyze(events, label="human")
    assert report.segments[0].gross_route == 12.0
    assert report.segments[0].pickups == 1
    assert report.slow_ticks == []
    text = "\n".join(render(report))
    assert "ticks over 4s: none" in text
