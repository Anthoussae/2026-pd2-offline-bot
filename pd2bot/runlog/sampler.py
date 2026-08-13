"""A sampling stack watcher: what is the main thread DOING, second by second?

Born from T87 (2026-08-13): the bot ran to the waypoint in ~1.7 s, then
stood visibly idle for ~15 s before clicking it — the operator watched it
happen — and NOTHING in the event log accounted for the gap. The stall
lived between instruments, and every timer added afterward only narrowed
the window without naming the line. The operator's requirement, stated
outright: an instrument that watches the CODE, so that a silent stall
anywhere — town, Cold Plains, the Countess descent — attributes itself.

Design: a daemon thread samples the main thread's stack every
`interval_s` via `sys._current_frames()` — cheap (microseconds), no
tracing hooks, no dependencies, no cooperation needed from the code
being watched. Consecutive identical stacks are span-compressed into one
line:

    03:47:55.113  +15.10s  chat.py:88:read_lines < channel.py:41:...

Only spans of `min_span_s` or longer are written, so busy churn costs
nothing on disk and a stall of any length is always on the record.

Always on in the real launcher (the run log's rule 5: optional
instrumentation means the run you most need to explain is the one where
the flag was forgotten). Drills, sims and tests never construct one.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

# Sampling faster buys resolution the spans do not need; slower risks
# missing a short stall between samples. 50 ms resolves anything a human
# could notice, at ~20 stack walks a second.
DEFAULT_INTERVAL_S = 0.05
# Spans shorter than this are churn, not stalls; dropping them is what
# keeps a whole run's sample file readable in one screenful.
DEFAULT_MIN_SPAN_S = 0.25
# Innermost frames carry the diagnosis; outer frames carry the context.
SIGNATURE_DEPTH = 12


def stack_signature(frame, depth: int = SIGNATURE_DEPTH) -> str:
    """One line for a stack: innermost first, `file.py:line:function`."""
    parts = []
    while frame is not None and len(parts) < depth:
        code = frame.f_code
        parts.append(
            f"{Path(code.co_filename).name}:{frame.f_lineno}:{code.co_name}"
        )
        frame = frame.f_back
    return " < ".join(parts)


class SpanWriter:
    """Span compression, pure: fed (t, wall, signature) samples in order,
    emits (wall_of_span_start, duration, signature) for every run of
    identical signatures at least `min_span_s` long."""

    def __init__(
        self,
        emit: Callable[[float, float, str], None],
        min_span_s: float = DEFAULT_MIN_SPAN_S,
    ) -> None:
        self._emit = emit
        self._min = min_span_s
        self._sig: str | None = None
        self._since: float = 0.0
        self._since_wall: float = 0.0
        self._last: float = 0.0

    def sample(self, t: float, wall: float, sig: str) -> None:
        if sig != self._sig:
            self._flush(end=t)
            self._sig, self._since, self._since_wall = sig, t, wall
        self._last = t

    def _flush(self, end: float) -> None:
        if self._sig is not None and end - self._since >= self._min:
            self._emit(self._since_wall, end - self._since, self._sig)

    def close(self) -> None:
        """Flush the open span as if one more different sample arrived."""
        self._flush(end=self._last)
        self._sig = None


class StackSampler(threading.Thread):
    """The watcher thread. `start()` it, `stop()` it; it never raises into
    the program it watches, and dying silently costs diagnosis, never
    correctness."""

    def __init__(
        self,
        path: str | Path,
        *,
        interval_s: float = DEFAULT_INTERVAL_S,
        min_span_s: float = DEFAULT_MIN_SPAN_S,
    ) -> None:
        super().__init__(daemon=True, name="pd2bot-stack-sampler")
        self._path = Path(path)
        self._interval = interval_s
        self._target = threading.main_thread().ident
        self._halt = threading.Event()
        self._writer = SpanWriter(self._emit, min_span_s)
        self._fh = None

    def _emit(self, wall: float, duration: float, sig: str) -> None:
        stamp = time.strftime("%H:%M:%S", time.localtime(wall))
        line = f"{stamp}.{int(wall % 1 * 1000):03d}  +{duration:7.2f}s  {sig}\n"
        try:
            self._fh.write(line)
            self._fh.flush()
        except Exception:  # noqa: BLE001 - the watcher must not wound the watched
            pass

    def run(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self._path, "a", encoding="utf-8")
            self._fh.write(
                f"# stack samples, main thread, every {self._interval}s; "
                f"spans >= {self._writer._min}s; started "
                f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
        except Exception:  # noqa: BLE001
            return
        while not self._halt.wait(self._interval):
            frame = sys._current_frames().get(self._target)
            if frame is None:
                continue
            try:
                sig = stack_signature(frame)
            finally:
                del frame  # never hold a frame reference across samples
            self._writer.sample(time.monotonic(), time.time(), sig)
        self._writer.close()
        try:
            self._fh.close()
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> None:
        self._halt.set()
        self.join(timeout=2.0)
