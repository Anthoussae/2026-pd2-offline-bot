# Handoff — paste this into a fresh conversation

Everything below is self-contained. The repo is clean and pushed at
`91d960b` on `m5-trial-run`.

---

> Continuing the PD2 offline bot, milestone M5, phase P6 (staged live
> acceptance). Read `docs/plans/2026-07-29-m5-trial-run/RESUME.md` first,
> then `docs/reviews/2026-07-31-m5-stage-b/summary.md`.
>
> Yesterday was a long supervised session: nine live stage-B attempts, the
> full Cold Plains run completed twice, and it fought once. It also
> produced enough self-inflicted regressions that we stopped and ran a
> review rather than push for another run.
>
> **Start with review finding 001 (P1).** The combat repositioning added
> at the very end of the session has never executed against the game, and
> it can drift the player out of `engage_radius` while `clear_radius`
> still wants those monsters dead — after which the step reports
> `waiting=True` forever and `waiting` suppresses the idle watchdog. A
> permanent hang with the alarm switched off on that exact path. Do not
> run unattended until it is fixed.
>
> Then findings 002 and 003 (both P2, both in the same never-run band),
> then the unexplained `SkillSwitchFailed` — `drills/t47_hotkey_audit.py`
> is written and unrun and settles it in about 30 seconds.
>
> Live runs need the elevated bridge; I start it, you drive it. Ask before
> anything that sends input to the game — I need to be at the machine
> watching, hands near the controls.
>
> Instruction-log IDs continue from R149.

---

## Context a new session most needs

**How live work happens.** I start the bridge once per session:

```
powershell -ExecutionPolicy Bypass -File "C:\dev\2026-pd2-bot\2026-pd2-offline-bot\tools\elevated-bridge.ps1"
```

You then drop `<id>.cmd.ps1` into `%LOCALAPPDATA%\pd2bot-bridge` and read
`<id>.out.txt` back. You can run read-only probes freely; anything that
sends input needs me watching, because the abort paths are physical
(take the mouse, or ESC).

**Run the bot:**

```
python -m pd2bot.wiring --games 1 --chicken 50 --run runs/cold-plains-stage-b.toml
```

Add `--dry-run` to assemble and print everything without sending. Python
is `~/.venvs/pd2bot/Scripts/python.exe` — bare `python` is a broken 3.8.

**Validation:** `python -m pytest -q` (666 pass) and `python -m ruff
check .` (clean).

## What I care about, learned the expensive way

- **Measure, do not guess.** Every good fix yesterday came from a live
  read; several bad ones came from a plausible theory. When a hypothesis
  and a probe are both available, run the probe — it was decisive five
  times and the guesses were wrong three times.
- **Tell me plainly when something failed**, including when the fix was
  the thing that broke it. Three of yesterday's failures were regressions
  from earlier in the same session, and saying so promptly is what kept
  it tractable.
- **Do not stack speculative changes.** If a fix has not run live, say so
  when reporting the next result.
- The user-request protocol (`🔶 R<n> [type]`, logged in
  `docs/instruction-log.md`) is in `~/.claude/CLAUDE.md`; keep using it.

## The three live theories still open

1. **`SkillSwitchFailed`** — the right skill slot stays on whatever was
   last selected. Three runs, three different skill pairs. Either the
   bindings differ from `config/necro.toml`, or the keypress is not
   landing. T47 separates them.
2. **Bone armor's cast animation** (my observation from manual play):
   commands sent straight after the cast interrupt it, so the buff never
   lands and it looks like a recast loop. Finding 002 says the current
   0.4 s fixed settle is the wrong shape — wait on the effect instead;
   the armor stat is readable and T46 characterised it.
3. **The town "dithering"** — finding 003 argues it is ~1200 stat reads
   per potion moved, and that halving `poll_s` made it worse rather than
   better.

## Deliberately not done

- **Patrol.** I asked for a wider sweep around the waypoint; the honest
  answer is that `clear_radius` does not patrol at all, and adding one is
  a new feature that P6 puts out of scope. Needs a decision, not a quiet
  implementation.
- **The unclean exit** — leaving sometimes ends on an unrecognized menu
  screen (`[CV--]`). M4's cycle, not the run.
- **R115** — should `IdleBail` share the cycle's chicken counter? Now the
  same shape as `StashFullHalt`/`TownStepHalt`; decide them together.
