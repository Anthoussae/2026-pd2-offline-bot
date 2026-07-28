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

Active plan: `docs/plans/2026-07-28-bot-from-scratch/` — read `plan.md`
and `notes.md` before non-trivial work. Superseded kolbot roadmap (incl.
its completed M1 spike): `docs/archive/plans/2026-07-28-pd2-offline-bot/`.
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
