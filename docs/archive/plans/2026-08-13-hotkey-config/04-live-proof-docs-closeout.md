# P4 — live proof, ADR, docs, cleanup

Size sm. Depends on P3. ADR: **expected** (write it here).

## Work

1. **T89 demonstration drill** (`drills/t89_keyfile_demo.py`): parse
   the live character file, print the detected bindings table
   (function → key name), print the toml verification verdict, and —
   in a game — effect-verify one skill switch per configured hotkey
   (the R47.1 capture, now automated). Register in the drill log.
2. **Live trip**: one `runs/t87-black-marsh-trips.toml` game via the
   bridge on the refactored path; read events + sampler for
   regressions.
3. **ADR** `docs/adr/2026-08-13-keybindings-from-the-client.md`:
   the client's own .key file is the source of truth for bindings;
   toml declares skill intent and is VERIFIED against the file; loud
   refusal on drift; defaults only when no client is readable.
   Record the empirical format basis and its risk (undocumented
   format, self-validating parse as the mitigation).
4. **Docs**: `pd2bot/input/README.md` (new keys/keyfile rows),
   `pd2bot/README.md` input line, CLAUDE.md only if a standing rule
   changes (it does not), glossary/teach at the CYCLE's closeout (the
   combat-logistics P6 teach step covers this detour too — note it in
   the plan dir rather than double-writing).
5. **Cleanup grep**: TODO/debug prints/dead constants; confirm
   DEFAULT_HOTKEYS survives only as labeled fallback; `_DONE.md` with
   outcomes, deviations, validation evidence.

## Validation

Full suite + ruff; T89 output pasted into `_DONE.md`; the trip's
events.jsonl clean (no refusals attributable to keys).

## Reminders

Session commit practice. The drill announces in chat (R95). Stop if the
live parse disagrees with the pinned format — that is a finding, not a
patch-over.

Done when: ADR committed, docs updated, T89 PASS registered, _DONE.md
written, plan archived per convention.
