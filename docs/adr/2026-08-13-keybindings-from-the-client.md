# ADR: keybindings come from the client's own config file

Date: 2026-08-13 · Status: **accepted** · Plan:
`docs/plans/2026-08-13-hotkey-config/` (R247)

## Context

Every key the bot pressed was an assumption: skill hotkeys hand-captured
per character (R47.1) into a hardcoded table and a toml the operator had
to keep in sync by hand; belt keys, the inventory toggle and the Show
Items label toggle simply assumed the client's default bindings, as
"(default binding)" comments scattered across five modules. A rebound
client would have failed silently, mid-run, one wrong keypress at a
time — and nothing would have named the cause.

Diablo II stores the player's ACTUAL bindings in a per-character file
(`Save\ProjectD2\<Char>.key` under the install). The format is
undocumented, but was pinned empirically against the live install
(2026-08-13): a variable header, then 108 self-describing 20-byte
records — each embeds its own function index twice — holding primary
and secondary Win32 VKs per bindable function.

## Decision

1. **The client's `.key` file is the source of truth for bindings.**
   `pd2bot/input/keyfile.py` parses it with a SELF-VALIDATING scan that
   refuses anything that does not prove itself (the mitigation for the
   undocumented format: a wrong parse would press wrong keys with full
   confidence, so no guessing, ever). Discovery walks from the running
   client's exe path; `BotPaths.keyfile` overrides; re-read per game so
   mid-session rebinds are honored.
2. **The toml still declares intent; the file verifies it.** The `.key`
   file cannot say WHICH skill sits on a hotkey slot (that lives in the
   character save), so `[hotkeys]` keeps its skill→key shape — and the
   wiring refuses at build time when a configured key drives no
   skill-hotkey slot in the client's layout, naming the skill, the key,
   and the client's actual slots. Runtime truth remains
   effect-verification (`ensure_right_skill`), unchanged.
3. **Non-skill bindings come from the file directly** (belt columns,
   inventory, Show Items) through one registry —
   `pd2bot/input/keys.py`, which also owns every VK constant and the
   fixed, non-bindable UI keys (ESC/Enter/arrows), ending the
   per-module duplicates.
4. **No client ⇒ the historical defaults, with a notice.** Sims, unit
   tests and clientless machines behave byte-for-byte as before;
   "defaults" is a labeled source, never a silent guess.

## Consequences

- A rebound client turns from a silent mid-run failure into a loud
  build-time refusal with fix instructions on both sides (toml or
  Configure Controls).
- The PD2 function list DIVERGES from vanilla's past the belt entries
  (Show Items: entry 37 in PD2, 63 in the vanilla-era file) — indices
  above ~26 are only trusted against PD2-written files, and the Show
  Items resolution falls back to ALT with a notice rather than refusing
  over a label toggle.
- The format pin rests on one install. The self-validation and the T89
  demonstration drill (parse → verify → live effect-verified switches)
  are the guard; a client patch that changes the format produces a
  refusal, not a misparse.
