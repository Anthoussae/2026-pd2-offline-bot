# P1 — Package skeleton and session layer

**Work item:** P1 · **Size:** sm · **Depends on:** nothing ·
**Blocks:** P2, P3, P4 · **Review gate:** none

## Scope

Stand up the project's first real Python package and the layer every
later phase reads through.

1. **Tooling**: `pyproject.toml` (project metadata, deps: `pymem`;
   dev deps: `pytest`, `ruff`), repo-root `.venv` on Python 3.12
   (installed at `%LocalAppData%\Programs\Python\Python312` — verify),
   ruff config (line length 100 is fine; default rule set plus `I`
   for import sorting).
2. **`pd2bot/offsets.py`** — every constant in the project, each with a
   comment citing its BH source file and line. Seed it from the
   verified table in
   `../2026-07-28-bot-from-scratch/spike-log.md` and the chains in
   [notes.md](notes.md). Nothing else in the codebase may contain a
   magic offset.
3. **`pd2bot/memory.py`** — a `GameSession` class:
   - attach to `Game.exe` via pymem; raise a clear, actionable error if
     `OpenProcess` fails (**"run as Administrator — PD2 runs
     elevated"**), and a different one if the process is not running;
   - resolve `D2Client.dll` base at runtime (case-insensitive module
     match — the module reports as `D2CLIENT.dll`);
   - typed read helpers: `u8/u16/u32/i32/ptr/bytes/cstring`;
   - a `read_struct_field(base, offset, kind)` style helper if it keeps
     call sites readable — but do not build an ORM. Keep it thin.

## Out of scope

- Any game-domain modelling (player, units, UI) — later phases.
- Any input, any writes to game memory.
- Retry/reconnect logic and long-running loops (M4 owns the run loop).

## Implementation notes

- M1 proved 64-bit Python reads the 32-bit client fine; no 32-bit
  fallback needed.
- Elevation check: detect up front rather than failing deep in a read.
  `ctypes.windll.shell32.IsUserAnAdmin()` is the cheap check; a failed
  `OpenProcess` is the authoritative one. Report both clearly.
- Keep `GameSession` construction cheap and explicit — no global
  singleton, no import-time side effects. Later phases take a session as
  a parameter.
- A pointer read of 0 is normal and meaningful ("not in a game", "no
  such unit"), not an error. Model it as `None`, never as an exception.

## Files

- New: `pyproject.toml`, `pd2bot/__init__.py`, `pd2bot/offsets.py`,
  `pd2bot/memory.py`, `tests/test_memory.py`.
- Updated: `.gitignore` if the venv path differs from the existing
  `.venv*/` rule; `README.md` gets setup instructions (venv, install,
  Administrator requirement).

## Validation

- `ruff check .` and `ruff format --check .` pass.
- `pytest` passes (P1's tests cover the pure parts: typed read helpers
  against a fake reader, offset table sanity).
- Live smoke check, elevated, with the client running: a short script or
  REPL session attaches and prints the D2Client base address.
- Live negative check: run **unelevated** and confirm the error message
  is the actionable "run as Administrator" one.

## ADR expectation

None.

## Agent reminders

- Do not commit unless the user asked.
- Do not expand scope into game-domain modelling.
- Do not suppress lint warnings or skip tests to make them pass.
- Reads only — this milestone never writes to the game or sends input.
- Stop and report if blocked by ambiguity or an unexpected design issue.
- Report what changed, what was validated, and any deviations.

## Definition of done

Package imports cleanly, `GameSession` attaches to the live client and
resolves the module base, both error paths give actionable messages,
lint and tests pass, and `offsets.py` holds every constant with BH
citations.
