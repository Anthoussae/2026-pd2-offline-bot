# The run event log: always-on, schema'd, append-only

Date: 2026-08-05 (M6 P4 → the run-event-log plan)
Status: **proposed** — accepted once P5 proves the log can answer a
question the old instrumentation could not.

## Context

On 2026-08-05 the bot spent **144 seconds in the Forgotten Tower** — a
19×19-subtile empty square room with one entrance and one exit, eleven
subtiles from the staircase it was trying to take — and gave the run up.
The investigation that followed could not say why, and the reason is
worth stating precisely, because it is an instrumentation failure rather
than a navigation one:

| Measure | Value |
|---|---|
| Ticks in the room | ~140–170 |
| Decisions recorded | **5** |
| Reflex fires (whole run) | 6, none in the room |

Everything else checked out. The atlas holds that room completely, A*
plans it as one leg, the map seed matches, and routing was never even
invoked because the staircase sat inside `click_range`. The bot was not
lost. **Nobody could tell what it was doing**, because five of roughly
one hundred and fifty decisions were written down.

What filled the vacuum was speculation. Two hypotheses were produced and
presented with more confidence than the evidence carried — "the entrance
fight owned the ticks" and "monsters were contesting the staircase" —
and the user killed both with one fact the log should have made
unnecessary: *that room never contains monsters*. A code change had
already been written on the strength of the second one.

That is the failure mode this ADR exists to prevent. The project's
existing logging surfaces are all prose or in-memory:

| Surface | Shape | Why it could not answer |
|---|---|---|
| `narrate.py` | `HH:MM:SS text` file | Deliberately coarse — "one line per meaningful act". Good story, not data. |
| `RunServices.log` | `print()` | stdout only; survives only if a drill captured it. Unstamped. |
| `EngineReport.log` | in-memory list | Records only ticks whose outcome carried a note. **This is the hole.** |
| Executor `trace` | in-memory list | Closest to an event log, never persisted. |
| `docs/drill-log.md` | markdown table | One row per run. Summary, not detail. |

Five surfaces, no schema, no uniform timestamp, nothing persisted as
data. Reconstructing a run means correlating prose across three
in-memory lists and one file — which is exactly how a reconstruction
becomes a story.

## Decision

**Every run writes a structured, append-only event log, and it is not
optional.**

1. **Format: JSONL**, one JSON object per line, appended and flushed per
   event so the file is readable while the bot runs and survives a
   crash. A renderer (`python -m pd2bot.runlog`) prints the human
   timeline. Data first, prose derived from it — never the reverse.
2. **Location: one directory per run**, `logs/runs/<stamp>-<runname>/`,
   holding `events.jsonl` and a `run.json` header (seed, character, run
   file, config, git sha). Every run kept; pruning is a later concern.
3. **Envelope on every event**: a monotonic `seq`, an ISO wall-clock
   `at` (what the operator saw), a monotonic `t` in seconds since run
   start (what arithmetic uses), and the area id + name.
4. **Three coordinate frames on every spatial event**: world subtiles
   (absolute), area-local (world − area origin, so the Tower reads as
   (6, 2) → (2, 13) rather than five-digit numbers), and
   character-relative with a Chebyshev distance and a **screen** compass
   bearing. Chebyshev because every reach, radius and budget in the
   codebase already uses it, so logged distances compare directly
   against `click_range`, `engage_radius`, `pickup_reach`. Screen-north
   is the world (−1, −1) diagonal (R219) — the operator's frame, defined
   once.
5. **Always on** (R220 Q11). `build_bot` opens a log unconditionally.
   The only silent path is an explicitly-passed `NullRunLog` for unit
   tests and the sim. Optional instrumentation means the one run you
   most need to explain is the one where the flag was forgotten — which
   is not a hypothetical, it is T71.
6. **Four rules the log obeys**, in its module docstring:
   - **Never raises.** A logging failure must not end a run.
   - **Never blocks.** Append and flush; no rotation, no network.
   - **Never interprets.** Record "clicked at X, player at Y", never
     "the click failed". Conclusions belong to the reader. This rule is
     the direct lesson of the two wrong diagnoses.
   - **Honest absence.** An unreadable field is `null` with a reason,
     never a plausible default. A guessed value in a diagnostic log is
     worse than no log at all.
7. **Names come from the existing code-anchored tables**
   (`item_ids.toml` + `item_codes.toml`), falling back to `kind <n>`.
   R144 — where a numeric review approved six wrong elite armours and
   the bot picked up a Wire Fleece believing it was a Kraken Shell — is
   why there must not be a second naming path.

## Alternatives considered

**Keep improving the prose narrative.** Tried, and it is the status quo
that failed. The narrative log is *deliberately* coarse — sparseness is
its stated value — so making it answer forensic questions would destroy
what it is good at. Both survive: the narrative is the story a human
skims, the event log is the record a tool queries (R220 Q8).

**Opt-in structured logging.** Rejected under Q11. Cheaper by default
and useless exactly when it matters.

**A database (SQLite).** Rejected. The queries wanted — filter by kind,
by time, by area — are served by grep and a renderer, and a schema
migration is a worse failure mode for a diagnostic tool than a
malformed line. JSONL degrades gracefully: a truncated file is still
readable up to the truncation.

**Python `logging` with a JSON formatter.** Rejected. The value here is
the *schema* — typed events with coordinate payloads — not the
transport, and `logging`'s global configuration is a poor fit for a
per-run file with a header.

## Consequences

**Good.** A run failure becomes a data question. The specific questions
T71 could not answer — what did each tick decide, where did the time go,
did the player move after each click, where did the click land on screen
— are all answerable from the record, without an agent in the loop and
without the conversation that produced it.

**Cost.** Tens of KB per run, and every new decision path must emit.
That second one is deliberate: **instrumentation is now part of the
definition of done for a behavior change**, not an optional extra. A
step that acts without recording what it did is the defect this ADR
names.

**Risk.** Timing instrumentation could distort what it measures; the
mitigation is one clock read per boundary, never a profiler. Volume
could make the log unreadable; the mitigation is renderer-side
collapsing of consecutive identical events, with volatile fields
excluded from the collapse key.

**Deliberately excluded.** Enemy-death events (R220 Q6, deferred by the
user as "might be too complicated"). The reliable signal is an observed
alive→corpse transition — a unit that merely stops appearing has left
perception, and logging that as a death would be exactly the kind of
false signal this ADR is trying to eliminate. The design is recorded in
the plan's `notes.md` for a later revival. Nothing in the log may claim
a kill until then.
