# PD2 offline kolbot

A kolbot-based bot for Project Diablo 2, **offline single-player only**
(hard constraint — never configure or document anything touching
battle.net/realms), on Windows. Deliverables: a working bot (poison dagger
necromancer, Countess first), an instruction manual (`docs/manual/`), and
kolbot component documentation (`docs/architecture/`). Customization uses an
overlay: `kolbot/` is a stock, gitignored clone of blizzhackers/kolbot; our
own configs/scripts will live in `overlay/` (from M2 on) and sync into it.

Active plan: `docs/plans/2026-07-28-pd2-offline-bot/` — read `plan.md` and
`notes.md` before non-trivial work. This repo is developed from two
machines (Mac = planning/docs, Windows = the machine with PD2 + the live
bot); keep state in git and planning artifacts so sessions on either side
can resume.

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
