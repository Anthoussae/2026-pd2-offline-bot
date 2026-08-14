# P1 — the config trio

Size: sm. Dependencies: none. Review gate: none. No game time.

## Scope

1. `config/necro.toml`: `heal_below_pct = 100.0` → `75.0` (comment: the
   R241 choice — drink when meaningfully hurt, not to top up).
   `heal_cooldown_s` stays 10.0.
2. Skip low runes: in `config/pickit.toml`, ABOVE the "all runes" rule,
   add a skip rule for ranks 1–12 (El…Sol). Mechanism: add an
   `item_ids.toml` group `runes_low = [el_rune … sol_rune]` (the first
   12 of the existing list) and a rule `kinds=["runes_low"],
   action="skip"`. **Check first** whether the id tables give the PD2
   stackable variants (`r01s`…`r12s`) their own names — if they resolve
   to the same kind ids as the plain runes nothing more is needed; if
   they have distinct kinds, the group must include them (the codes
   exist at item_codes.toml:710+). State what was found in the commit.
3. Delete the two dormant socket rules (pickit.toml:111–121) and the
   comment block introducing them; note in the file that T38 never ran
   and the rules matched nothing (user removal, R241 item 8-adj).

## Files

config/necro.toml, config/pickit.toml, config/item_ids.toml.

## Validation

pytest (the shipped-pickit tests validate the file loads fully
resolved and rules fire — expect count unchanged or +new), ruff.
`python -m pd2bot.wiring --dry-run` if cheap. Commit
`feat: config trio — heal at 75, skip El–Sol runes, drop dormant socket rules`.

## Reminders

Do not touch rule order semantics (first match wins — the skip must sit
ABOVE "all runes"). Do not expand scope.
