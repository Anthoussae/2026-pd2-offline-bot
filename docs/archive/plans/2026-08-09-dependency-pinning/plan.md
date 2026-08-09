---
kind: plan
size: sm
depth: small
status: done
repo: 2026-pd2-offline-bot
created: 2026-08-09
completed: 2026-08-09
commit: fa56adb
adr: none
---

# Plan — dependency pinning: a curated lockfile plus an unpinned canary

## Size and why

`sm` — one new file (`requirements.txt`) and three small edits (README,
`pyproject.toml`, `ci.yml`). One agent, one pass; validation ends with a
push (the CI change can only be proven by CI running it).

## Goal

A fresh install of this project — new machine, CI runner, six months
from now — produces byte-for-byte the same dependency versions as the
known-good set validated today, while a weekly canary job keeps the
early-warning signal that unpinned installs used to provide for free.

## Acceptance criteria

1. `requirements.txt` exists with all 8 packages exact-pinned to
   today's venv versions, curated (no `cmake`/`ninja` stowaways).
2. A scratch venv built ONLY from `requirements.txt` runs the full
   suite green from the repo root (local fresh-machine proof).
3. CI's `checks` job installs from `requirements.txt` and its first run
   on the new configuration is green (the runner is the real
   fresh-machine proof).
4. The canary job exists, is gated to `schedule`/`workflow_dispatch`
   events only, and is syntactically accepted by GitHub (the push does
   not produce a workflow-file error). Its first real firing is
   **deferred by design**: schedules only run from the default branch,
   so it goes live when M6 merges.
5. README documents the one-command install and the update ritual.

## Scope

- New `requirements.txt` (repo root).
- `README.md`: install command swap + update ritual + one canary
  sentence in the CI paragraph.
- `pyproject.toml`: pointer comment on the dependency tables (floors
  stay as they are — they are the intent, not the lock).
- `.github/workflows/ci.yml`: `checks` installs from the lockfile; new
  `canary` job; `schedule` (Mondays 09:00 UTC) + `workflow_dispatch`
  triggers; concurrency group gains the event name so a canary run and
  a push run never cancel each other.

## Out of scope (do not expand)

- pip-tools / uv / poetry / hash-pinning — rejected as heavy for 8
  packages; recorded in notes.md future work.
- Dependabot auto-update PRs — future work.
- Upgrading any dependency version today: the pins record the CURRENT
  green set (1169 tests, ruff clean). Bumps are their own future ritual.
- The venv's stowaways (`cmake`, `ninja`) are left installed — they
  belong to the d2mapapi_mod side-project; they are merely excluded
  from the lockfile.

## Discovery summary (details in [notes.md](notes.md))

Known-good set, Python 3.12.10: direct `Pymem==1.14.0` (no deps),
`pytest==9.1.1` (transitives `colorama==0.4.6`, `iniconfig==2.3.0`,
`packaging==26.2`, `pluggy==1.6.0`, `Pygments==2.20.0`),
`ruff==0.16.0` (no deps). The venv's `pip freeze` also shows
`cmake==4.4.0` and `ninja==1.13.0` — NOT bot dependencies; hence a
curated file, never a bare freeze. R238 all-yes; commit covered by the
same instruction.

## The files

### `requirements.txt` (new, repo root)

```text
# The locked dependency set. The ONE install command (README has the ritual):
#     pip install -r requirements.txt
# Direct dependencies — the intent behind these lives in pyproject.toml:
Pymem==1.14.0
pytest==9.1.1
ruff==0.16.0
# Transitive (pulled in by pytest), pinned so installs are fully reproducible:
colorama==0.4.6
iniconfig==2.3.0
packaging==26.2
pluggy==1.6.0
Pygments==2.20.0
# Never regenerate this file with a bare `pip freeze`: the dev venv carries
# non-bot tools (cmake, ninja — d2mapapi_mod build leftovers) that must not
# be locked in here.
```

### `ci.yml` changes

- Triggers gain:

```yaml
  schedule:
    - cron: "0 9 * * 1"  # Mondays 09:00 UTC — the unpinned canary
  workflow_dispatch:
```

- Concurrency group becomes
  `ci-${{ github.event_name }}-${{ github.ref }}`.
- `checks` gains `if: github.event_name != 'schedule' &&
  github.event_name != 'workflow_dispatch'` and installs with
  `pip install -r requirements.txt`.
- New `canary` job: same runner/steps but
  `if: github.event_name == 'schedule' || github.event_name ==
  'workflow_dispatch'` and the UNPINNED install
  (`pip install pymem pytest ruff`), with a comment stating its
  contract: red canary = a new upstream version breaks us; it never
  blocks merges (branch protection requires `checks` only).

### README changes (Development setup)

- Swap the `pip install pytest ruff pymem` line for
  `pip install -r requirements.txt`.
- Add the update ritual (3–4 lines): upgrade the package in the venv →
  run pytest + ruff → edit the pin(s) in `requirements.txt` → push and
  let CI confirm on a fresh machine. Never bare-freeze.
- One sentence in the CI paragraph: the weekly canary job checks latest
  unpinned versions so upstream breakage is noticed on schedule, not
  during setup on a new machine.

### `pyproject.toml` change

A comment above `[project]`'s `dependencies`: floors here are the
human-readable intent (direct deps only); `requirements.txt` is the
derived, authoritative install set — change versions there.

## Docs

README as above; no architecture docs (process change, not bot
behavior). Teach step closes the cycle: explainer on
lockfiles/transitive dependencies/the canary pattern, glossary entries
to match (`lockfile`, `transitive dependency`; the existing CI and
staged-rollout entries may gain cross-references).

## ADR

`none` — this is standard practice at the smallest sensible scale; the
alternatives rejected (heavier tooling) are recorded in notes.md, and
reversing the choice later is cheap. No lasting architectural
consequence beyond the files themselves.

## Validation

1. Local: build a scratch venv in the session scratchpad from ONLY
   `requirements.txt`; run `python -m pytest -q` and
   `python -m ruff check .` from the repo root with it. Expect 1169
   passed, clean.
2. Existing venv still green (unchanged, but cheap to confirm).
3. Commit + push (authorized by R238's "then /yona-implement");
   `gh run watch` the `checks` job — green proves the lockfile installs
   and passes on a real fresh Windows machine, and that the workflow
   edit parses.
4. Canary: confirm the job is SKIPPED on the push event (correct
   gating). Its live firing is deferred to post-M6-merge by GitHub's
   default-branch rule; record that in `_DONE.md` as a known follow-up
   check.

## Implementer reminders

- Do not commit before local validation passes.
- Do not expand scope (no version bumps, no extra tooling).
- Stop and report if the scratch-venv install surprises (e.g. a
  transitive pin conflicts) — that finding matters more than the plan.
- `_DONE.md` + archive + teach step close the cycle, per convention.
