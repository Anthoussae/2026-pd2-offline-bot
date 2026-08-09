# The pd2bot package map

The folder tree mirrors the architecture docs: one subpackage per layer,
named the same way the documentation talks about it. Rule of thumb:
**the root holds the commands you type and the shared vocabulary; the
subpackages hold the machinery.**

```text
pd2bot/
├── offsets.py       The game's memory map: every address and constant,
│                    with provenance. Shared vocabulary for all layers.
│
│   Commands (python -m pd2bot.<name>) — thin shims or small CLIs;
│   each file's first line says where the machinery lives:
├── dump.py          print what the bot sees (the perception checker)
├── oog.py           which menu screen is up
├── navigate.py      survey / acceptance walks
├── collision.py     ASCII walkability view
├── cycle.py         unattended create/verify/leave game cycles
├── chat.py          post to the in-game chat
├── navdemo.py       input-gate and projection diagnostics
├── runlog.py        read a run's event log
├── watchdog.py      the independent safety process (guarded-run starts it)
├── wiring.py        THE BOT: assembles everything and plays runs
├── partyline.py     in-game notification channel
├── drill.py         the T-numbered live-drill harness
├── uipoints.py      calibrated UI click points
│
├── perception/      SEEING — reads game memory, decodes it into state.
├── input/           ACTING — every guarded send path (world, menu,
│                    panel, chat, hotkeys) plus window/screen plumbing.
├── nav/             MOVING — A* pathing, the walk loop, the explored-map
│                    atlas, waypoints, survey.
├── safety/          NOT DYING — the chicken/death-latch monitor and the
│                    separate watchdog process.
├── runlog/          REMEMBERING — the per-run event log and the
│                    narrative log.
└── behavior/        DECIDING — the tick engine, reflex ladder, necro
    │                combat, run definitions.
    ├── town/        town errands (heal, stash, belt, inventory), one
    │                concern per file; TownLayer composes them.
    └── steps/       the run steps a runs/*.toml file can name, one
                     step family per file.
```

Each subpackage has its own `README.md` (what lives there, what other
layers import from it) and each module's first docstring line states its
one job — `grep` for a concept, or read any folder's README, and you
should land within one file of the answer.

Layer rules that keep the structure honest:

- perception reads, input acts — nothing in `perception/` sends input,
  and `input/` guards are re-verified at send time with no bypass.
- `behavior/` talks to the world only through the layers above; runs
  are data (`runs/*.toml`), validated at load.
- `offsets.py` stays at the root because every layer shares it.

Docs: `docs/architecture/` explains each layer;
`docs/adr/2026-08-09-package-layout.md` records why the tree looks
this way.
