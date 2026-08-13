# P1 — the .key parser (`pd2bot/input/keyfile.py`)

Size sm. No dependencies. ADR: none here (P4 writes the one ADR).

## Scope

A pure parser for D2's per-character keybinding file, self-validating,
tolerant of both observed framings. No consumers change in this phase.

Out of scope: the registry (P2), wiring (P3).

## Format (empirically pinned 2026-08-13 — see ../notes.md)

- After a variable header (4 bytes `25 00 00 00` on the character file,
  8 bytes `57 53 25 00 …` on `default.key`), **108 records x 20
  bytes**: `{u16 pad, u32 index, u16 primary_vk, u32 one, u32 index2,
  u16 secondary_vk, u16 pad}`; `index == index2` validates a record;
  `0xffff` = unbound; VKs are Win32 codes.
- Anchor by SCANNING: find the first offset where a run of >= 8
  consecutive valid records with ascending indices 0..7 begins, then
  stride. Refuse (return None / raise KeyfileError) when no anchor is
  found — never guess.
- Function labels the bot needs (constants in this module, pinned from
  `default.key` defaults + live cross-check):
  `CHARACTER = 0`, `INVENTORY = 1`, `AUTOMAP = 7`,
  `SKILL_HOTKEYS = range(14, 22)` (slots 1..8; F1..F8 default),
  `BELT = range(23, 27)` (keys 1..4 default),
  `SHOW_ITEMS = <pin empirically in this phase>` — scan default.key for
  primary 0x12 (ALT) and record the index with a comment quoting the
  evidence bytes.

## API

```python
@dataclass(frozen=True)
class Binding:
    index: int
    primary: int | None   # VK, None when 0xffff
    secondary: int | None

def parse_keyfile(data: bytes) -> dict[int, Binding]: ...
def read_keyfile(path: Path) -> dict[int, Binding]: ...  # thin IO wrapper
```

## Tests (`tests/input/test_keyfile.py`)

- A fixture builder that emits records byte-for-byte in BOTH framings;
  round-trip parse.
- Unbound (`0xffff`) → None; a corrupt record breaks the stride and the
  parser refuses rather than mislabeling.
- The live-shape fixture: entries 14..19 = F1..F6, 1 = I/B, 23..26 =
  '1'..'4' — assert the label constants line up (this is the regression
  pin for the empirical map).

## Reminders

Do not commit unless asked (the operator's standing pattern here is
commit-per-phase — follow the session's established practice). No scope
expansion; stop and report if the live file contradicts the pinned
format. Validation: `pytest tests/input/test_keyfile.py`, `ruff check`.

Done when: parser + tests green; SHOW_ITEMS index pinned with evidence.
