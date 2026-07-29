# 2026-pd2-offline-bot

A from-scratch Python bot for Project Diablo 2, targeting the offline
single-player client on Windows. It reads the running game's memory
out-of-process and drives it with synthetic input — it never injects code into
the game.

See [CLAUDE.md](CLAUDE.md) for the project overview,
[docs/architecture/perception.md](docs/architecture/perception.md) for how the
bot sees the game, and [docs/plans/](docs/plans/) for the active roadmap.

> An earlier attempt to use the existing kolbot bot failed: kolbot supports
> Diablo II 1.13d/1.14d and PD2's client is 1.13c. The diagnosis is in
> [docs/archive/plans/2026-07-28-pd2-offline-bot/spike-log.md](docs/archive/plans/2026-07-28-pd2-offline-bot/spike-log.md).
> `kolbot/` is kept as a gitignored *reference* only — its scripts encode 20
> years of botting behaviour worth reading.

## Running the bot's perception tool

**You must run as Administrator.** The PD2 client runs elevated, and Windows
will not let an ordinary process read an elevated one's memory.

Start Project Diablo 2 normally (via PD2Launcher) and load your character, then
from an **elevated** terminal in the repo root:

```bash
python -m pd2bot.dump
```

Add `--watch` to keep printing at ~5 Hz, or `-v` for more detail. This is the
tool for checking that the bot sees the game correctly: run it, look at the
game, and confirm the numbers agree.

## Navigation tools (M3)

All from an elevated terminal at the repo root, game running:

```bash
python -m pd2bot.navdemo gate         # is input allowed right now, and why not
python -m pd2bot.navdemo click-test   # projection calibration (--send to click)
python -m pd2bot.collision            # ASCII walkability around the player
python -m pd2bot.navigate --survey    # record rooms into the atlas while YOU walk
python -m pd2bot.navigate --demo      # acceptance walk (see --help)
```

Input never bypasses the gate: every send checks `can_act()` and that the
game window is foreground, and refuses otherwise (see
`docs/architecture/navigation.md`).

## Map knowledge: the explored-map atlas

Single-player maps are fixed per character per difficulty, so the bot
*remembers* the collision grids it reads instead of generating maps:
they accumulate under `maps/` (gitignored save-data, regenerable by
walking). Walk each new area once with `--survey` (you steer, the bot
records); from then on the bot plans routes across the whole area. A
dormant offline map generator exists for maps never walked
(`pd2bot/mapdata.py`; blocked on this machine by PD2's modified DLLs) —
see `docs/adr/2026-07-28-hybrid-map-knowledge.md`.

## Development setup

Requires Python 3.12+. The virtualenv deliberately lives **outside** this
folder: the repo sits in OneDrive next to the large gitignored `kolbot/` clone,
and putting thousands of venv files there makes every install crawl.

```bash
py -3.12 -m venv "$HOME/.venvs/pd2bot"
"$HOME/.venvs/pd2bot/Scripts/python.exe" -m pip install pytest ruff pymem
```

The package is imported from the repo root rather than installed, so run
commands from there.

```bash
"$HOME/.venvs/pd2bot/Scripts/python.exe" -m pytest
```

```bash
"$HOME/.venvs/pd2bot/Scripts/python.exe" -m ruff check .
```

Tests run without the game: they exercise the decoding and traversal logic
against fixed byte buffers. They cannot tell you an offset still points at the
right thing after a game patch — only running `pd2bot.dump` next to the live
game can.

## Setting up a new machine

Install the agent-toolkit workflow skills globally, then clone this project and
pull the stock kolbot reference clone into `kolbot/`:

```bash
git clone https://github.com/Anthoussae/agent-toolkit && ./agent-toolkit/install.sh
```

```bash
git clone https://github.com/Anthoussae/2026-pd2-offline-bot && cd 2026-pd2-offline-bot && git clone --depth 1 https://github.com/blizzhackers/kolbot kolbot
```

## Working across machines

Mac = planning/docs; Windows = the machine with PD2 and the live bot. All state
lives in git and the planning artifacts under `docs/plans/` — push after each
session so the other machine can resume.
