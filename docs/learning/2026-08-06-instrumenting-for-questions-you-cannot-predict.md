# Instrumenting for questions you can't predict — 2026-08-06

*Cycle: the run event log — always-on, schema'd, append-only records of
what the bot did and why (`docs/archive/plans/2026-08-05-run-event-log/`,
ADR `docs/adr/2026-08-05-run-event-log.md`).*

## The big idea

The bot spent **144 seconds stuck in an empty square room** and gave the
run up, and nobody could say why — because out of roughly 150 decisions
it made in that room, exactly **5** were written down. Four confident
explanations were offered for the failure. All four were wrong. The fix
was not a cleverer guess; it was **recording every decision**, so the
next time something misbehaved the answer was already on disk.

That is the whole lesson of this cycle: **you cannot predict which
question you'll need to ask, so instrument for all of them.** A log
built to answer "did it pick up the rune?" is useless when the real
question turns out to be "why did it stand still for two minutes?" The
only defence is to record the *decisions themselves*, not a
hand-picked summary of the ones you thought would matter.

## Key concepts

**Reasoning from silence.** When the record is sparse, the mind fills
the gap with a story — and a plausible story is indistinguishable from a
true one until you check. "The fight owned the ticks", "the staircase
was contested": both were offered with confidence, both were false, and
both *sounded* right. The discipline this cycle installed: when
something misbehaves, **read the log; and if the log can't answer, add
the instrument, not a story.** The repo now says this in CLAUDE.md
because it was paid for four times in one session.

**Structured events, not print statements.** The log is JSONL — one
line per event, each a small labelled record (`kind`, a timestamp, the
area, and a payload). Because it is structured, it is *queryable*: `-m
pd2bot.runlog --pickup` correlates every pickup attempt against every
collection to answer "which wanted items did we fail to get, and why" —
a question no amount of scrolling through ad-hoc `print()` output could
answer. A text log is something you read; a structured log is something
you *ask*.

**The four rules that keep an instrument honest.** Instrumentation must
not change or endanger the thing it measures:
- *never raises* — a logging bug must not crash the run it's watching
  (least of all on the tick that was already failing);
- *never blocks* — measuring must not slow the loop into new behaviour;
- *never interprets* — it records what was observed (the last action
  before an item appeared), never a conclusion about cause;
- *honest absence* — a field it couldn't read is written as *unknown*,
  never defaulted to a plausible zero. A log that quietly invents data
  is worse than no log, because you'll trust it.

**Transitions, not states.** Every event fires on a *change*. A rune
lying on the floor for thirty ticks produces **one** `item.dropped`, not
thirty — so the log stays a readable record of what happened, not a
firehose of what merely *was*. This is the difference between a log you
skim in a minute and one you drown in.

**Observability is a feature, not overhead.** It's tempting to treat
logging as something you bolt on when debugging. This cycle made it
**mandatory and always-on**, because the run you most want to understand
is the one you didn't know would fail — and you only get to record that
run once, live. The measured cost (guarded reads, skipped entirely when
the log is off) is trivial; the cost of *not* having the record is
another 144-second mystery.

## Where it shows up

`pd2bot/runlog.py` (the writer + the reader/renderer),
`docs/architecture/run-log.md` (every event kind, for the next agent who
was not here). The events are emitted from the executor
(`action.*`), the engine (`tick`, `step.decision`, `refusal`), the
steps (`item.*`), and the layers (`stash.*`, `npc.*`, `waypoint.*`,
`area.transition`). Deliberately **not** recorded: enemy deaths, and the
`item.vanished`/`item.accidental` refinements — deferred, and named in
the archived plan's notes so their absence never reads as a silent bug.
