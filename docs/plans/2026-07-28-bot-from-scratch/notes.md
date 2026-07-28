# Notes — PD2 bot from scratch (plan B reorientation)

## Context: why this plan exists

M1 of the previous roadmap (now archived at
`docs/archive/plans/2026-07-28-pd2-offline-bot/`) delivered a decisive
verdict: **kolbot cannot run on PD2** — PD2's client is D2 1.13c,
current kolbot supports only 1.13d/1.14d, and the community's
historical bridge (pd2bs) is publicly dead. Full diagnosis:
`../../archive/plans/2026-07-28-pd2-offline-bot/spike-log.md`.

At the M1 review gate (2026-07-28) the user chose **plan B**: build the
bot from scratch using **out-of-process memory reading + synthetic
input** — resurrecting the architecture from the original
(pre-kolbot-reorientation) planning round. Kolbot's JS script library
demotes from runtime to *behavioral reference* (chicken logic, pickit
concepts, run structure); the shallow clone at `kolbot/` stays for
mining.

## Initial understanding and goals (carried forward + updated)

- Working bot for the user's PD2 **offline single-player** client on
  Windows; learning exercise: synthetic input generation and
  process-memory reading.
- First character: poison dagger necromancer. Flagship run target:
  Countess (staging TBD — see questions).
- Deliverables from the old roadmap to re-scope: instruction manual
  (`docs/manual/`) and component docs (`docs/architecture/`) — now
  presumably about *our* bot rather than kolbot (question below).
- Teaching theme: originally "efficient use/adaptation of existing
  solutions"; from-scratch still leans on existing solutions (BH
  offsets, map generators, kolbot behaviors) — theme likely survives
  reframed (question below).

### Scope change from user (2026-07-28, review-gate conversation)

**Offline-only is no longer a hardcoded/engineered constraint.** User's
reasoning: sole user; PD2 is patch-gated away from Blizzard T&C
exposure; no need for esoteric self-hamstringing (e.g. memory guards
that refuse to act unless single-player flag set — old Q4 is dead).
Offline single-player remains the *design target and scope* (it is what
the user plays; PD2's online realm has its own anti-bot rules and other
players, and is not a target of this project) — but we build no
enforcement machinery around it.

## Current state

- Repo has: `kolbot/` (gitignored stock clone, now reference-only),
  docs scaffolding, archived-pending old roadmap with completed M1.
- No bot code exists. Language/stack undecided (old QA reopens).
- Windows machine (this one) verified: PD2 at
  `C:\Program Files (x86)\Diablo II\ProjectD2\` (Game.exe 1.13c =
  1.0.13.60), Season 13 client, user plays offline SP char
  `MaqiuDoubing` (save in `..\Diablo II\Save\`). PD2's own BH fork
  (`BH.dll` + `BH.json`) is present and loaded in the user's normal
  play — authoritative offset source candidate.

## Discovery log (this round)

Freshness check of the plan-B tooling ecosystem (GitHub API, 2026-07-28):

- **Project-Diablo-2/BH — pushed 2026-07-14, active, current for S13.**
  Contains `BH/D2Structs.h`, `BH/D2Ptrs.h`, `BH/CommonStructs.h`,
  `BH/Constants.h` — the PD2-maintained memory structures/offsets for
  the exact client we target. This is the load-bearing dependency and
  it is healthy.
- **srounet/pymem — pushed 2026-05, active.** Python ReadProcessMemory
  wrapper; supports the Python-stack option.
- **jcageman/d2mapapi — pushed 2025-11**, C# REST wrapper running real
  game code headlessly for map layout + collision per (seed,
  difficulty, area). blacha/diablo2 (TS, 2023) and
  joffreybesos/d2-mapgenerator (Rust, 2022) same idea, staler.
  ⚠ Risk to validate later: these emit *vanilla* 1.13c layouts; PD2
  modifies some areas/maps (`pd2maps.mpq`). May need pointing at PD2's
  MPQs or accepting vanilla-equivalence for campaign areas (Tower
  likely unchanged — verify empirically in the relevant milestone).
- Older references (d2info 2020, D2SharpMemory 2015, DiabloInterface
  2022, Diablo-II-Address-Table 2024) — usable as cross-checks of
  structure layouts, not dependencies.
- koolo (D2R, Go) / botty (D2R, Python) — architecture prior art only.

Assessment: plan B's critical inputs (current offsets, memory-read
library, map generation) all exist and the critical one is maintained
by the PD2 team itself.

## Questions

(to be added after discovery)

## User answers / scope changes

### 2026-07-28 — Confirmation round + QA

- Q1 (out-of-process ReadProcessMemory, offsets from PD2's BH source): **yes**
- Q2 (SendInput synthetic input, foreground window, behind an input interface): **yes**
- Q3 (pin to current season; re-verify offsets seasonally): **yes**
- Q4 (fixed windowed mode, agreed resolution): **yes**
- Q5 (deliverables reframed to our bot: manual = our setup/config; architecture = our design + mined references): **yes**
- Q6 (keep `kolbot/` as gitignored behavioral reference): **yes**
- **QA (language/stack): Python** (pymem + ctypes/SendInput).
- **QB (map knowledge): approved hybrid** — seed-based offline map
  generation (d2mapapi-style) + A* for global routing; live memory-read
  collision as fallback/verifier; PD2-map-fidelity check (vanilla
  generator output vs PD2's actual areas) is an explicit early
  milestone task. Glossary: added A*, collision map, heuristic.
- **QC (behavior architecture): approved** — hierarchical FSM engine +
  two data layers (runs as declarative data; pickit rules as data,
  kolbot `.nip` as design reference). User notes: (a) PD necro travel
  style = on foot, killing everything en route (slower, safer; suits
  corpse-fueled kit and simplifies pathing — no pack avoidance);
  (b) future goals include more run paths and more characters →
  data-driven layers are load-bearing, not nice-to-have.
- Mined kolbot pattern (answering user question "is kolbot sorc-only?"
  — no): three-layer class handling: per-class *config* (data: skill
  IDs, army sizes, enabled scripts), per-class *attack module* (logic
  implementing a common interface, dispatched via
  `ClassAttack[me.classid]`), class-agnostic *run scripts* ("travel
  here, kill this"). Adopt the same separation: our per-class combat
  module + per-class config + class-agnostic run definitions.

## Future work ideas

(to be added)
