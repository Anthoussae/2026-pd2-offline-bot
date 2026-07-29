# When reality corrects the docs — 2026-07-28

*Cycle: M3 navigation — the input gate, reading walkability from memory,
the explored-map atlas, A* pathfinding, and the walk loop. The bot walked
its first routes on its own (5/5 acceptance).*

## The big idea

Almost every bug this cycle came from the same source: a written-down
"fact" that reality disagreed with. The community's struct headers said
the collision grid ended with a pointer — the live game showed the grid
stored inline instead. The renderer's config file implied one scaling
factor — measuring actual walks gave a different one. My own first
guess at the click math was off by exactly that scale. The professional
habit this builds is: **documentation is a hypothesis; the running
system is the evidence.** Good engineers don't skip reading the docs —
they read them, then design a cheap check that would catch the docs
being wrong. Each of our checks (a debug dump, a calibration routine)
took minutes and caught an error that would have cost hours of confused
debugging later.

## Key concepts

**Calibration** — deriving a constant by measuring the system instead of
assuming it. We clicked in eight directions, recorded how far the
character walked, and fitted the pixels-per-subtile values from the
data (20/10, not the theoretical 16/8). The fit also *validated itself*:
the isometric model requires the x/y ratio to be exactly 2, and the
measured ratio was 2.000. When a fitted model reproduces a constraint
you didn't feed into it, that is strong evidence you measured the right
thing.

**Closed-loop control** — act, observe the result, correct, repeat.
The walk loop never assumes a click worked: it clicks, watches the
player's actual position, and escalates when nothing changes (re-click,
then re-plan, then give up loudly). The alternative — "open-loop": issue
all the clicks and hope — fails the moment anything unexpected happens.
Your own mouse-touch during the demo was absorbed by exactly this loop:
the disturbance changed the observation, and the next correction fixed
it. A subtlety we hit: the give-up counter must measure *lack of
progress*, not *slowness*, or a slowed character reads as a failure.

**Transient vs persistent state** — the game's collision grid encodes
two different kinds of fact in one number: "there is a wall here"
(true next week) and "a monster is standing here" (false in two
seconds). Storing both in a permanent map file caused 247 phantom
updates in one survey — and would have frozen corpses into walls. The
fix is separating them at the boundary: the live view keeps everything
(a monster in your way is real *now*); the saved atlas strips the
transient bits and keeps only terrain. Asking "what is the lifetime of
this piece of data?" before persisting it is a habit that prevents a
whole category of cache bugs.

**Guard at the point of action** — the input gate re-checks "is it safe
to click?" inside the one function that clicks, not at every call site.
Call sites forget; a single chokepoint cannot be bypassed by accident.
This is the structural answer to M1's "Save and Exit Game" incident,
and it held: in live testing the gate refused correctly with the menu
open and with the window unfocused, in the real client.

## What we did, in these terms

Built the gated input layer and calibrated its screen math; read the
game's own walkability grids after a debug dump corrected the struct
layout; persisted only the terrain into a per-seed atlas (your insight
that single-player maps never change made a whole external map
generator unnecessary); ran A* over atlas+live knowledge; and closed
the loop from plan to click to observed position. Ten sixty-subtile
walks, ten arrivals.

## Where you'd meet this professionally

Calibration-over-assumption appears anywhere software meets a physical
or third-party system: sensor offsets, clock skew between servers, an
API whose docs lag its behavior. Closed-loop thinking is the core of
site reliability work (monitor → alert → correct) and of any retry
logic. The transient/persistent split is the daily bread of caching —
"how long is this value true?" is the first question of every cache
design. And single-chokepoint guards are how real systems enforce
invariants: one function that touches the database, one module that
holds credentials, one gate that sends the click.
