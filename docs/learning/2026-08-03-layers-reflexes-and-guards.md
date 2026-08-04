# Layers, reflexes, and guards — 2026-08-03

*Cycle: M5, the trial run — the bot now plays a full game (heal, travel,
fight, loot, leave) unattended, and passed a staged live acceptance.*

## The big idea

M5's real product is not the fighting; it is a *structure* in which
fighting can never crowd out surviving. Every piece of this cycle is
some form of the same move: take a rule that used to live in someone's
head ("always check your health", "make sure the right spell is
selected") and turn it into architecture, so that forgetting it is no
longer possible.

## Key concepts

**Layered architecture.** The bot's decision-making is split into three
layers that do not know each other's contents: a small engine that
ticks; run definitions that are pure data ("preamble, then waypoint,
then clear"); and a per-class combat module behind an interface. This
is **separation of concerns**: each layer can change — a new run, a new
character class — without touching the others. The proof it works: a
second run really is just a new TOML file.

**Priority interrupts (the reflex ladder).** Every tick, before the
current task gets a turn, an ordered list of survival checks runs —
drink, escape, retreat, upkeep — and the first one that fires *takes
the whole tick*; the task simply does not run. This is how operating
systems treat interrupts: urgent things preempt scheduled things, by
construction rather than by each task remembering to check. The subtle
part we paid for twice: a **cooldown** (this resource is spent) must
only start when the action really happened, but **pacing** (do not spam
this) must record even failed attempts — collapsing the two produced a
livelock in one direction and a stopped ladder in the other.

**Command vs. effect (the verified switch).** Sending a command is not
the same as the command having happened. Before any cast, the bot
presses the hotkey and then *reads the game's memory* to confirm the
skill actually switched; a blood-warp cast is only believed once the
character has visibly moved. This "act, then verify the effect" habit
is everywhere in serious automation, because the alternative — trusting
your own output — fails silently and at the worst time.

**Behavior as data (the pickit).** What loot is worth picking up lives
in `config/pickit.toml`, not in code. The same is true of the runs and
every class number. The payoff is twofold: a non-programmer can tune
behavior safely, and the loader can **validate** the whole file at
startup — an unknown key or misspelled step name stops the program with
a clear error *before* anything moves, instead of misbehaving an hour
in. "Fail loudly at load time, not quietly at run time" is a
professional reflex worth internalizing.

**Scoped guards.** The bot has exactly four ways to send input, and
each is wrapped in a guard that states *when sending is legitimate*:
world clicks (in a game, no panel open), menu clicks (not in a game),
chat typing (chat provably open), and — new this cycle — panel clicks
(the specific panel the caller names is provably open, re-checked at
the moment of clicking). No path has a bypass flag. When a new need
appeared (clicking inside the stash), the answer was a new narrow
guard, not a hole in an old one.

## What we did, in these terms

The engine ticks: snapshot → safety monitor → reflex ladder → current
step. The staged acceptance (A through E, each riskier than the last,
ending with three unattended clean runs) is itself a professional
pattern: never jump from "works in simulation" to "runs alone" in one
step. And the week's hardest bug was a perception-vs-action mismatch:
the bot *saw* items perfectly (memory reads) but *clicked* them wrongly,
because the clickable sprite draws above the item's map position — the
fix came from measuring, not guessing.

## Where you'd meet this professionally

Layering and interfaces are the daily bread of any codebase you will be
hired into; "make the illegal state unrepresentable" and "validate at
the boundary" are phrases you will hear in code review. The
cooldown-vs-pacing distinction reappears in every retry system (backoff
policies); command-vs-effect is the heart of distributed systems ("did
my request succeed, or did I just send it?"); and staged rollouts —
canary releases, feature flags at 1% — are how every large service
ships. The glossary has the new terms.
