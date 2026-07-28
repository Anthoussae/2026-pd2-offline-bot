# 2026-pd2-offline-bot

A kolbot-based bot for Project Diablo 2 — **offline single-player only** —
on Windows. See [CLAUDE.md](CLAUDE.md) for the project overview and
[docs/plans/2026-07-28-pd2-offline-bot/plan.md](docs/plans/2026-07-28-pd2-offline-bot/plan.md)
for the active roadmap.

## Setting up a new machine (e.g. the Windows box)

Run these in a bash-capable terminal (the one inside Claude Code on Windows
works). Step 1 installs the agent-toolkit workflow skills globally; step 2
clones this project and pulls a stock kolbot clone into `kolbot/` (which is
intentionally gitignored — see the overlay approach in the plan):

```bash
git clone https://github.com/Anthoussae/agent-toolkit && ./agent-toolkit/install.sh
```

```bash
git clone https://github.com/Anthoussae/2026-pd2-offline-bot && cd 2026-pd2-offline-bot && git clone --depth 1 https://github.com/blizzhackers/kolbot kolbot
```

Then start Claude Code in the project folder and begin with:

> Read docs/plans/2026-07-28-pd2-offline-bot/plan.md and notes.md, then
> `/yona-implement` the M1 phase (01-windows-spike.md).

## Working across machines

Mac = planning/docs; Windows = the machine with PD2 and the live bot. All
state lives in git and the planning artifacts under `docs/plans/` — push
after each session so the other machine can resume.
