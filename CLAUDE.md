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
generator was built but is blocked by PD2's DLLs and deferred). **M4
done** (game cycle: menu perception via the D2Win control list, the
separately-guarded `MenuInput`, autonomous create/leave with an
unconditional Hell-verification guard on every entry, chicken +
death-latch safety monitor, in-game chat channel; acceptance 3/3
unattended cycles — see `docs/architecture/game-cycle.md` and the
archived `docs/archive/plans/2026-07-28-m4-game-cycle/_DONE.md`). Next
up is M5 (trial run: FSM + necro combat + survival reflex ladder +
pickit — Cold Plains), which needs its own `yona-plan` pass; its
planning inputs (the survival toolkit, robustness-before-live-runs) are
recorded in the archived M4 notes.md.

**User request protocol**: every instruction to the user is issued as
`🔶 M<m> P<p> R<n> — Title [type] · YYYY-MM-DD HH:MM` (M/P from
`docs/project-state.md`; R is the overall counter, never reset), logged
in `docs/instruction-log.md` and appended one-line to
`docs/request-index.md` — full rules in the agent-toolkit skills'
"User request protocol" section. Superseded kolbot roadmap:
`docs/archive/plans/2026-07-28-pd2-offline-bot/`.

Perception, navigation, and the game cycle are done and live-verified.
Input goes through guarded send paths with **no bypass**: world input
via `pd2bot.input.GatedInput` (guard: `can_act()` AND foreground),
menu input via `pd2bot.menuinput.MenuInput` (guard: the complement —
not in a game, or the ESC menu open), chat via `pd2bot.chat.Chat`
(types only while the chat console is verified open). M4 kept the M1
contract: `GatedInput`'s guard was not touched. Safety invariant: after
a detected death the bot sends no input of any kind, permanently
(`pd2bot.safety`, the death latch) — do not add recovery behavior
without an explicit user decision (see
`docs/architecture/game-cycle.md`). Live checks against the
game need **Administrator rights** (the client runs elevated; UIPI also
blocks synthetic input from normal processes). The agent runs elevated
commands itself via the **bridge**: the user starts
`tools/elevated-bridge.ps1` in a run-as-admin PowerShell once per
session; the agent then drops `<id>.cmd.ps1` files into
`%LOCALAPPDATA%\pd2bot-bridge` and reads `<id>.out.txt` back (protocol
in the script header). A human still needs to be at the machine for
game-side actions; those asks go through the request protocol above.
Development happens on this Windows machine (the one with PD2). The repo
is maintained on GitHub as standard practice — keep state in git and
planning artifacts so any session, anywhere, can resume — but no special
accommodation for other machines is needed.

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
