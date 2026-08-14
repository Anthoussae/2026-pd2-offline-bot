"""The run event log: a structured record of everything a run did.

**Why this exists, precisely.** On 2026-08-05 the bot spent 144 seconds
in the Forgotten Tower — an empty 19x19-subtile square room, eleven
subtiles from the staircase it was trying to take — and gave the run up.
Nobody could say why. Not because the behaviour was subtle: because of
roughly 150 decisions made in that room, **five were written down**.
The atlas held the room completely, A* planned it as one leg, the seed
matched, and routing was never even invoked. The bot was not lost; the
instrument was blind.

What filled that vacuum was speculation — two confident diagnoses, both
wrong, one of which had already been turned into a code change before
the user killed it with a single fact ("that room never has monsters").

So this module exists to make a run a matter of record rather than
reconstruction, and it obeys four rules that come straight out of that
failure:

**Never raises.** A logging failure must not end a run. The write path
is wrapped; on error it disables itself, says so once, and the run
continues. Instrumentation is not a dependency.

**Never blocks.** Append and flush, nothing else. No rotation, no
compaction, no network. The file is readable while the bot is running
and survives a crash — the `Narrator` discipline (R179), for the same
reason: the run you most want to read is the one that died.

**Never interprets.** Events record what happened — "clicked at X, the
player was at Y, the projection was screen point Z" — never what it
meant. "The click failed" is a conclusion, and conclusions belong to
whoever reads the log. This rule is the direct lesson of the two wrong
diagnoses: both were inferences dressed as observations.

**Honest absence.** A field the bot could not read is `None`, with a
reason where one is available. Never a plausible-looking default. A
guessed value in a diagnostic log is worse than no log at all, because
it is indistinguishable from a real one.

**It is not optional** (R220 Q11). `build_bot` opens one unconditionally;
the only silent path is `NullRunLog`, passed explicitly by unit tests and
the sim. Optional instrumentation means the one run you most need to
explain is the one where somebody forgot the flag — which is not a
hypothetical, it is exactly what happened.

Layout, one directory per run, nothing pruned (R220 Q2):

    logs/runs/<YYYYMMDD-HHMMSS>-<runname>/
        run.json        the header, written once at open
        events.jsonl    one JSON object per line, appended

Read one back with the renderer:

    python -m pd2bot.runlog                    # the most recent run
    python -m pd2bot.runlog <run-dir>
    python -m pd2bot.runlog <run-dir> --kind action. --since 59

The schema reference lives in `docs/architecture/run-log.md`; this
module owns the envelope and the writing rules.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_ROOT = Path("logs") / "runs"


def _default_warn(text: str) -> None:  # pragma: no cover - console only
    print(f"!!  run log: {text}", flush=True)


class NullRunLog:
    """The silent implementation. The ONLY way to not log (R220 Q11).

    Unit tests and the sim pass this explicitly. Nothing that touches
    the live game may use it — `build_bot` opens a real one, and that is
    deliberate: the alternative is a forgotten flag on the run that
    matters most.
    """

    path: Path | None = None
    directory: Path | None = None
    # Emitters check this BEFORE gathering anything an event would need.
    # It is not an optimisation detail: `_here()` and `_vitals()` are live
    # memory reads, and a silent log that still paid for them would make
    # instrumentation observable in the behaviour it instruments — which
    # `test_nothing_is_read_until_we_have_actually_cast` exists to forbid.
    enabled = False

    def event(self, kind: str, /, **fields: Any) -> None:
        return None

    def area(self, area_id: int | None, area_name: str | None = None) -> None:
        return None

    def close(self, **fields: Any) -> None:
        return None

    def __enter__(self) -> NullRunLog:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class RunLog:
    """One run's event log: a directory, a header, and an append-only file.

    Every event carries the same envelope, filled here rather than by
    the caller — an emitter that has to remember to stamp its own events
    will eventually forget, and a partly-stamped log is worse than none:

    - `seq`  a monotonic counter, so ordering survives equal timestamps
    - `at`   ISO wall clock, local — what the operator saw on screen
    - `t`    seconds since run start, monotonic — what arithmetic uses
    - `area` / `area_name` — the last area told to `area()`, so no event
      is orphaned and no emitter needs to look it up

    Both clocks are injectable, because the sim's clock is fake and
    advances only when the sim says so.
    """

    enabled = True

    def __init__(
        self,
        run_name: str,
        *,
        root: Path | str = DEFAULT_ROOT,
        header: dict | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        warn: Callable[[str], None] = _default_warn,
    ) -> None:
        self._clock = clock
        self._wall = wall
        self._warn = warn
        self._started = clock()
        self._seq = 0
        self._area: int | None = None
        self._area_name: str | None = None
        self._disabled = False

        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(wall()))
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in run_name)
        self.directory = Path(root) / f"{stamp}-{safe}"
        self.path = self.directory / "events.jsonl"
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema": SCHEMA_VERSION,
                "run": run_name,
                "started_at": self._iso(),
                **(header or {}),
            }
            (self.directory / "run.json").write_text(
                json.dumps(payload, indent=2, default=str), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 - never fatal (rule 1)
            self._fail(f"could not open {self.directory} ({exc})")

    # -- writing ---------------------------------------------------------------

    def area(self, area_id: int | None, area_name: str | None = None) -> None:
        """Set the area stamped onto subsequent events.

        Called by whoever proves an area change (the traverse step, the
        waypoint travel). Kept as ambient state rather than a per-event
        argument because every emitter would otherwise have to thread it,
        and the ones that forgot would produce events nobody could place.
        """
        self._area = area_id
        self._area_name = area_name

    def event(self, kind: str, /, **fields: Any) -> None:
        """Append one event. Never raises (rule 1); never blocks (rule 2).

        `kind` is POSITIONAL-ONLY, and that is load-bearing rather than
        stylistic: without it, no emitter could ever have a field called
        "kind" — and half of what this log describes (monsters, items)
        has a kind. Found the moment `npc.interact` tried to record the
        NPC's kind and collided with the parameter name.

        The positional-only signature is NOT enough on its own: a field
        literally named "kind" used to survive the call and then clobber
        the envelope's event kind in the record merge, which is how every
        `pickup.order_*` event of the 2026-08-10 pilot batch was written
        with an item-kind NUMBER as its event kind — invisible to every
        kind-filtered reader, and misread live as "orders never booked".
        The envelope's identity keys (seq, at, t, kind) are therefore
        inviolable: a colliding field is preserved under `field_<name>`
        rather than dropped (rule: never lose what an emitter said) —
        but emitters should name such fields properly (`item_kind`,
        `npc_kind`, `monster_kind`) so the rename never fires.

        `kind` is a dotted namespace — `action.move`, `item.dropped`,
        `step.decision` — so a reader can filter by prefix. Unknown
        fields are allowed on purpose: an emitter that learns something
        new should be able to record it without a schema migration, and
        the renderer degrades gracefully to key=value for anything it
        does not recognise.
        """
        if self._disabled:
            return
        self._seq += 1
        record = {
            "seq": self._seq,
            "at": self._iso(),
            "t": round(self._clock() - self._started, 3),
            "kind": kind,
        }
        if self._area is not None:
            record["area"] = self._area
            record["area_name"] = self._area_name
        for key in ("seq", "at", "t", "kind"):
            if key in fields:
                fields[f"field_{key}"] = fields.pop(key)
        record.update(fields)
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001 - never fatal (rule 1)
            self._fail(f"could not write to {self.path} ({exc})")

    def close(self, **fields: Any) -> None:
        """Final event. `fields` typically carries the run's ending."""
        self.event("run.end", **fields)

    # -- internals -------------------------------------------------------------

    def _iso(self) -> str:
        seconds = self._wall()
        base = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(seconds))
        return f"{base}.{int((seconds % 1) * 1000):03d}"

    def _fail(self, reason: str) -> None:
        """Disable the log, once, loudly. A broken instrument that keeps
        half-writing is worse than one that admits it stopped."""
        if self._disabled:
            return
        self._disabled = True
        self._warn(f"{reason} — logging disabled for the rest of this run")

    def __enter__(self) -> RunLog:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


# -- reading ----------------------------------------------------------------------


def load(run_dir: Path | str) -> list[dict]:
    """Every event in a run directory, in order.

    A malformed line is SKIPPED rather than fatal: JSONL degrades
    gracefully, and a log truncated by a crash — precisely the log you
    most want to read — is still readable up to the truncation.
    """
    path = Path(run_dir)
    if path.is_dir():
        path = path / "events.jsonl"
    events = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return events
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def latest_run(root: Path | str = DEFAULT_ROOT) -> Path | None:
    """The most recent run directory, by name (the names sort by time)."""
    directories = sorted(p for p in Path(root).glob("*") if p.is_dir())
    return directories[-1] if directories else None


# The fields excluded from the collapse key when the renderer folds
# consecutive identical events. Found the hard way while demoing the T71
# decision trace: an elapsed-seconds value inside the label made every
# line unique, so nothing collapsed and the reader got one line per tick
# — which is the wall of noise that collapsing exists to prevent.
_VOLATILE = frozenset({"seq", "at", "t", "dur_s", "elapsed_s", "timing", "n"})


def _collapse_key(event: dict) -> tuple:
    return (
        event.get("kind"),
        tuple(
            sorted(
                (k, json.dumps(v, sort_keys=True, default=str))
                for k, v in event.items()
                if k not in _VOLATILE
            )
        ),
    )


def _place(value: Any) -> str:
    """A coordinate payload (mapframe.describe) rendered compactly."""
    if not isinstance(value, dict) or "world" not in value:
        return json.dumps(value, default=str)
    out = f"{tuple(value['world'])}"
    if value.get("local") is not None:
        out += f" local{tuple(value['local'])}"
    if value.get("dist") is not None:
        out += f" {value['dist']} away"
    if value.get("bearing"):
        out += f" {value['bearing']}"
    return out


def describe_event(event: dict) -> str:
    """One event as a line of English-ish text. No interpretation."""
    parts = []
    for key, value in event.items():
        if key in {"seq", "at", "t", "kind", "area", "area_name"}:
            continue
        if isinstance(value, dict) and "world" in value:
            parts.append(f"{key}={_place(value)}")
        elif isinstance(value, dict):
            inner = " ".join(f"{k}={v}" for k, v in value.items())
            parts.append(f"{key}[{inner}]")
        else:
            parts.append(f"{key}={value}")
    return "  ".join(parts)


def render(events: list[dict], *, collapse: bool = True) -> list[str]:
    """The human timeline. Consecutive identical events fold into one
    line carrying a count and the span they covered."""
    lines: list[str] = []
    index = 0
    while index < len(events):
        event = events[index]
        run_length = 1
        if collapse:
            key = _collapse_key(event)
            while (
                index + run_length < len(events)
                and _collapse_key(events[index + run_length]) == key
            ):
                run_length += 1
        last = events[index + run_length - 1]
        stamp = str(event.get("at", ""))[11:23] or "?"
        head = f"[t+{event.get('t', 0):8.2f}] {stamp}  {event.get('kind', '?')}"
        area = event.get("area_name") or event.get("area")
        if area is not None:
            head += f"  ({area})"
        body = describe_event(event)
        if run_length > 1:
            span = float(last.get("t", 0)) - float(event.get("t", 0))
            body += f"   [x{run_length} over {span:.1f}s]"
        lines.append(f"{head}  {body}".rstrip())
        index += run_length
    return lines


def summarize(events: list[dict]) -> list[str]:
    """The footer: duration, ticks, timing, event counts, areas visited."""
    if not events:
        return ["(no events)"]
    duration = float(events[-1].get("t", 0))
    counts: dict[str, int] = {}
    for event in events:
        counts[event.get("kind", "?")] = counts.get(event.get("kind", "?"), 0) + 1
    ticks = [e for e in events if e.get("kind") == "tick"]
    lines = [
        "",
        "SUMMARY",
        f"  duration      {duration:.1f}s over {len(events)} event(s)",
    ]
    if ticks:
        durations = [float(t.get("dur_s", 0)) for t in ticks]
        lines.append(
            f"  ticks         {len(ticks)}  "
            f"mean {sum(durations)/len(durations):.3f}s  "
            f"max {max(durations):.3f}s"
        )
    # Time per area: the question "where did the run spend itself" is
    # the first one anybody asks of a slow run.
    spent: dict[str, float] = {}
    for before, after in zip(events, events[1:], strict=False):
        name = str(before.get("area_name") or before.get("area") or "?")
        spent[name] = spent.get(name, 0.0) + (
            float(after.get("t", 0)) - float(before.get("t", 0))
        )
    lines.append("  areas")
    for name, seconds in sorted(spent.items(), key=lambda kv: -kv[1]):
        lines.append(f"      {name:<28} {seconds:8.1f}s")
    lines.append("  events by kind")
    for kind, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"      {kind:<28} {count:6d}")
    return lines


def _world(field) -> tuple | None:
    """The world coordinate out of a three-frame spatial field."""
    if isinstance(field, dict):
        got = field.get("world")
        return tuple(got) if got else None
    if isinstance(field, (list, tuple)):
        return tuple(field)
    return None


def pickup_report(events: list[dict]) -> list[str]:
    """The pickup census: what the pickit wanted, and what we actually got.

    Written because answering "were any whitelisted items not picked up"
    on 2026-08-06 took a throwaway correlation script — eleven of that
    run's thirteen misses emitted no event at all, so the only honest
    census was `action.pickup_attempt` joined to `item.collected` by
    unit id. That join belongs in the tool, not in a script somebody has
    to rewrite each time.

    Deliberately derives from the ATTEMPT stream rather than from
    `item.dropped`: a click is proof the pickit wanted the item, and the
    report has to work on logs written before the newer events existed
    (the baseline run is one). Fields that are absent are reported as
    absent — the log's honest-absence rule — never defaulted to zero.
    """
    attempts: dict = {}
    for e in events:
        if e.get("kind") != "action.pickup_attempt":
            continue
        uid = e.get("unit_id")
        row = attempts.setdefault(uid, {
            "item": e.get("item"), "area": e.get("area_name"),
            "pos": _world(e.get("target")), "clicks": 0,
        })
        row["clicks"] += 1
    collected = {
        e.get("unit_id"): e for e in events if e.get("kind") == "item.collected"
    }
    abandoned = {
        e.get("unit_id"): e for e in events if e.get("kind") == "item.abandoned"
    }
    if not attempts:
        return ["PICKUP  no pickup attempts in this log"]

    got = [u for u in attempts if u in collected]
    lines = [
        f"PICKUP  {len(got)}/{len(attempts)} collected "
        f"({100 * len(got) // len(attempts)}%)"
    ]

    by_area: dict = {}
    for uid, row in attempts.items():
        hit, total = by_area.setdefault(row["area"], [0, 0])
        by_area[row["area"]] = [hit + (1 if uid in collected else 0), total + 1]
    lines.append("  by floor")
    for area, (hit, total) in by_area.items():
        lines.append(f"    {str(area):<24} {hit}/{total}")

    missed = [(u, r) for u, r in attempts.items() if u not in collected]
    if missed:
        lines.append(f"  MISSED ({len(missed)})")
        for uid, row in missed:
            gave = abandoned.get(uid) or {}
            reason = gave.get("reason", "no write-off event")
            near = gave.get("neighbours")
            near = f"{near} neighbour(s)" if near is not None else "neighbours unknown"
            lines.append(
                f"    {str(row['item']):<18} {str(row['pos']):<18} "
                f"{str(row['area']):<22} {row['clicks']:>2} clicks  "
                f"{near:<20} -> {reason}"
            )
    else:
        lines.append("  MISSED (0) — everything attempted came up")

    histogram: dict = {}
    for row in attempts.values():
        histogram[row["clicks"]] = histogram.get(row["clicks"], 0) + 1
    lines.append(
        "  attempts histogram: "
        + " ".join(f"{k}:{histogram[k]}" for k in sorted(histogram))
    )
    # The bimodality is the finding that says "systematic, not flaky",
    # so the report states it rather than leaving it to be re-noticed.
    quick = sum(n for c, n in histogram.items() if c <= 2)
    lines.append(
        f"  {quick} item(s) took <=2 clicks; "
        f"{sum(n for c, n in histogram.items() if c >= 8)} spent 8 or more"
    )
    stolen = [
        e for e in collected.values() if e.get("attributed_to") is not None
    ]
    if stolen:
        # The "clicked A, got B" rate, as a standing number rather than a
        # forensic finding. Every one of these is a click that spent
        # itself on the wrong item while its real target stayed put.
        lines.append(f"  CLICKED-THE-NEIGHBOUR ({len(stolen)})")
        for e in stolen:
            lines.append(
                f"    {str(e.get('item')):<18} came up from a click aimed at "
                f"unit {e.get('attributed_to')} at {e.get('attributed_aim')}"
            )
    stray = [u for u in collected if u not in attempts]
    if stray:
        lines.append(
            f"  NOTE: {len(stray)} item(s) came up with no attempt recorded "
            "(picked up by a click aimed at something else, or before "
            "attempt logging began)"
        )
    return lines


_BLOCK_NAMES = {"A": "NO NAME TAGS", "B": "LOOT FILTER TAGS",
                "C": "DEFAULT TAGS"}


def tagmode_report(events: list[dict]) -> list[str]:
    """The tag-mode battery table (R248/R250): accuracy and speed per mode.

    Rounds are windowed by the battery's own `battery.round` boundary
    events (stage test_start/test_end); the per-item evidence inside a
    window is the ordinary item stream. Wantedness is judged by the
    `wanted_kinds` list the round's test_start recorded — kind-based on
    purpose, because ground unit ids churn. Absent boundaries are
    reported as absent (a crash mid-round leaves an unclosed window);
    nothing is defaulted to zero.
    """
    rounds: list[dict] = []
    open_round: dict | None = None
    for e in events:
        kind = e.get("kind")
        if kind == "battery.round" and e.get("stage") == "test_start":
            open_round = {
                "block": e.get("block"), "round_no": e.get("round_no"),
                "mode": e.get("mode"),
                "start_t": float(e.get("t", 0)),
                "wanted_start": e.get("wanted_on_ground"),
                "junk_start": e.get("junk_on_ground"),
                "wanted_kinds": set(e.get("wanted_kinds") or []),
                "collected_seen": 0, "junk_collected_seen": 0,
                "attempts": 0, "abandoned": 0, "last_wanted_t": None,
            }
            rounds.append(open_round)
        elif kind == "battery.round" and e.get("stage") == "test_end":
            if open_round is not None:
                open_round["elapsed_s"] = e.get("elapsed_s")
                open_round["timed_out"] = e.get("timed_out")
                open_round["collected"] = e.get("collected")
                open_round["wanted_left"] = e.get("wanted_left")
                open_round["resolving"] = e.get("resolving")
                open_round["junk_collected"] = e.get("junk_collected")
                open_round = None
        elif open_round is not None:
            if kind == "item.collected":
                if e.get("item_kind") in open_round["wanted_kinds"]:
                    open_round["collected_seen"] += 1
                    open_round["last_wanted_t"] = float(e.get("t", 0))
                else:
                    open_round["junk_collected_seen"] += 1
            elif kind == "action.pickup_attempt":
                open_round["attempts"] += 1
            elif kind == "item.abandoned":
                open_round["abandoned"] += 1
    if not rounds:
        return ["TAGMODE  no battery rounds in this log"]

    lines = ["TAGMODE  per round"]
    lines.append(
        f"    {'round':<7}{'mode':<6}{'wanted':<8}{'got':<5}{'left':<6}"
        f"{'time_s':<8}{'to_last':<9}{'junk+':<7}{'clicks':<8}{'gave up':<8}"
    )
    by_mode: dict = {}
    for r in rounds:
        complete = "elapsed_s" in r
        label = f"{r['round_no']}{r['block']}"
        to_last = (
            f"{r['last_wanted_t'] - r['start_t']:.1f}"
            if r["last_wanted_t"] is not None else "-"
        )
        time_s = f"{r['elapsed_s']:.1f}" if complete else "OPEN"
        flag = " TIMEOUT" if complete and r.get("timed_out") else ""
        if r.get("resolving"):
            flag += f" +{r['resolving']} resolving"
        got = r.get("collected")
        got = r["collected_seen"] if got is None else got
        junk = r.get("junk_collected")
        junk = r["junk_collected_seen"] if junk is None else junk
        lines.append(
            f"    {label:<7}{str(r['mode']):<6}"
            f"{str(r['wanted_start']):<8}{got:<5}"
            f"{str(r.get('wanted_left', '?')):<6}{time_s:<8}{to_last:<9}"
            f"{str(junk):<7}{r['attempts']:<8}{r['abandoned']:<8}{flag}"
        )
        if complete:
            by_mode.setdefault((r["mode"], r["block"]), []).append(r)
    lines.append("  per mode (complete rounds only)")
    for mode, block in sorted(by_mode):
        rows = by_mode[(mode, block)]
        wanted = sum(r["wanted_start"] or 0 for r in rows)
        got = sum(
            r["collected"] if r.get("collected") is not None
            else r["collected_seen"]
            for r in rows
        )
        mean_t = sum(float(r["elapsed_s"]) for r in rows) / len(rows)
        junk = sum(
            r["junk_collected"]
            if r.get("junk_collected") is not None
            else r["junk_collected_seen"]
            for r in rows
        )
        timeouts = sum(1 for r in rows if r.get("timed_out"))
        pct = f"{100 * got // wanted}%" if wanted else "n/a"
        name = _BLOCK_NAMES.get(block, "?")
        lines.append(
            f"    {block} ({name}): {len(rows)} round(s)  "
            f"accuracy {got}/{wanted} ({pct})  "
            f"mean time {mean_t:.1f}s  junk picked {junk}  "
            f"timeouts {timeouts}"
        )
    consumed = [e for e in events if e.get("kind") == "battery.consumed"]
    if consumed:
        lines.append(
            f"  CONSUMED BY SLIPPED CLICKS ({len(consumed)}): "
            + "; ".join(
                f"kind {e.get('item_kind')} in round "
                f"{e.get('round_no')}{e.get('block')}"
                for e in consumed
            )
        )
    losses = [e for e in events if e.get("kind") == "battery.loss"]
    for e in losses:
        lines.append(
            f"  LOSS  round {e.get('round_no')}{e.get('block')} "
            f"missing {e.get('missing')}"
        )
    end = next(
        (e for e in reversed(events) if e.get("kind") == "battery.end"), None
    )
    if end is None:
        lines.append("  NOTE: no battery.end — the battery did not close")
    elif not end.get("completed"):
        lines.append(f"  NOTE: battery stopped early — {end.get('why')}")
    return lines


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    """`python -m pd2bot.runlog [run-dir] [--kind P] [--since S] [--raw]`"""
    import argparse

    parser = argparse.ArgumentParser(description="Render a run event log.")
    parser.add_argument("run", nargs="?", help="run directory (default: latest)")
    parser.add_argument("--kind", help="only kinds with this prefix")
    parser.add_argument("--since", type=float, help="only events at/after t")
    parser.add_argument("--until", type=float, help="only events at/before t")
    parser.add_argument("--raw", action="store_true", help="pass JSON through")
    parser.add_argument(
        "--no-collapse", action="store_true", help="one line per event"
    )
    parser.add_argument(
        "--pickup", action="store_true",
        help="the pickup census: wanted vs collected, and why not",
    )
    parser.add_argument(
        "--tagmode", action="store_true",
        help="the tag-mode battery table (R248): accuracy/speed per mode",
    )
    args = parser.parse_args(argv)

    run = Path(args.run) if args.run else latest_run()
    if run is None:
        print("no runs found under logs/runs/", flush=True)
        return 1
    events = load(run)
    if args.kind:
        events = [e for e in events if str(e.get("kind", "")).startswith(args.kind)]
    if args.since is not None:
        events = [e for e in events if float(e.get("t", 0)) >= args.since]
    if args.until is not None:
        events = [e for e in events if float(e.get("t", 0)) <= args.until]

    print(f"# {run}", flush=True)
    if args.pickup:
        for line in pickup_report(events):
            print(line, flush=True)
        return 0
    if args.tagmode:
        for line in tagmode_report(events):
            print(line, flush=True)
        return 0
    if args.raw:
        for event in events:
            print(json.dumps(event, default=str), flush=True)
    else:
        for line in render(events, collapse=not args.no_collapse):
            print(line, flush=True)
        for line in summarize(events):
            print(line, flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
