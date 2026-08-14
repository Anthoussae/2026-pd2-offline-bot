"""The locomotion report: where a run's movement time actually went.

Built for the clear_radius speed pass (R256/R257): the T92 human-vs-bot
comparison proved the gap (8.3×) and `compare.py` says WHERE it lives
per area; this report says WHY, per run — duty cycle, gross-vs-net
route, every idle span with the step that owned it, every slow tick
with the nav events that happened inside it, and the plan-cost summary
once `nav.plan` events exist.

It reads both sample dialects (`tick` from the engine, `observe.sample`
from the human recorder), sharing `compare.py`'s constants so the two
tools can never disagree about what "idle" means.

Usage:

    python -m pd2bot.runlog.locomotion <run-dir> [--slow-tick 4]

No interpretation, per the run log's own rule: the numbers and their
attributions, never a verdict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from pd2bot.runlog.compare import (
    IDLE_SPAN_S,
    IDLE_SPEED,
    JUMP_SUBTILES,
    PICKUP_KINDS,
    POSITION_KINDS,
)

# A tick longer than this gets listed individually with whatever nav
# events fired inside it. 4 s is the R256 QB acceptance bar.
DEFAULT_SLOW_TICK_S = 4.0


@dataclass
class IdleSpan:
    t_start: float
    t_end: float
    step: str | None  # the step of the span's last sample (bot logs only)

    @property
    def duration_s(self) -> float:
        return self.t_end - self.t_start


@dataclass
class SlowTick:
    t: float
    dur_s: float
    step: str | None
    inside: list[str] = field(default_factory=list)  # nav events in its window


@dataclass
class SegmentReport:
    area: int | None
    area_name: str | None
    t_enter: float
    t_exit: float = 0.0
    samples: int = 0
    gross_route: float = 0.0
    first_pos: tuple[float, float] | None = None
    last_pos: tuple[float, float] | None = None
    moving_s: float = 0.0
    idle_s: float = 0.0
    idle_spans: list[IdleSpan] = field(default_factory=list)
    pickups: int = 0

    @property
    def duration_s(self) -> float:
        return max(0.0, self.t_exit - self.t_enter)

    @property
    def net_displacement(self) -> float:
        if self.first_pos is None or self.last_pos is None:
            return 0.0
        return math.dist(self.first_pos, self.last_pos)

    @property
    def effective_speed(self) -> float:
        return self.gross_route / self.duration_s if self.duration_s > 0 else 0.0

    @property
    def duty_cycle(self) -> float:
        accounted = self.moving_s + self.idle_s
        return self.moving_s / accounted if accounted > 0 else 0.0


@dataclass
class RunReport:
    label: str
    segments: list[SegmentReport] = field(default_factory=list)
    slow_ticks: list[SlowTick] = field(default_factory=list)
    plans: int = 0
    plan_time_s: float = 0.0
    plan_worst_s: float = 0.0
    plan_outcomes: dict = field(default_factory=dict)
    plan_budget_exhausted: int = 0
    total_s: float = 0.0


def _describe_nav_event(event: dict) -> str:
    kind = event.get("kind")
    if kind == "nav.plan":
        return (
            f"nav.plan {event.get('outcome')} {event.get('duration_s', 0)}s"
            + (f" ({event.get('nodes')} nodes)" if event.get("nodes") is not None else "")
        )
    detail = event.get("detail") or ""
    return f"{kind} {detail}"[:100]


def analyze(
    events: list[dict], label: str = "run", slow_tick_s: float = DEFAULT_SLOW_TICK_S
) -> RunReport:
    """Fold one run's events into a RunReport. Pure; order-dependent."""
    report = RunReport(label=label)
    current: SegmentReport | None = None
    last: tuple[float, tuple[float, float]] | None = None
    open_idle_start: float | None = None

    def close_idle(t_end: float, step: str | None) -> None:
        nonlocal open_idle_start
        if (
            open_idle_start is not None
            and current is not None
            and t_end - open_idle_start >= IDLE_SPAN_S
        ):
            current.idle_spans.append(IdleSpan(open_idle_start, t_end, step))
        open_idle_start = None

    for index, event in enumerate(events):
        kind = event.get("kind")
        t = float(event.get("t", 0.0))
        report.total_s = max(report.total_s, t)

        if kind == "nav.plan":
            report.plans += 1
            duration = float(event.get("duration_s") or 0.0)
            report.plan_time_s += duration
            report.plan_worst_s = max(report.plan_worst_s, duration)
            outcome = event.get("outcome") or "?"
            report.plan_outcomes[outcome] = report.plan_outcomes.get(outcome, 0) + 1
            if event.get("budget_exhausted"):
                report.plan_budget_exhausted += 1
            continue

        if kind in PICKUP_KINDS and current is not None:
            current.pickups += 1
            continue

        if kind not in POSITION_KINDS:
            continue

        area = event.get("area")
        step = event.get("step")
        if current is None or current.area != area:
            close_idle(last[0] if last else t, step)
            current = SegmentReport(
                area=area, area_name=event.get("area_name"), t_enter=t, t_exit=t
            )
            report.segments.append(current)
            last = None  # positions never bridge a transition

        # Slow ticks: only the engine dialect carries dur_s.
        dur = event.get("dur_s")
        if dur is not None and float(dur) > slow_tick_s:
            inside = [
                _describe_nav_event(e)
                for e in events[max(0, index - 20):index]
                if e.get("kind") in ("nav.failed", "nav.plan")
                and float(e.get("t", 0.0)) > t - float(dur)
            ]
            report.slow_ticks.append(
                SlowTick(t=t, dur_s=float(dur), step=step, inside=inside)
            )

        current.t_exit = t
        current.samples += 1
        world = (event.get("player") or {}).get("world")
        if not world:
            continue
        position = (float(world[0]), float(world[1]))
        if current.first_pos is None:
            current.first_pos = position
        current.last_pos = position
        if last is not None:
            dt = t - last[0]
            dist = math.dist(position, last[1])
            if dt > 0 and dist <= JUMP_SUBTILES:
                current.gross_route += dist
                if dist / dt < IDLE_SPEED:
                    current.idle_s += dt
                    if open_idle_start is None:
                        open_idle_start = last[0]
                else:
                    current.moving_s += dt
                    close_idle(last[0], step)
        last = (t, position)
    if last is not None and current is not None:
        # An idle span still open at the end is precisely the one a
        # wedged run needs on the record (the sampler's close() rule).
        close_idle(last[0], None)
    return report


# -- rendering ---------------------------------------------------------------------


def render(report: RunReport, slow_tick_s: float = DEFAULT_SLOW_TICK_S) -> list[str]:
    lines = [f"locomotion report — {report.label} ({report.total_s:.0f}s total)"]
    for seg in report.segments:
        name = seg.area_name or f"area {seg.area}"
        lines.append("")
        lines.append(f"{name} (area {seg.area}) — {seg.duration_s:.0f}s, {seg.samples} samples")
        lines.append(
            f"  route {seg.gross_route:.0f}st gross / {seg.net_displacement:.0f}st net"
            f"  ·  speed {seg.effective_speed:.1f} st/s"
            f"  ·  duty {seg.duty_cycle * 100:.0f}%"
            f"  (moving {seg.moving_s:.0f}s / idle {seg.idle_s:.0f}s)"
        )
        if seg.pickups:
            lines.append(f"  pickups {seg.pickups}")
        spans = sorted(seg.idle_spans, key=lambda s: -s.duration_s)
        if spans:
            lines.append(f"  idle spans >= {IDLE_SPAN_S:.0f}s: {len(spans)}")
            for span in spans[:10]:
                step = f"  [{span.step}]" if span.step else ""
                lines.append(
                    f"    t+{span.t_start:7.1f}  {span.duration_s:5.1f}s{step}"
                )
            if len(spans) > 10:
                lines.append(f"    ... and {len(spans) - 10} more")
    if report.slow_ticks:
        lines.append("")
        lines.append(f"ticks over {slow_tick_s:g}s: {len(report.slow_ticks)}")
        for tick in report.slow_ticks:
            step = f"  [{tick.step}]" if tick.step else ""
            lines.append(f"  t+{tick.t:7.1f}  {tick.dur_s:5.1f}s{step}")
            for inner in tick.inside:
                lines.append(f"      {inner}")
    else:
        lines.append("")
        lines.append(f"ticks over {slow_tick_s:g}s: none")
    if report.plans:
        lines.append("")
        outcomes = ", ".join(f"{k} x{v}" for k, v in sorted(report.plan_outcomes.items()))
        lines.append(
            f"plans: {report.plans} ({outcomes}) — total {report.plan_time_s:.2f}s, "
            f"worst {report.plan_worst_s:.2f}s"
            + (
                f", budget exhausted x{report.plan_budget_exhausted}"
                if report.plan_budget_exhausted
                else ""
            )
        )
    return lines


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    import argparse

    from pd2bot.runlog.events import latest_run, load

    parser = argparse.ArgumentParser(
        description="Movement numbers for one run: duty cycle, idle spans, slow ticks."
    )
    parser.add_argument("run", nargs="?", help="run directory (default: latest)")
    parser.add_argument(
        "--slow-tick", type=float, default=DEFAULT_SLOW_TICK_S,
        help="list ticks longer than this many seconds (default 4)",
    )
    args = parser.parse_args(argv)

    run_dir = Path(args.run) if args.run else latest_run()
    if run_dir is None:
        print("no runs found")
        return 1
    events = load(run_dir)
    if not events:
        print(f"no events in {run_dir}")
        return 1
    report = analyze(events, label=Path(run_dir).name, slow_tick_s=args.slow_tick)
    for line in render(report, slow_tick_s=args.slow_tick):
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
