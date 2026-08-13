"""T88 — DEMONSTRATION: an unwanted NPC dialog is closed briskly.

A new test KIND (operator request, 2026-08-13): a demonstration stages a
known hazard on purpose, in front of the operator, and lets the bot's
own integrated machinery answer it — the operator just watches and
reports satisfaction. Nothing here is bespoke recovery: the closure under
demonstration is `_clear_stray_ui`, the exact call every town approach
and interact attempt makes when it finds something open that it did not
ask for (the user's own rule from 2026-08-01: close it immediately, move,
click elsewhere).

Six rounds: each of the three town NPCs twice. Each round deliberately
opens the NPC's dialog (the staged "wayward" dialog — deterministic,
where waiting for a genuine misclick would demonstrate patience instead),
holds it briefly so the operator can SEE it standing open, then invokes
the recovery and stamps the clock at every edge:

    opened_at -> recovery_started -> closed_at   (+ the closure duration)

The table prints at the end; every line also lands in the bridge's
out.txt, so the record survives the window closing.

    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t88_dialog_recovery_demo

Town only. Deliberate dialog clicks and ESC presses are the only input,
plus chat announcements. The game is left in a `finally`.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import offsets  # noqa: E402
from pd2bot.input.chat import Chat  # noqa: E402
from pd2bot.wiring import build_bot  # noqa: E402

CANCEL_FILE = Path(os.environ.get("LOCALAPPDATA", ".")) / "pd2bot-bridge" / "drill-cancel"

ROUNDS = [
    (offsets.NPC_AKARA, "Akara"),
    (offsets.NPC_KASHYA, "Kashya"),
    (offsets.NPC_CHARSI, "Charsi"),
] * 2
# Long enough for a human to register the dialog standing open; excluded
# from the closure measurement (the recovery clock starts when recovery
# is invoked, exactly as it would be on the bot's next action attempt).
SHOW_THE_DIALOG_S = 0.8
BETWEEN_ROUNDS_S = 1.5
# "Briskly", quantified: the ESC + verify loop should land well inside
# this; a round over it is reported as SLOW even if it closed.
BRISK_S = 2.0


def _stamp(wall: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(wall)) + f".{int(wall % 1 * 1000):03d}"


def main() -> int:
    if CANCEL_FILE.exists():
        # The watchdog-latch precedent: a leftover from a previous session
        # must not kill this one; clearing per-round would eat a real stop.
        CANCEL_FILE.unlink(missing_ok=True)
        print("note: cleared a stale drill-cancel file from a previous session")

    bot = build_bot(should_stop=CANCEL_FILE.exists)
    cycle = bot.cycle()
    town = bot.town
    chat = Chat(bot.session)

    if not town.menu.window.bring_to_foreground():
        print("could not focus the game window — refusing to send anything")
        return 1

    rows: list[dict] = []
    created = False
    try:
        print("creating a game...", flush=True)
        cycle.create_game()
        created = True
        chat.say(
            "T88 dialog-recovery demo: 6 rounds. Each opens an NPC dialog "
            "on purpose; the bot's own recovery closes it. Just watch."
        )
        for n, (kind, name) in enumerate(ROUNDS, start=1):
            chat.say(f"round {n}/{len(ROUNDS)}: opening {name}'s dialog")
            town.open_npc_dialog(kind, name)  # the wayward dialog, verified open
            opened = time.time()
            time.sleep(SHOW_THE_DIALOG_S)  # visibility only, not measured
            recovery_started = time.time()
            found = town._clear_stray_ui()
            closed = time.time()
            still_open = town._any_panel_open()
            duration = closed - recovery_started
            rows.append({
                "round": n, "npc": name,
                "opened": opened, "recovered": recovery_started,
                "closed": closed, "duration": duration,
                "found": found or "nothing reported",
                "ok": not still_open,
            })
            verdict = (
                f"closed in {duration:.2f}s"
                if not still_open
                else "STILL OPEN — recovery failed"
            )
            chat.say(f"round {n}: {verdict}")
            print(
                f"round {n}: {name:7s} opened {_stamp(opened)}  "
                f"recovery {_stamp(recovery_started)}  closed {_stamp(closed)}  "
                f"({duration:.2f}s) [{rows[-1]['found']}]",
                flush=True,
            )
            time.sleep(BETWEEN_ROUNDS_S)

        print("\n--- T88 summary: wayward dialog -> closure ---")
        print(
            f"{'round':>5}  {'npc':7s}  {'opened at':12s}  "
            f"{'closed at':12s}  {'closure':>7s}  verdict"
        )
        for r in rows:
            verdict = "ok" if r["ok"] else "FAILED"
            if r["ok"] and r["duration"] > BRISK_S:
                verdict = "ok but SLOW"
            print(
                f"{r['round']:>5}  {r['npc']:7s}  {_stamp(r['opened']):12s}  "
                f"{_stamp(r['closed']):12s}  {r['duration']:6.2f}s  {verdict}"
            )
        closures = [r["duration"] for r in rows if r["ok"]]
        if len(closures) == len(rows):
            print(
                f"\nVERDICT: {len(rows)}/{len(rows)} closed; slowest "
                f"{max(closures):.2f}s, mean "
                f"{sum(closures) / len(closures):.2f}s "
                f"(brisk = under {BRISK_S:.1f}s)"
            )
        else:
            failed = len(rows) - len(closures)
            print(f"\nVERDICT: {failed} round(s) FAILED to close — not brisk, not done")
        chat.say("T88 demo complete — back to the terminal")
    except Exception as exc:  # noqa: BLE001 - a drill reports, never explodes
        print(f"\nDRILL FAILED: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if created:
            try:
                print("\nleaving the game...", flush=True)
                cycle.leave_game()
                print("left cleanly")
            except Exception as exc:  # noqa: BLE001
                print(f"leave failed ({exc}) — a human should look")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
