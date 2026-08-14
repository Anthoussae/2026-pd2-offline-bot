# P3 — posture fight styles and berserk

Size: md. Dependencies: P2 (for the return policy hook). Review gate:
**end of phase — the supervised berserk run (R241 Q6); the operator
watches and judges.**

## Scope

**A. The style enum** (`behavior/combat.py`): `CombatConfig` gains
`style: str = "skirmish"`, valid values `{"skirmish", "charge"}`,
validated at load. `_POSTURE_KEYS` admits `style` (this is the
deliberate crossing of "a posture is a manner, not a build" —
`combat.py:250`'s comment must be updated to cite the ADR). Skills
remain excluded; the enum names a choreography the class module
implements, not arbitrary behavior.

**B. Charge style** (`behavior/necro.py`): when style == "charge":
target = nearest visible hostile (keep the futility write-off and the
never-struck preference as tiebreak within "nearest band"); attack =
poison dagger left-click; NO skirmish out-step (the dash-out is
skipped); retreat still honored when the reflex ladder or
retreat_group_size demands it (berserk is not suicide — the ladder
outranks style by construction). Desecrate/revive upkeep: unchanged
(they are upkeep, not choreography).

**C. The berserk posture** (`config/necro.toml`):

```toml
[combat.postures.berserk]
style = "charge"
armor_recast_below_pct = 60.0   # verify the actual rung key name in
                                 # necro.toml [reflex]; wire a per-
                                 # posture override for it if the rung
                                 # threshold is not yet posture-aware
linger = true
```

plus the P2 return policy: berserk returns to the line only at zero
hostiles within perception of the engagement bubble. If making the
armor rung threshold posture-aware is disproportionate, STOP and
report options instead of hacking it.

**D. Run wiring**: nothing new — `posture = "berserk"` in any step
already flows through `_checked_posture`.

## Live acceptance (SUPERVISED — Q6)

One Cold Plains clearance with `posture = "berserk"` on the clear step
(a scratch run file is fine), operator watching, hands near ESC.
Expect: charge-nearest visibly different from skirmish; armor recast
firing below 60%; potions normal; no starved safety (the ladder's
precedence is the claim under test as much as the style). Judge by eye
AND by the event log (reflex counts, safety silent).

## Validation

Unit tests: style validation, charge target selection (nearest, write-
off respected), posture override of style + armor number, sim run under
berserk (the simworld exercises engage loops). pytest + ruff; commit.

## Reminders

The reflex ladder and safety monitor are not modified — berserk's
safety IS their precedence; if any test requires weakening a rung to
make charge "work", stop. Update behavior.md's posture section.
