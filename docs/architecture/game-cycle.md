# The game cycle: how the bot gets in and out of games, and stays safe

M4's layer. Perception answers "what is around me" (M2), navigation
answers "how do I get over there" (M3) — the game cycle answers "how do
I get a *game* at all, and when do I abandon one". It is the layer that
turns a bot that can walk into a bot that can be left alone.

Companion docs: [perception.md](perception.md),
[navigation.md](navigation.md), and the archived M4 planning dir
([docs/archive/plans/2026-07-28-m4-game-cycle/](../archive/plans/2026-07-28-m4-game-cycle/plan.md)
— live-check history, calibrations, the implementation log).

## Menus are data too (`oog.py`)

At the menus there is no player unit, so all of M2's perception reads
nothing. But D2's menus are not pixels — every button, textbox and
image is a node in a linked list of `Control` structs owned by
D2Win.dll. `oog.py` walks that list and answers two questions from
memory alone: *which screen is this* and *where are its buttons*.

- Screens are named by **fingerprint** — a couple of controls at
  positions distinctive enough to identify the screen, mined from
  kolbot's `Control.js` (twenty years of community knowledge of these
  layouts) and verified against the live client. Anything that matches
  nothing is `UNKNOWN`, and the cycle treats `UNKNOWN` as "stop and
  describe", never "click and hope".
- Buttons carry their label (`"HELL"`, `"OK"`) as a wide string inside
  the struct, so the dump is self-explaining, and the state field
  distinguishes enabled from greyed-out (a disabled CONVERT TO button
  live-confirmed the semantics).
- The walk is bounded, cycle-guarded, and stops at the first implausible
  node — the list mutates while we read it, same defensive posture as
  the unit hash table.

`python -m pd2bot.oog` dumps the current screen and control table; the
live transition log (in-game → loading → main menu → char select →
difficulty → in game) classified every step with zero unknowns.

Two live discoveries worth remembering:

- **Save-and-exit lands at the MAIN MENU** in offline single player,
  not at char select — kolbot's lore says char select, but kolbot is
  multiplayer lore. The cycle's sequences are written to the observed
  reality.
- **The in-game ESC menu is *not* in the control list** (it belongs to
  D2Client's panel system, not D2Win). Its one load-bearing button gets
  different treatment — see below.

## The second gate (`menuinput.py`)

M3's `GatedInput` sends only when *in a game with no blocking panel* —
exactly where the menus are not. Rather than weaken that guard (the M1
"Save and Exit Game" incident is why it exists), M4 added the promised
second, separately-guarded path:

    GatedInput  sends only when  in a game AND no blocking panel
    MenuInput   sends only when  NOT in a game, OR the ESC menu is open

The guards are complements. A world click can never land on a menu; a
menu click can never land on the world; the M1 incident click is now
reachable only through the path whose guard *means* it. Same
construction rules as the first gate: no bypass flag, no unguarded
variant, checks re-run at the moment of sending, refusals raise
`InputRefused` with the reason.

`Chat` (`chat.py`) is the third narrow path: it types messages into the
in-game chat so a human watching the game gets instructions without
alt-tabbing. Its hazard is specific: if the opening Enter fails, "typed"
text lands on the game as hotkey presses — so nothing is typed until
the chat console (panel 0x05) is *verified open*, re-checked before
every character.

## Menu geometry: the pillarbox

Menu controls live in a fixed 800×600 space; the window is whatever the
user made it (1536×864 here). The mapping is **aspect-fit**: the menu
is scaled uniformly (min of width/800, height/600) and centered,
leaving black bars. On this window that is 1.44× with 192 px side bars
— and 1.44 is the mysterious scale M3 found in the config files and
rejected for world clicks. Both were right: 1.25× is the *world* scale,
1.44× is the *menu* scale.

This was not guessed: the first click used a naive stretch model and
missed the OK button by 140 px (horizontal only — the y agreement was
the clue), and the corrected model was confirmed by hover calibration
(user rests the cursor on the button, bot compares prediction against
`GetCursorPos`) to ±2 px before any further click was allowed.

"Save and Exit Game", having no control struct, is a hover-calibrated
position stored as *fractions of the client rect* (0.4889, 0.4236) —
the M3 HUD-strip precedent. Re-run that calibration after any window
or resolution change.

## The cycle itself (`cycle.py`)

    leave:   ESC → esc menu open? → click Save and Exit → main menu
    create:  main menu → SINGLE PLAYER → char select (character is
             pre-selected) → OK → difficulty popup → HELL → loading →
             in game → player readable → THE GUARD

Every transition is a poll with a timeout and bounded re-clicks
(kolbot's locationTimeout pattern): a click that didn't take gets
retried a couple of times, then the cycle stops and *names the screen
it was stuck on*.

**The difficulty guard** runs after every game entry, before any run
logic: the difficulty byte is read from memory (via parsing BH's
`GetDifficulty` — same trick as the UI array) and must equal Hell. A
misclicked difficulty popup therefore costs one aborted cycle — never a
poisoned atlas, which is the actual risk: difficulty is the one part of
the atlas key (seed, difficulty, area) that a misclick could silently
falsify.

The error taxonomy, decided before any of it was built:

| event | response |
|---|---|
| focus lost | refocus once; if it fails or repeats, pause and wait for the human — never fight a person for their own mouse |
| transition timeout | bounded retries, then stop, naming the screen |
| `UNKNOWN` screen | stop immediately with the control dump |
| wrong difficulty | leave the game, halt the loop |
| `NavigationError` in a run | fail the cycle, start the next game (a fresh game in town is the cheapest recovery there is) |
| death | see below — the one response that sends nothing |

Acceptance was empirical: `python -m pd2bot.cycle --games 3 --dwell 10`
ran three unattended cycles, each created, Hell-verified, dwelled, and
exited, with zero retries and zero human input.

## The safety monitor (`safety.py`)

A per-tick watchdog over the player's vitals, two reflexes, death
always evaluated first:

**Chicken** (kolbot's word): life at/below a percentage threshold
outside town → leave the game *now*. Offline SP makes this stronger
than it sounds, because ESC pauses the game instantly — the exit is
effectively complete the moment the keypress lands, and the remaining
clicks happen in a paused world. The threshold is a **floor trigger**
sampled ~2.5×/s: it fires on the first observation at-or-below, which
after a burst of damage may be well below the threshold. That is the
intended semantic — react to the crossing within a tick, don't wait to
observe the exact value. A chickened game is a routine outcome; the
loop continues — **but not forever**: PD2 carries HP/mana between games
(no heal on re-entry), so a character below the threshold at game entry
would chicken out of every game it ever enters. The loop halts loudly
after N consecutive chickens (default 2) — user-spotted during the live
drill, whose "odd" instant trip was exactly this carried-vitals effect.
The durable fix is M5's town-heal preamble (visit the healer before
leaving town, kolbot-style); the backstop stays as defense in depth.

**The death latch**: if the player's unit mode reads Death/Dead (0/17)
or hp reads zero, the monitor fires a loud local alert and latches
permanently — from that moment the bot sends *no input of any kind*,
not even leave-game, and the latch survives anything memory says later.
The game is left exactly as the human needs to see it (user decision:
death recovery and corpse retrieval are deferred, low priority; a bot
that guesses after its character died has already guessed wrong once).

The chicken was live-proven at zero risk via the mana threshold (same
code path as life, different stat): threshold 99%, cast in town,
watched the bot announce the trip in chat and evacuate. The death path
is simulation-tested only, deliberately — its entire behavior is "send
nothing and alert", which fakes cover completely, and dying in Hell to
test it would cost real experience.

## Re-verification after a patch

Same drill as perception (see perception.md), plus, in order of
likelihood to move:

1. `D2WIN_FIRST_CONTROL` and the `Control` struct (offsets.py cites BH
   `D2Ptrs.h:624` and `CommonStructs.h:567-585`) — re-fetch, re-diff,
   re-dump at char select.
2. `GetDifficulty` (BH `D2Ptrs.h:152`) — the parser self-discovers the
   byte's address and refuses on unrecognized code, so a moved variable
   is caught loudly; verify with one Hell game.
3. The two hover calibrations (menu scale is derived, but Save-and-Exit
   fractions are measured) — re-run after any window/resolution change,
   patch or not.
