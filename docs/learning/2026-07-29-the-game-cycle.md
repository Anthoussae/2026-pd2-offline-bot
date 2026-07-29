# The game cycle: state machines, complements, and fail-stop — 2026-07-29

*Cycle: M4 — the bot now creates and leaves games by itself, verifies
every game it enters, flees on low vitals, and stops dead (literally) if
the character dies.*

## The big idea

Until now the bot could see and walk, but a human had to hand it a game
to see and walk *in*. M4 built the loop around everything else: get into
a game, confirm it's the right one, do the work, get out, repeat — and
know when to bail out or stop entirely. Everything in it is one pattern
applied over and over: **observe state, act, verify the state changed,
never act on a state you can't name.**

## Key concepts

**State machine.** A design where the program is always in exactly one
named state (main menu, char select, difficulty popup, in game...) and
only moves between them along defined transitions. The discipline isn't
the naming — it's refusing to act while in an *unrecognized* state. Our
cycle raises an error carrying a full description rather than clicking
into a screen it can't identify. Any system that must drive another
system (installers, payment flows, network protocols) is written this
way.

**Polling with timeouts and bounded retries.** After every action the
cycle doesn't assume success; it repeatedly re-checks ("did the screen
change yet?") up to a time limit, re-tries the action a fixed number of
times, then gives up loudly. The alternative — fire the click and
assume — is called open-loop, and it's how automation silently drifts
off the rails. Note the *bounded* part: unlimited retries turn a stuck
program into a stuck program that also hammers its target forever.

**Complement guards.** M3 built one gate: input is allowed only *in a
game with no menu covering it*. M4 needed to click exactly where that
gate says no — the menus. The wrong fix is adding a bypass flag to the
existing gate (every bypass eventually gets used by accident). The right
fix, and what we built, is a **second gate whose condition is the
logical complement of the first**: menu input is allowed only *outside
a game, or with the ESC menu open*. Neither path can do the other's
job, so the M1 accident (a click meant for the world landing on "Save
and Exit Game") is now structurally impossible in both directions.

**Fail-stop.** When the character dies, the bot does not try to be
clever. It latches a permanent halt: no further input of any kind, a
loud alert, and the game left untouched for the human. Choosing to
*stop* on a serious failure — rather than attempt recovery you haven't
designed — is a respected engineering stance (databases do it, avionics
do it). The alternative, guessing after something has already gone
badly wrong, tends to convert one failure into several. The halt is a
**latch**: once set, it stays set no matter what later observations
say, because "the world looks fine again" is exactly what a wrong
recovery would look like too.

**Verify, then trust (the difficulty guard).** Every game the bot
enters, it reads the actual difficulty out of memory and compares it to
what it intended, *before* doing anything else. The lesson generalizes:
after an action whose failure would silently corrupt stored data (here,
the map atlas), don't verify the *action* — verify the *outcome*, from
the most authoritative source available.

**Calibration beats models (again).** The menus turned out to be drawn
in a fixed 800×600 space, scaled to fit the window and centered between
black bars. Our first projection model was plausible and wrong by 140
pixels; the fix was measured, then *confirmed by measurement* (you
hovered the mouse on a button; the bot compared prediction to reality)
before any click was allowed to use it. Third milestone in a row where
the measured value overruled the documented one.

## What we did, in these terms

The bot reads the menu system's own widget list from memory (each
button's position, size, and label), classifies the current screen by
fingerprint, and refuses on `UNKNOWN`. A state machine drives
leave/create sequences with polling, timeouts, and bounded retries; a
complement-guarded input path does the clicking; the difficulty guard
verifies every entry; a per-tick safety monitor implements chicken
(flee at a vitals threshold — a floor trigger that reacts to the
crossing, not the exact value) and the fail-stop death latch.
Acceptance: three unattended create-verify-dwell-leave cycles, plus a
live chicken drill run at zero risk by putting the threshold somewhere
harmless (mana, in town). We also gave the bot a chat voice in-game, so
live-test instructions reach you without alt-tabbing — its guard types
nothing until the chat box is confirmed open, since keystrokes without
a text box are hotkeys.

## Where you'd meet this professionally

State machines with explicit unknown-state handling are the backbone of
anything that automates a UI or a protocol (test frameworks like
Selenium/Playwright, payment and checkout flows, deployment
orchestrators). "Bounded retries with timeouts, then fail loudly" is
close to a job-interview answer for designing any distributed or
flaky-environment system. Fail-stop versus fail-recover is a genuine
design decision you'll see argued in incident reviews; knowing *when
not to auto-recover* reads as seniority. And the guard/complement-guard
construction — making the dangerous thing structurally unreachable
instead of policy-forbidden — is the mindset behind most good security
and safety engineering.
