---
kind: plan
size: sm
depth: small
status: done
repo: 2026-pd2-offline-bot
created: 2026-08-09
completed: 2026-08-09
commit: 220aa2a
adr: none
---

# Plan — CI (GitHub Actions): run pytest + ruff on every push

## Size and why

`sm` — one new file, no code changes, no phases. One agent executes it
in one pass; the only multi-step part is validation (a push is required
to see the workflow run).

## Goal

Every push to GitHub automatically runs the offline checks — the full
pytest suite and `ruff check` — on a Windows machine, and marks the
commit green/red. This converts "we remembered to run the tests"
(discipline, via `/yona-push`) into a machine guarantee, and checks the
code *as committed* rather than as it sits in the working tree.

## Acceptance criteria

1. `.github/workflows/ci.yml` exists on the current branch and is valid
   (the push triggers a run instead of an "invalid workflow" annotation).
2. The first CI run completes **green** on `windows-latest`: checkout,
   Python 3.12, `pip install pymem pytest ruff`, `python -m pytest -q`
   (expect ~1169 passed), `python -m ruff check .`.
3. A deliberate failure is NOT required to accept (the suite passing on
   a fresh machine is the claim being bought), but if anything must be
   debugged, debug via the run logs (`gh run view --log-failed`), not by
   guessing.

## Scope

- One workflow file: `.github/workflows/ci.yml` (exact content below).
- A short README note under "Development setup" saying CI exists and
  what it runs.

## Out of scope (decided during planning — do not expand)

- Branch protection on `main` (a GitHub settings change; future work).
- A README status badge (cosmetic; future work, noted in notes.md).
- pip caching in the workflow (three tiny packages; not worth the
  config surface — revisit only if runs get slow).
- Anything touching live-game verification: CI covers exactly the
  offline half. Offsets/calibrations remain the drills' job; do not
  claim otherwise in docs.
- No changes to `pyproject.toml`, the test suite, or lint config.

## Discovery summary (details in [notes.md](notes.md))

- **Windows runner is forced**: `pd2bot/window.py:20` and
  `pd2bot/input.py:42` evaluate `ctypes.windll` at import time; the
  tests import these modules, so Linux runners cannot collect the
  suite. `runs-on: windows-latest` also matches the dev machine.
- **Private repo**: Actions minutes metered (2,000/month free), Windows
  bills 2×; ~4–6 billed minutes per push — comfortable.
- **Install contract is the README recipe**: `pip install pymem pytest
  ruff`, run from the repo root. `pyproject.toml` deliberately has no
  build system (its comment explains why) — **do not** `pip install -e .`.
- All check config is already centralised in `pyproject.toml`
  (`testpaths`, `pythonpath = ["."]`, ruff excludes for `spike/` and
  `kolbot/`), so the workflow needs no flags.
- Default branch `main`; work happens on milestone branches (currently
  `m6-countess`) with PRs at milestone boundaries → trigger on push
  (all branches) + `pull_request` targeting `main`. Locally green
  today: 1169 tests, ruff clean.
- User confirmations: R236 all yes (runner, triggers, 3.12 pin,
  install method, ruff fails the build).

## The workflow file

Write exactly this as `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:
    branches: [main]

# Metered minutes: if several pushes land quickly, only the newest
# commit's run survives per branch.
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  checks:
    # Not a preference: pd2bot touches ctypes.windll at import time,
    # so the suite cannot even be collected on Linux (see plan notes).
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      # The README recipe. Deliberately NOT an editable install —
      # pyproject.toml has no build system, by design.
      - run: pip install pymem pytest ruff
      - run: python -m pytest -q
      - run: python -m ruff check .
```

Notes for the implementer:

- Keep the two check steps separate (a ruff failure should be visibly
  distinct from a test failure in the run UI).
- A branch push that also has an open PR to `main` runs twice (push +
  pull_request events). Known and accepted — PRs only exist briefly at
  milestone boundaries.

## Docs to update

- `README.md`: 2–3 sentences under "Development setup" — CI runs
  pytest + ruff on every push via GitHub Actions on a Windows runner;
  it cannot verify live-game truths (offsets/calibrations), which stay
  with `pd2bot.dump` and the drills.
- No architecture docs change (CI is process, not bot behavior).

## ADR

`none` — this implements a standard practice with no plausible
alternative shapes worth recording (the Windows-runner constraint is a
fact, not a decision; it is documented in the workflow comment and
notes.md).

## Validation

Validation requires a commit and push (CI cannot run otherwise), so per
convention confirm with the user before committing; the natural shape is
one conventional commit on the current branch (`m6-countess`).

```bash
git add .github/workflows/ci.yml README.md docs/
```

Then commit, push, and watch:

```bash
gh run watch
```

or `gh run list --limit 1` / `gh run view --log-failed` if it fails.
Green run on this branch = acceptance criteria 1–2 met. (A later merge
to `main` needs nothing extra; the same workflow rides along.)

## Implementer reminders

- Do not commit without the user's go-ahead (the validation section
  makes this the one place to ask).
- Do not expand scope (badge, branch protection, caching are out).
- Do not suppress warnings or skip tests to get green — if the fresh
  Windows runner reveals a real environment assumption, stop and
  report; that finding is valuable.
- Record completion in `_DONE.md` per convention, then archive the plan
  dir; the teach step (`/teach`) closes the cycle — CI concepts are
  already in the glossary, so the explainer can be short or folded into
  the next cycle's.
