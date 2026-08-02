"""The narrative log (R179): broad actions, wall-clock stamped, in English.

The ask, in the user's words: a human-readable per-run log of the BROAD
actions, where apparent idleness is visible and explicable — "the bot runs
up to an NPC, then dawdles for several seconds; I'm curious what it's
doing." The dawdle is verification polling and settle timers, and the fix
is not to remove it but to make it say so.

**The coarseness contract.** One line per meaningful act: step
transitions, each preamble station with its duration and what was
verified, waypoint travel, fight and clearance summaries (on completion,
not per swing), pickups, the cleanse, write-offs, and the run summary.
Waits narrate on COMPLETION, with the duration and what was being waited
for — "heal: vitals read full (3.8s)" is the whole point of the channel.
If a line could fire more than about once a second it belongs in the
micro-log (`RunServices.log` / `PreambleReport.log`), not here: the
narrative log's value IS its sparseness. Every `narrate` call site is an
editorial decision, not a mirror of the micro-log.

One `Narrator` is built per run (wiring), writing to
`logs/run-<YYYYMMDD-HHMMSS>.log` — gitignored, machine-local — and
echoing to stdout prefixed `»` so it stands apart from the micro-log's
indented lines. The consumers (`RunServices.narrate`, the engine, the
town layer) hold only a `narrate(text)` callable that defaults to a
no-op, so tests and drills stay silent unless they opt in.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path


def noop(text: str) -> None:
    """The default narrate: nowhere. Consumers hold a callable, not a
    Narrator, precisely so silence costs nothing to express."""


def _default_echo(line: str) -> None:  # pragma: no cover - console only
    print(f"» {line}", flush=True)


class Narrator:
    """Writes the per-run narrative file, one stamped line at a time.

    The file is named at construction (the run's wall-clock start) but
    created on the FIRST line — a run that never narrates leaves nothing
    behind. Lines are appended and flushed per call: the file's whole job
    is to be readable while the bot is running, and after a crash.
    """

    def __init__(
        self,
        directory: str | Path = "logs",
        *,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], time.struct_time] = time.localtime,
        echo: Callable[[str], None] = _default_echo,
    ) -> None:
        self._clock = clock  # durations (monotonic; injectable for tests)
        self._wall = wall  # stamps (wall clock; what a human reads)
        self._echo = echo
        stamp = time.strftime("%Y%m%d-%H%M%S", wall())
        self.path = Path(directory) / f"run-{stamp}.log"

    def narrate(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S", self._wall())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp}  {text}\n")
        self._echo(text)

    @contextmanager
    def span(self, label: str):
        """A wait that will explain itself: narrates ONE completion line
        with the duration. The body reports how it ended through the
        yielded callable — `done("verified", "vitals read full")` becomes
        `heal: verified after 3.8s (vitals read full)`. A body that
        raises still narrates (`FAILED after ...`), because the dawdle a
        human asks about is most often the one that ended badly."""
        started = self._clock()
        outcome = {"text": "done", "detail": None}

        def done(text: str, detail: str | None = None) -> None:
            outcome["text"] = text
            outcome["detail"] = detail

        try:
            yield done
        except BaseException as exc:
            elapsed = self._clock() - started
            self.narrate(
                f"{label}: FAILED after {elapsed:.1f}s ({type(exc).__name__})"
            )
            raise
        elapsed = self._clock() - started
        detail = outcome["detail"]
        self.narrate(
            f"{label}: {outcome['text']} after {elapsed:.1f}s"
            + (f" ({detail})" if detail else "")
        )
