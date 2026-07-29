# PD2 offline bot (from scratch)

A from-scratch Python bot for Project Diablo 2 on Windows, targeting the
user's **offline single-player** client (that scope is a design target,
not an enforced guard; PD2's online realm is not a target of this
project). Architecture: out-of-process memory reading (pymem; offsets
from PD2's open-source BH fork) + OS-level synthetic input; no
injection, no pixel-scraping. Deliverables: a working bot (poison dagger
necromancer — trial run: Cold Plains clearance; flagship: Countess), an
instruction manual (`docs/manual/`), and architecture documentation
(`docs/architecture/`). `kolbot/` is a stock, gitignored clone kept as a
*behavioral reference only* (never edited, never executed — it is
incompatible with PD2's 1.13c client; see the archived plan).

Active roadmap: `docs/plans/2026-07-28-bot-from-scratch/` — read its
`plan.md` and `notes.md` before non-trivial work. **M1 done** (perception
+ input proven); **M2 done** (the `pd2bot/` package: live game-state
snapshots — see `docs/architecture/perception.md` and the archived
`docs/archive/plans/2026-07-28-m2-perception-core/_DONE.md`). **M3 done** (navigation:
gated input, live collision, the explored-map atlas — SP maps are fixed
per character+difficulty, so the bot persists every room grid it reads —
A* + the walk loop; acceptance walk passed 5/5 live; see
`docs/architecture/navigation.md` and the archived
`docs/archive/plans/2026-07-28-m3-navigation/_DONE.md`; the offline map
generator was built but is blocked by PD2's DLLs and deferred). Next up
is M4 (game cycle), which needs its own `yona-plan` pass.

**User request protocol**: every instruction to the user is issued as
`🔶 R<n> [type]` and logged in `docs/instruction-log.md` — see the
convention in the agent-toolkit skills; continue IDs from that log. Superseded kolbot roadmap:
`docs/archive/plans/2026-07-28-pd2-offline-bot/`.

Perception and navigation are done and live-verified. All input goes
through `pd2bot.input.GatedInput`, whose single send path checks
`pd2bot.uistate.can_act()` *and* the game window being in the foreground,
and refuses otherwise — there is no bypass, and M4's menu clicking must
add its own separately-guarded method rather than weaken this one (see
`docs/architecture/navigation.md` and the ADRs). Live checks against the
game need an **elevated terminal with a human present** (the client runs
elevated); every ask to the user goes through the request protocol above.
This repo is developed from two machines (Mac = planning/docs, Windows =
the machine with PD2 + the live bot); keep state in git and planning
artifacts so sessions on either side can resume.

## Development workflow (agent-toolkit)

For non-trivial work, follow the toolkit workflow skills (installed
globally from the agent-toolkit repo): `/yona-plan` (plan first),
`/yona-implement` (execute a plan), `/yona-review` (review changes),
`/yona-push` (push/PR/CI). Plans live in `docs/plans/`, reviews in
`docs/reviews/`; both are archived under `docs/archive/` when done.

**Teaching step (always):** at the end of every development cycle, follow
the `/teach` skill — write a short plain-language explainer of the cycle's
key concepts in `docs/learning/` and update `docs/learning/glossary.md`.
The teach step is part of "done", not optional polish. The skill contains
the learner profile and communication preferences — calibrate to them.
