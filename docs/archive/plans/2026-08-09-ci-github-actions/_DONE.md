---
kind: implementation-log
status: done
repo: 2026-pd2-offline-bot
plan: plan.md
completed: 2026-08-09
commit: 220aa2a
adrs: []
---

# Done — CI (GitHub Actions)

## Outcome

**Complete and live-proven.** Every push now runs pytest + ruff on a
`windows-latest` runner. The first run went green in ~40 s (34 s for the
push event, 44 s for the concurrent pull_request event on the open
m6-countess PR — both passed). Acceptance criteria 1–2 met on the first
attempt.

## Completed work

- `.github/workflows/ci.yml` — as planned: windows-latest, push (all
  branches) + PRs-to-`main` triggers, per-branch cancellation of
  superseded runs, `pip install pymem pytest ruff` (no editable
  install), pytest and ruff as separate failing steps.
- `README.md` — CI paragraph under Development setup, including the
  boundary statement (offline half only; offsets/calibrations stay with
  `pd2bot.dump` and the drills).

## Validation

- Local pre-push: `pytest -q` → 1169 passed; `ruff check .` → clean.
- Live: pushed `220aa2a`, watched run 31307902345 with
  `gh run watch --exit-status` → **success**; the parallel push-event
  run 31307901843 also **success** (34 s). Real cost far below the
  planned 4–6 billed-minute estimate.

## Deviations from the plan

- **Action versions bumped after the green run** (`checkout@v4→v5`,
  `setup-python@v5→v6`): the first run annotated both actions with a
  Node 20 deprecation warning that would recur on every run. The bump
  rides in the closeout commit, which itself triggers CI and validates
  it. Two-line change, inside the spirit of "do not suppress warnings —
  fix them".
- None otherwise; the YAML shipped as written in the plan.

## Documentation

- README (above); glossary CI entry updated (no longer "the missing
  piece") plus a **runner** definition; teach explainer
  `docs/learning/2026-08-09-continuous-integration.md`.

## ADRs

None — as planned. The Windows-runner constraint is a fact of the
codebase, documented in the workflow comment and notes.md, not a choice
among alternatives.

## Follow-up (outside scope, recorded in notes.md)

- Branch protection on `main` (require green CI before merge) — GitHub
  settings, one-time, worth doing at the next milestone merge.
- README status badge — cosmetic.
- pip caching — only if runs ever get slow; at ~40 s they are not.
