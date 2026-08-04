# Building the workflow itself — 2026-08-01

*Cycle: M5 P6 (R169/R170) — the workflow overhaul: the Drill Kit test
protocol, the Partyline chat channel, the turn-end alert, the numbered
request log, and the self-starting elevated bridge.*

## The big idea

This cycle wrote almost no bot behavior. It formalized *how we work*:
how tests start and stop, how the agent and the user talk while a game
is running, and how the human steps in the process get recorded. Teams
do this deliberately — the workflow is a system too, with its own bugs
(a test that starts before the user is ready, two bridges racing on one
queue, a request that never got written down), and it gets the same
treatment as code: name the parts, define the contracts, automate the
repetition.

## Key concepts

**Hook.** A place where a host program promises to run *your* code when
a defined event happens. Claude Code fires a "Stop" event when the
agent finishes a turn; we attached a script to it that queues a one-line
"done — your turn" into the game's chat. That is the whole pattern:
you do not modify the host, you register for its events. (Git has
hooks too — e.g. run the tests before every commit.)

**Handshake.** An explicit two-way exchange before something risky
begins, instead of one side just starting. An in-game test now
announces itself and then *waits for the user to type OK* — because a
test that begins the moment the announcement ends is betting the user
was ready, and lost that bet in practice. The related contract rule:
every test states how it *ends* before it starts (T51 run 1 was
aborted for lacking exactly this — the walker had no way to know they
were done).

**Whitelist.** The chat channel accepts exactly two commands — "ok" and
"abort" (plus spelling variants) — matched against a fixed list, and
only while a test is waiting or running. Everything else is ignored.
Reading free text and acting on it would make chat a command channel,
with all the trust problems that implies; a whitelist grants the
minimum capability the feature needs. The general principle is called
*least privilege*.

**Mutex (mutual exclusion).** The elevated bridge now starts itself at
logon, which created a new failure: a manually-started copy would give
two bridges racing to grab commands off one queue. The fix is a named
**mutex** — an operating-system object only one process can hold at a
time. The second bridge tries to take it, fails, and exits politely.
Any time "exactly one of these may run" matters, a mutex (or a lock,
its in-program cousin) is the tool.

**Toil, and measuring it.** Every request the agent makes of the human
now gets a number, a type (decision / execute / verify / provision /
inform), and two log entries. The point is not bureaucracy — it is
analytics on the human-in-the-loop load. Clusters of one type point at
their own remedy: many "execute" requests → automate that step; many
"verify" requests → build instrumentation so the tool can judge.
Repetitive manual work that automation could absorb is what the
industry (borrowing Google's term) calls **toil**, and logging it is
the first step to eliminating it.

## What we did, in these terms

We registered a **hook** for turn-end notifications; added a
**handshake** (the OK gate) and an end-condition rule to every live
test; constrained the new chat-command surface to a two-word
**whitelist**; made the bridge single-instance with a **mutex**; and
started measuring **toil** through the numbered request log. One design
choice worth noticing: the notification path *fails silent* on purpose
— an undeliverable "your turn" message is a non-event, and a helper
that fails loudly punishes the workflow it exists to speed up. Alerts
older than 30 seconds are dropped rather than delivered late, because a
stale notification is worse than none.

## Where you'd meet this professionally

Hooks are everywhere: git hooks, CI pipelines ("on every push, run the
tests"), webhooks between services, editor plugins. Handshakes underlie
deployment gates ("type the environment name to confirm") and network
protocols alike. Whitelisting inputs is a security fundamental you will
meet in code review the first time you parse anything a user typed.
Mutexes and locks appear in any concurrent code and in interviews. And
toil-tracking is standard practice in SRE (site reliability
engineering) teams, where "how many times did a human have to touch
this?" is a tracked metric with a budget.
