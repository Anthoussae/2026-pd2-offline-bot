"""T40 — where does text the USER types into the chat line live in memory?

The bot can talk (M4's `pd2bot.chat`) and the user cannot answer. The one
thing the bot already knows about the user's typing is the *envelope*: UI
slot 0x05 (UI_CHAT_CONSOLE) goes 1 the moment Enter opens the chat line and
0 when it is posted or cancelled, which is exactly the flag chat.py checks
before it types. So "you opened chat, typed for a while, and submitted
something" is readable today. The words are not: BH exports no chat buffer
(it runs in-process and never needed one), so there is no offset to cite and
no function whose code can be parsed for it.

This drill goes and finds one. The user types a rare marker, the whole
committed address space is searched for it, and the round is repeated with a
SECOND marker to separate a real address from a coincidence — an address
that carries marker 1 and then carries marker 2 is the buffer; an address
that only ever matched once is noise.

Two different targets are worth finding and the protocol catches both:

    the EDIT BUFFER   — holds the line while it is being typed, and is
                        probably cleared on Enter. Reading it means racing
                        the user's Enter key.
    the SCROLLBACK    — holds the message after it is posted. Better: it
                        can be read lazily, long after the fact, and it
                        distinguishes a posted line from an ESC-cancelled
                        one, which the edit buffer never can.

So each round scans TWICE — once with the line open, once after it is
posted — and reports which addresses survived the post.

The self-check comes first and the drill fails hard without it. A scan that
silently reads nothing would report "the chat text is not in memory", which
is a conclusion about the GAME drawn from a bug in the INSTRUMENT — the most
expensive kind of wrong answer this project has paid for (see the T17 note in
offsets.py). So before any marker is scanned for, the character's own name is
scanned for: it is known to be in memory at a cited offset, so finding it
proves the scanner reaches real data, and not finding it means stop.

Read-only: the bot sends nothing but its own chat messages.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t40_chat_read_scan
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.player import read_player  # noqa: E402

# Lowercase letters and digits only: no shift, no punctuation, nothing a
# keyboard layout could turn into a different character than the one we
# search for. Rare enough that a false positive anywhere in a 32-bit address
# space would be remarkable.
MARKERS = ("qzmarker71", "qzmarker42")
MARKER_PREFIX = "qzmarker"  # the typo fallback (see _scan)

# How long to let the user finish typing before the with-the-line-open scan.
# The bot CANNOT talk during this window — chat refuses while the console is
# open (it is a blocking panel) — so the round is on a clock, and the clock
# is generous.
TYPE_DWELL_S = 12.0
OPEN_TIMEOUT_S = 300.0
POST_TIMEOUT_S = 240.0
CONTEXT_BYTES = 48
MAX_REPORTED = 12

ENCODINGS = ("ascii", "utf16")


def _needle(marker: str, encoding: str) -> bytes:
    return marker.encode("ascii") if encoding == "ascii" else marker.encode("utf-16-le")


def _scan(run: DrillRun, marker: str, label: str) -> dict[str, list[int]]:
    """Scan for `marker` in both encodings; report timing and fall back to
    the prefix if nothing matched (a mistyped marker and an absent buffer
    look identical otherwise, and they call for opposite next steps)."""
    hits: dict[str, list[int]] = {}
    for encoding in ENCODINGS:
        started = time.monotonic()
        found = run.session.search(_needle(marker, encoding))
        elapsed = time.monotonic() - started
        hits[encoding] = found
        print(
            f"  [{label}] {marker!r} as {encoding}: {len(found)} hit(s) "
            f"in {elapsed:.1f}s",
            flush=True,
        )
    if not any(hits.values()):
        for encoding in ENCODINGS:
            partial = run.session.search(_needle(MARKER_PREFIX, encoding))
            if partial:
                print(
                    f"  [{label}] NOTE: the prefix {MARKER_PREFIX!r} matched "
                    f"{len(partial)} time(s) as {encoding} — the marker was "
                    "probably mistyped, not absent",
                    flush=True,
                )
    return hits


def _dump(run: DrillRun, address: int, modules) -> str:
    """What sits around a hit — the difference between an address and a
    finding. A scrollback line is preceded by the sender's name; a bare edit
    buffer is not."""
    try:
        start = max(0, address - CONTEXT_BYTES // 2)
        raw = run.session.raw(start, CONTEXT_BYTES)
    except Exception as exc:
        return f"{run.session.describe(address, modules)} (unreadable: {exc})"
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in raw)
    return f"{run.session.describe(address, modules)}  |{printable}|"


def _round(
    run: DrillRun,
    marker: str,
    index: int,
    modules,
    hold_s: float,
) -> dict[str, dict[str, list[int]]]:
    """One marker, start to finish: open scan, post scan."""
    run.say(f"ROUND {index}: press Enter and type exactly:  {marker}")
    run.say(
        f"Then WAIT about {int(hold_s)}s with the line still open — I cannot "
        "talk while your chat line is up, and I am scanning during it."
    )
    run.say("Then press Enter to post it. I speak again when the round ends.")

    if not run.wait_until(
        lambda: run.panel_open(offsets.UI_CHAT_CONSOLE), timeout_s=OPEN_TIMEOUT_S
    ):
        raise RuntimeError(f"round {index}: the chat line never opened")

    run.sleep(TYPE_DWELL_S)
    open_before = run.panel_open(offsets.UI_CHAT_CONSOLE)
    open_hits = _scan(run, marker, f"round {index} open")
    open_after = run.panel_open(offsets.UI_CHAT_CONSOLE)
    if not (open_before and open_after):
        # Not a failure — the scan still ran, it just ran against a posted
        # line rather than a live one, and a result read as "edit buffer"
        # would be wrong. Say so rather than quietly mislabelling it.
        print(
            f"  [round {index}] the line was NOT open across the whole scan "
            f"(before={open_before} after={open_after}) — treat these hits as "
            "post-submit, not edit-buffer",
            flush=True,
        )

    if not run.wait_until(
        lambda: not run.panel_open(offsets.UI_CHAT_CONSOLE), timeout_s=POST_TIMEOUT_S
    ):
        raise RuntimeError(f"round {index}: the chat line never closed")
    run.sleep(1.0)
    post_hits = _scan(run, marker, f"round {index} posted")

    for encoding in ENCODINGS:
        for address in (open_hits[encoding] + post_hits[encoding])[:MAX_REPORTED]:
            print(f"    {encoding}: {_dump(run, address, modules)}", flush=True)

    run.say(
        f"Round {index} done — {sum(len(v) for v in open_hits.values())} hit(s) "
        f"while open, {sum(len(v) for v in post_hits.values())} after posting."
    )
    return {"open": open_hits, "posted": post_hits}


def _holds(run: DrillRun, address: int, marker: str, encoding: str) -> bool:
    """Does this exact address carry this marker right now?"""
    needle = _needle(marker, encoding)
    try:
        return run.session.raw(address, len(needle)) == needle
    except Exception:
        return False


T40 = Drill(
    test_id="T40",
    title="Where the user's typed chat line lives in memory",
    kind="human calibration",
    instructions=(
        "SETUP: in a game, in town, all panels closed. You drive; I only read.",
        "Two rounds. Each: open chat, type a marker I give you, wait, post it.",
        "Type the marker EXACTLY - it is what I search memory for.",
        "Nothing is at risk: this drill sends no keys and no clicks.",
    ),
    sends_input=False,
)


def t40_body(run: DrillRun) -> str:
    session = run.session
    modules = session.modules()

    # -- self-check: prove the scanner before trusting any negative result --
    player = read_player(session)
    if player is None or not player.name:
        raise RuntimeError("cannot read the character name — not in a game?")
    started = time.monotonic()
    name_hits = session.search(player.name.encode("ascii"))
    scan_seconds = time.monotonic() - started
    regions = len(session.regions())
    print(
        f"self-check: {regions} readable regions; the character name "
        f"{player.name!r} found {len(name_hits)} time(s) in {scan_seconds:.1f}s",
        flush=True,
    )
    if not name_hits:
        raise RuntimeError(
            "SCANNER IS BLIND — the character name is at a cited offset and "
            "must be findable. Every 'not found' below would be meaningless, "
            "so the drill stops here rather than producing a false negative"
        )
    # How long the user must hold the line open: the typing dwell, plus BOTH
    # encoding passes, plus a typo-fallback pass that only runs when nothing
    # matched — the case where holding still matters most. Measured, not
    # guessed: a hardcoded window is what stranded two earlier drills, and
    # here it would silently turn an edit-buffer reading into a posted one.
    hold_s = TYPE_DWELL_S + 3 * scan_seconds + 5

    rounds = [
        _round(run, MARKERS[0], 1, modules, hold_s),
        _round(run, MARKERS[1], 2, modules, hold_s),
    ]

    # -- the decisive test: does a round-1 address now carry marker 2? ------
    #
    # Two independent ways of saying the same thing, because they fail
    # differently: intersecting the two scans finds addresses that matched
    # both markers, while re-reading round 1's addresses catches a buffer
    # that moved contents without moving itself.
    stable: list[tuple[str, str, int]] = []
    for state in ("open", "posted"):
        for encoding in ENCODINGS:
            for address in rounds[0][state][encoding]:
                if _holds(run, address, MARKERS[1], encoding) or address in rounds[1][
                    state
                ][encoding]:
                    stable.append((state, encoding, address))

    if not stable:
        totals = {
            f"r{i + 1}.{state}.{enc}": len(rounds[i][state][enc])
            for i in (0, 1)
            for state in ("open", "posted")
            for enc in ENCODINGS
        }
        found_any = any(totals.values())
        return (
            "NO STABLE ADDRESS — "
            + ("the markers were found but never twice at the same address, so "
               "the buffer is reallocated per message and needs a pointer chain"
               if found_any
               else "the markers were not in memory at all in either encoding")
            + f" ({totals}); scanner verified working ({len(name_hits)} name hits)"
        )

    lines = [f"{state}/{enc} {session.describe(addr, modules)}" for state, enc, addr in stable]
    for state, encoding, address in stable[:MAX_REPORTED]:
        print(f"  STABLE {state}/{encoding}: {_dump(run, address, modules)}", flush=True)

    in_module = [line for line in lines if "heap:" not in line]
    posted = [line for line in lines if line.startswith("posted")]
    return (
        f"FOUND {len(stable)} stable address(es): {'; '.join(lines[:6])}"
        f"{' ...' if len(lines) > 6 else ''}. "
        f"{len(posted)} survive posting (scrollback candidates); "
        f"{len(in_module)} sit inside a module (durable offset candidates)"
    )


SUITE = {"T40": (T40, t40_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T40"], run=shared)
    print(f"\nsuite: T40 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
