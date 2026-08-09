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

## Game cycle tools (M4)

The bot creates and leaves single-player games by itself — menus are read
from memory (the D2Win control list) and clicked through a second,
separately-guarded input path. Every game entry is memory-verified as the
configured difficulty before anything else runs, and a per-tick safety
monitor chickens out of games on vitals thresholds and halts permanently
(no further input, loud alert) if the character dies. See
`docs/architecture/game-cycle.md`.

```bash
python -m pd2bot.oog                  # which menu screen is up + its controls
python -m pd2bot.cycle --games 3      # unattended create/verify/dwell/leave cycles
python -m pd2bot.chat "hello"         # post a message to the in-game chat
```

`pd2bot.cycle` takes `--dwell`, `--life-chicken`, `--mana-chicken`, and
`--chicken-in-town` (the last is a live-test aid). Menu clicking relies on
two calibrations recorded in `pd2bot/cycle.py` and `pd2bot/menuinput.py`
(the pillarboxed menu scale is derived from the window; the Save-and-Exit
position was hover-measured) — re-check them after changing window size or
resolution.

## Running the bot (M5)

The bot now plays: town preamble → waypoint → clearance (with patrol)
→ pickit-driven pickup → leave, repeat. From an **elevated** terminal
at the repo root (or through the bridge — see below):

```bash
python -m pd2bot.wiring --games 3
```

Flags: `--run runs/<file>.toml` (default `cold-plains`), `--radius N`
and `--chicken PCT` overrides (both refuse loudly if they have nothing
to apply to), `--dry-run` (assemble, print the wiring, send nothing).
`tools/live-run.ps1` wraps this through the elevated bridge with
absolute paths baked in; `tools/bridge-run.ps1` runs arbitrary drills
the same way, and `tools/drill-cancel.ps1` (or typing `abort` in the
in-game chat, or pressing ESC/Enter in the field) stops a run.
Architecture: `docs/architecture/behavior.md`.

**What the operator tunes** (both files are commented for exactly this):

- `config/pickit.toml` — what is worth picking up and what to keep,
  stash, or drop. The user-facing knob; edit freely between sessions.
  While it names unresolved item ids the inventory cleanse disables
  itself and says so at startup.
- `config/necro.toml` — every class number: skill ids, hotkeys (must
  match the client's F1–F6 bindings), the belt layout and refill
  minimums, all reflex-ladder thresholds, the skirmish numbers. The
  loader rejects unknown keys loudly, so typos fail at startup.
- `runs/*.toml` — the runs themselves (ordered steps + parameters); a
  new run is a new file, validated at load. `config/item_codes.toml`
  and `config/item_ids*.toml` are the item vocabulary the pickit
  matches against (`item_ids.learned.toml` grows from play).

`pd2bot.dump` gained diagnostic flags used throughout the M5 live work:
`--items` (raw ground-item fields), `--monsters` (type-1 units with
alignment and distance), `--carried` (carried items with raw location
bytes). Live drills follow the T-numbered protocol in `pd2bot/drill.py`
and log to `docs/drill-log.md`.

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

CI runs both checks automatically on every push: GitHub Actions
(`.github/workflows/ci.yml`) runs the full pytest suite and `ruff check` on a
Windows runner (the code imports Win32 APIs at module load, so Linux runners
cannot collect it). Green CI means the offline half is sound; it verifies
nothing about the live game — offsets and calibrations remain the job of
`pd2bot.dump` and the drills.

## Setting up a new machine

Install the agent-toolkit workflow skills globally, then clone this project and
pull the stock kolbot reference clone into `kolbot/`:

```bash
git clone https://github.com/Anthoussae/agent-toolkit && ./agent-toolkit/install.sh
```

```bash
git clone https://github.com/Anthoussae/2026-pd2-offline-bot && cd 2026-pd2-offline-bot && git clone --depth 1 https://github.com/blizzhackers/kolbot kolbot
```

## Keeping state in git

Development happens on the Windows machine with PD2 installed. All state
lives in git and the planning artifacts under `docs/plans/` — commit and
push after each working session, standard practice, so the project can be
picked up from anywhere.
