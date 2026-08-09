"""T66 — the ALT label toggle: find the state flag in memory.

**Autonomous** (R207 mandate). PD2's ALT toggles the ground-item label
display; the bot can press ALT (VK_MENU, verified T63) but cannot KNOW
the current state — and a toggle you cannot read is a parity bug waiting
to happen (press it once out of sync and every 'labels on' becomes
'labels off'). The user's directive: find the internal flag.

Protocol (the T22/T36 signal-hunt shape, applied to module memory):
snapshot every module's writable memory, press ALT, diff — then press
ALT three more times and keep only the addresses whose value ALTERNATES
in lockstep with the presses (frame counters and RNG state churn on
every read; only a real toggle flag flips exactly with the key). Four
presses = the display ends in the state it started. Reported as
module+offset with both values, ready for offsets.py.

## How it ends

On its own after 4 ALT presses and the diffs (~1-2 minutes).
Abort: 'abort' in chat, tools\\drill-cancel.ps1, ESC, or take the mouse.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import VK_MENU, GatedInput  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402

CHUNK = 1 << 20
SETTLE_S = 0.4
MAX_REPORTED = 10

T66 = Drill(
    test_id="T66",
    title="ALT label toggle — find the state flag in memory",
    kind="bot control",
    sends_input=True,
    menu_ok=True,  # autonomous campaign: gate waived
    instructions=(
        "AUTONOMOUS: starts immediately. The bot presses ALT four times,",
        "diffing module memory between presses to find the label-display",
        "flag. The display ends in the state it started. Hands off.",
        "Abort: 'abort' in chat, drill-cancel, ESC, or take the mouse.",
    ),
)


def _snapshot(session, modules) -> dict[str, bytes]:
    out = {}
    for m in modules:
        parts = []
        for off in range(0, m.size, CHUNK):
            size = min(CHUNK, m.size - off)
            try:
                parts.append(session.raw(m.base + off, size))
            except Exception:
                parts.append(b"\x00" * size)  # unreadable page: constant
        out[m.name] = b"".join(parts)
    return out


def t66_body(run: DrillRun) -> str:
    session = run.session
    gated = GatedInput(session)
    modules = session.modules()
    print(f"diffing {len(modules)} module(s)", flush=True)

    snaps = [_snapshot(session, modules)]
    for press in range(4):
        run.check_cancel()
        gated.press_key(VK_MENU)
        run.sleep(SETTLE_S)
        snaps.append(_snapshot(session, modules))
        print(f"press {press + 1}: snapshot taken", flush=True)

    # Candidates: bytes that differ between snap0 and snap1, and then
    # alternate exactly: s0==s2==s4 and s1==s3, with s0 != s1.
    survivors: list[tuple[str, int, int, int]] = []
    for name in snaps[0]:
        s0, s1, s2, s3, s4 = (snaps[i][name] for i in range(5))
        n = min(len(s0), len(s1), len(s2), len(s3), len(s4))
        for i in range(n):
            a, b = s0[i], s1[i]
            if a != b and s2[i] == a and s3[i] == b and s4[i] == a:
                survivors.append((name, i, a, b))
                if len(survivors) > 5000:
                    break
        if len(survivors) > 5000:
            break

    lines = [
        f"{name}+0x{off:x}: {a} <-> {b}"
        for name, off, a, b in survivors[:MAX_REPORTED]
    ]
    for line in lines:
        print(f"  FLAG candidate {line}", flush=True)
    run.say(
        f"TEST T66 done — {len(survivors)} alternating byte(s). Hands back.",
        patience_s=15.0,
    )
    if not survivors:
        raise RuntimeError(
            "no byte alternated with the ALT presses in any module — the "
            "flag lives outside module memory (heap hunt is the follow-up)"
        )
    return (
        f"{len(survivors)} alternating byte(s); top candidates: "
        + "; ".join(lines)
    )


if __name__ == "__main__":
    status = run_drill(T66, t66_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
