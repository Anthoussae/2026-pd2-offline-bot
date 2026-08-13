"""T91 — the "F" default-tags toggle: find its state flag in memory.

The R248 tag-mode battery needs to KNOW whether ground labels are
showing loot-filter styling or the game's default names, and the key
that flips them — "F", per the operator — is bound NOWHERE on disk:
the character keyfile has no entry carrying 0x46, BH.json's filter
hotkeys are all "None", and ProjectDiablo.cfg has no F row (R248 plan
discovery). A toggle you cannot read is a parity bug waiting to happen
(T66's exact argument for the ALT flag), so before the battery trusts
blind parity, this probe hunts the flag.

Protocol: T66's, verbatim, with key F — snapshot every module's
writable memory, press F, diff; then press three more times and keep
only the bytes that ALTERNATE in lockstep with the presses. Four
presses = the display ends in the state it started. Candidates are
reported as module+offset with both values, ready for offsets.py (the
expectation is BH.dll, beside BH_LABEL_DISPLAY; T66's flag was the
single alternating byte in 117 modules).

Found → add the constant to offsets.py, a reader beside
`label_display_on`, and wire `filter_state` in wiring.py; the battery
then verifies mode 3 by read. Not found → the battery's blind-parity
fallback stands (announced F presses with an abort window).

## How it ends

On its own after 4 F presses and the diffs (~1-2 minutes).
Abort: 'abort' in chat, tools\\drill-cancel.ps1, ESC, or take the mouse.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input.gated import GatedInput  # noqa: E402
from pd2bot.input.keys import VK_F  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402

CHUNK = 1 << 20
SETTLE_S = 0.4
MAX_REPORTED = 10

T91 = Drill(
    test_id="T91",
    title="F default-tags toggle — find the state flag in memory",
    kind="bot control",
    sends_input=True,
    menu_ok=True,  # the probe is its own gate: four inert key presses
    instructions=(
        "AUTONOMOUS: starts immediately. The bot presses F four times,",
        "diffing module memory between presses to find the default-tags",
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


def t91_body(run: DrillRun) -> str:
    session = run.session
    gated = GatedInput(session)
    modules = session.modules()
    print(f"diffing {len(modules)} module(s)", flush=True)

    snaps = [_snapshot(session, modules)]
    for press in range(4):
        run.check_cancel()
        gated.press_key(VK_F)
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
        f"TEST T91 done — {len(survivors)} alternating byte(s). Hands back.",
        patience_s=15.0,
    )
    if not survivors:
        raise RuntimeError(
            "no byte alternated with the F presses in any module — either "
            "F is not a toggle on this client (tell the battery to stay on "
            "blind parity) or the flag lives outside module memory"
        )
    return (
        f"{len(survivors)} alternating byte(s); top candidates: "
        + "; ".join(lines)
    )


if __name__ == "__main__":
    status = run_drill(T91, t91_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
