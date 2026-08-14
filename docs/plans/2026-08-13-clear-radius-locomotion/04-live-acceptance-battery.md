# P4 — live acceptance battery

Size: sm. Dependencies: P1, P2, P3 all complete, suite green.
Review gate: **YES — end of phase, operator verdict (see below).**

## Scope

Three ordinary Cold Plains runs under the new locomotion, measured
against both standing benchmarks. Bounded tuning between runs. Nothing
lands as "faster" without these numbers.

## Standing mandate

The operator must be present; confirm presence BEFORE each launch (the
request protocol — this phase's launches are `execute` requests with
the next free R numbers). Launch method unchanged: bridge +
`tools/guarded-run.ps1` (watchdog enforced), abort available everywhere
("abort the test" in chat, or `tools\drill-cancel.ps1`).

## Protocol

1. Pre-flight: `python -m pd2bot.wiring --dry-run` via the bridge —
   confirm the describe() block shows the berserk default and the
   expected run steps.
2. Run 1: `tools/guarded-run.ps1 -Run runs\cold-plains.toml -Games 1`.
   Read `logs/runs/<newest>/events.jsonl` FIRST (the standing method
   note), then:

```
python -m pd2bot.runlog.locomotion logs/runs/<newest>
```

```
python -m pd2bot.runlog.compare logs/runs/<newest> logs/runs/20260813-083614-cold-plains
```

```
python -m pd2bot.runlog.compare logs/runs/<newest> logs/runs/20260813-192249-human-coldplains
```

3. Judge against the targets. If a target misses for a TUNABLE reason
   (leg length, restrike, budget constants): change exactly ONE knob,
   note it in notes.md with the number it is meant to move, and run
   again — max two tuning iterations beyond the three planned runs.
   If a target misses for a STRUCTURAL reason (a new stall family, a
   safety interaction, berserk dying): STOP, report, do not improvise.
4. Runs 2 and 3 (or post-tuning runs): same measurement; the
   acceptance claim is made on three consecutive clean runs under one
   configuration.

## Acceptance targets (R256 QB, operator-set)

Per run, Cold Plains segment:

- **duration < 180 s**
- **zero ticks over 4 s** (locomotion report `--slow-tick 4`)
- **idle < 45 s**

Also record (no pass/fail, for the record and the P5 re-pricing):
effective speed, gross-vs-net route ratio, combat exposure, kills by
drop count if visible, pickup census (`runlog --pickup`), chicken/
monitor silence, watchdog stalls if any (the 15 s grace is standing).

## Watch specifically

- **Berserk survival**: hp minimums per run (the ladder owns survival —
  R241's validation was shorter than a full clearance; this battery is
  its endurance test). Any chicken or death latch = structural stop.
- **Budget false-negatives**: `nav.plan` events with
  `budget_exhausted=true` — each one, check whether the target was
  genuinely unreachable (write-off fine) or a real path was refused
  (constant too low: that is a tunable-knob iteration).
- **The old stall families**: nav.failed count, longest tick, longest
  idle span — all should collapse relative to the baseline.

## Review gate (end of phase)

Present to the operator, as one `verify` request:

1. The three-run numbers table vs targets, vs old baseline, vs human.
2. Every tuning change made and why.
3. The berserk survival record (hp minima, ladder fires).
4. Ask: do the numbers pass, AND does it look right from the chair
   (the burst/backtrack/dither list from R255 — gone, reduced,
   unchanged)? The operator's eye is part of acceptance.

## Reminders

- Do not commit unless asked. Do not expand scope. Report every run's
  outcome honestly (a failed run is data, not an embarrassment).
- Log every launch request in the instruction log at issue time.

## Definition of done

Three consecutive clean runs under one configuration meeting all three
targets, the record in notes.md, and the operator's gate verdict
requested (the verdict itself may arrive after this phase's work ends).
