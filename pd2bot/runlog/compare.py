"""Reduce two run logs — one played by anyone — to comparable phase tables.

Built for R255: the operator plays a Cold Plains run while
`pd2bot.observe` records it, and the question is where the wall-clock
difference against a bot run actually lives. Both logs carry
position-bearing samples with the same fields (`tick` from the engine,
`observe.sample` from the recorder), so one reducer serves both and the
comparison never depends on who was at the keyboard.

Everything a segment reports is computed from samples alone:

- **route length** — summed distance between consecutive samples, with
  loading-screen jumps (> `JUMP_SUBTILES` in one step) excluded.
- **moving vs idle** — each inter-sample gap is idle when the implied
  speed is under `IDLE_SPEED` subtiles/s (far below any real walk).
  Idle spans of `IDLE_SPAN_S` or longer are counted and the longest is
  kept: "how often did this run stand still, and for how long" is the
  discrepancy question stated as a number.
- **combat exposure** — time with at least one live hostile in
  perception. Symmetric, unlike kill counts (the engine's log has no
  monster-death event), so it is what the comparison table uses.
- **pickups** — `item.collected` (engine) + `observe.pickup` (recorder).

Usage:

    python -m pd2bot.runlog.compare <run-dir-a> <run-dir-b>

No interpretation: the output says where the seconds went, per area;
whose fault they are is the reader's conclusion to draw.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

# Sample kinds that carry a player position, per emitter.
POSITION_KINDS = frozenset({"tick", "observe.sample"})
PICKUP_KINDS = frozenset({"item.collected", "observe.pickup"})
# Below this implied speed (subtiles/s) an inter-sample gap is idle.
# Real walking measures an order of magnitude above it.
IDLE_SPEED = 1.0
# An idle span shorter than this is a beat between actions, not a stall.
IDLE_SPAN_S = 2.0
# A single-step displacement above this is a load (waypoint, staircase),
# not walking; it joins no route and neither moving nor idle time.
JUMP_SUBTILES = 60


@dataclass
class Segment:
    """One contiguous stay in one area."""

    area: int | None
    area_name: str | None
    t_enter: float
    t_exit: float = 0.0
    samples: int = 0
    route_subtiles: float = 0.0
    moving_s: float = 0.0
    idle_s: float = 0.0
    idle_spans: int = 0
    longest_idle_s: float = 0.0
    combat_s: float = 0.0
    pickups: int = 0
    kills: int = 0
    _open_idle_s: float = field(default=0.0, repr=False)

    @property
    def duration_s(self) -> float:
        return max(0.0, self.t_exit - self.t_enter)

    def close_idle(self) -> None:
        if self._open_idle_s >= IDLE_SPAN_S:
            self.idle_spans += 1
            self.longest_idle_s = max(self.longest_idle_s, self._open_idle_s)
        self._open_idle_s = 0.0


@dataclass
class RunProfile:
    """A whole run reduced to its area segments."""

    label: str
    segments: list[Segment] = field(default_factory=list)
    total_s: float = 0.0

    def segment_for(self, area: int | None) -> Segment | None:
        """The FIRST stay in an area — the comparison's unit of account."""
        for segment in self.segments:
            if segment.area == area:
                return segment
        return None


def reduce_run(events: list[dict], label: str = "run") -> RunProfile:
    """Fold an event list into a RunProfile. Pure; order-dependent."""
    profile = RunProfile(label=label)
    current: Segment | None = None
    last: tuple[float, tuple[float, float]] | None = None  # (t, position)

    def enter(area: int | None, name: str | None, t: float) -> Segment:
        nonlocal last
        segment = Segment(area=area, area_name=name, t_enter=t, t_exit=t)
        profile.segments.append(segment)
        last = None  # positions never bridge a transition
        return segment

    for event in events:
        kind = event.get("kind")
        t = float(event.get("t", 0.0))
        profile.total_s = max(profile.total_s, t)
        area = event.get("area")
        if kind in PICKUP_KINDS or kind == "observe.kill" or kind in POSITION_KINDS:
            if current is None or current.area != area:
                if current is not None:
                    current.close_idle()
                current = enter(area, event.get("area_name"), t)
        if current is None:
            continue
        if kind in PICKUP_KINDS:
            current.pickups += 1
        elif kind == "observe.kill":
            current.kills += 1
        if kind not in POSITION_KINDS:
            continue
        current.t_exit = t
        current.samples += 1
        player = event.get("player") or {}
        world = player.get("world")
        if not world:
            continue
        position = (float(world[0]), float(world[1]))
        if last is not None:
            dt = t - last[0]
            dist = math.dist(position, last[1])
            if dt > 0 and dist <= JUMP_SUBTILES:
                current.route_subtiles += dist
                if dist / dt < IDLE_SPEED:
                    current.idle_s += dt
                    current._open_idle_s += dt
                else:
                    current.moving_s += dt
                    current.close_idle()
        last = (t, position)
    if current is not None:
        current.close_idle()
    # Combat exposure needs the inter-sample dt, so it is a second pass
    # kept trivially simple rather than woven into the loop above.
    _fold_combat(events, profile)
    return profile


def _fold_combat(events: list[dict], profile: RunProfile) -> None:
    last_t: float | None = None
    last_hostiles = 0
    last_area: int | None = None
    for event in events:
        if event.get("kind") not in POSITION_KINDS:
            continue
        t = float(event.get("t", 0.0))
        area = event.get("area")
        if last_t is not None and area == last_area and last_hostiles > 0:
            segment = profile.segment_for(area)
            if segment is not None and segment.t_enter <= t <= segment.t_exit:
                segment.combat_s += t - last_t
        last_t, last_area = t, area
        last_hostiles = int(event.get("hostiles") or 0)


# -- rendering ---------------------------------------------------------------------


def _row(name: str, a: str, b: str, delta: str = "") -> str:
    return f"  {name:<26}{a:>14}{b:>14}{delta:>14}"


def render_comparison(a: RunProfile, b: RunProfile) -> list[str]:
    """Side-by-side, aligned by area (first stay each). No verdicts."""
    lines = [
        _row("", a.label[:13], b.label[:13], "delta"),
        _row("total", f"{a.total_s:.0f}s", f"{b.total_s:.0f}s",
             f"{b.total_s - a.total_s:+.0f}s"),
    ]
    seen: list[int | None] = []
    for segment in [*a.segments, *b.segments]:
        if segment.area not in seen:
            seen.append(segment.area)
    for area in seen:
        sa, sb = a.segment_for(area), b.segment_for(area)
        name = (sa or sb).area_name or f"area {area}"
        lines.append("")
        lines.append(f"{name} (area {area})")

        def cell(seg: Segment | None, fmt) -> str:
            return fmt(seg) if seg is not None else "-"

        def delta(fmt_value, unit: str, sa=sa, sb=sb) -> str:
            if sa is None or sb is None:
                return ""
            return f"{fmt_value(sb) - fmt_value(sa):+.0f}{unit}"

        lines.append(_row(
            "duration",
            cell(sa, lambda s: f"{s.duration_s:.0f}s"),
            cell(sb, lambda s: f"{s.duration_s:.0f}s"),
            delta(lambda s: s.duration_s, "s"),
        ))
        lines.append(_row(
            "route",
            cell(sa, lambda s: f"{s.route_subtiles:.0f}st"),
            cell(sb, lambda s: f"{s.route_subtiles:.0f}st"),
            delta(lambda s: s.route_subtiles, "st"),
        ))
        lines.append(_row(
            "moving / idle",
            cell(sa, lambda s: f"{s.moving_s:.0f}/{s.idle_s:.0f}s"),
            cell(sb, lambda s: f"{s.moving_s:.0f}/{s.idle_s:.0f}s"),
        ))
        lines.append(_row(
            f"idle spans >= {IDLE_SPAN_S:.0f}s",
            cell(sa, lambda s: f"{s.idle_spans} (max {s.longest_idle_s:.0f}s)"),
            cell(sb, lambda s: f"{s.idle_spans} (max {s.longest_idle_s:.0f}s)"),
        ))
        lines.append(_row(
            "combat exposure",
            cell(sa, lambda s: f"{s.combat_s:.0f}s"),
            cell(sb, lambda s: f"{s.combat_s:.0f}s"),
        ))
        lines.append(_row(
            "pickups",
            cell(sa, lambda s: str(s.pickups)),
            cell(sb, lambda s: str(s.pickups)),
        ))
        if (sa and sa.kills) or (sb and sb.kills):
            lines.append(_row(
                "kills (observed)",
                cell(sa, lambda s: str(s.kills)),
                cell(sb, lambda s: str(s.kills)),
            ))
        lines.append(_row(
            "samples",
            cell(sa, lambda s: str(s.samples)),
            cell(sb, lambda s: str(s.samples)),
        ))
    return lines


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    import argparse
    import json

    from pd2bot.runlog.events import load

    parser = argparse.ArgumentParser(
        description="Two run logs, side by side, per area."
    )
    parser.add_argument("run_a", help="first run directory")
    parser.add_argument("run_b", help="second run directory")
    args = parser.parse_args(argv)

    profiles = []
    for run_dir in (args.run_a, args.run_b):
        path = Path(run_dir)
        label = path.name
        try:
            header = json.loads((path / "run.json").read_text(encoding="utf-8"))
            if header.get("recorder") == "human-observer":
                label = "human"
            else:
                label = header.get("run", label)
        except OSError:
            pass
        events = load(path)
        if not events:
            print(f"no events in {path}")
            return 1
        profiles.append(reduce_run(events, label=label))
    for line in render_comparison(*profiles):
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
