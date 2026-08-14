---
kind: implementation-log
status: done
repo: 2026-pd2-offline-bot
plan: plan.md
completed: 2026-08-09
commit: fa56adb
adrs: []
---

# Done — dependency pinning

## Outcome

**Complete.** Installs are reproducible (curated 8-package exact-pin
`requirements.txt`, one install command everywhere) and the early-warning
signal survives (weekly unpinned canary job). All acceptance criteria
met; the canary's first real firing is deferred by GitHub's
default-branch rule, as the plan predicted.

## Completed work

- `requirements.txt` — 8 packages exact-pinned from the known-good
  venv, hand-curated (cmake/ninja stowaways excluded, with a comment
  warning against bare `pip freeze` regeneration).
- `.github/workflows/ci.yml` — `checks` installs from the lockfile;
  new `canary` job (schedule Mondays 09:00 UTC + workflow_dispatch,
  unpinned install, same checks, never required by branch protection);
  concurrency group gains the event name.
- `README.md` — one-command install, the four-step update ritual, the
  canary sentence in the CI paragraph.
- `pyproject.toml` — pointer comment: floors are intent, the lockfile
  is the authoritative set.

## Validation

- **Local fresh-machine proof**: scratch venv built from ONLY
  `requirements.txt` → `pip freeze` shows exactly the 8 pinned
  packages; `pytest -q` 1169 passed; `ruff check .` clean.
- **Live**: pushed `fa56adb`; CI `checks` job **success** installing
  from the lockfile on a fresh windows-latest runner; `canary` job
  **skipped** on the push event — the gating is correct.

## Deviations from the plan

None.

## Documentation

README (above); teach explainer
`docs/learning/2026-08-09-dependency-pinning.md`; glossary gained
**lockfile / pinning**, **canary**, **transitive dependency**.

## ADRs

None — as planned; standard practice at minimal scale, alternatives
recorded in notes.md, cheap to reverse.

## Follow-up (outside scope)

- **After the M6 merge to `main`**: confirm the canary actually fires
  the following Monday (or trigger it once by hand:
  `gh workflow run ci.yml`). Schedules only run from the default
  branch, so it is dormant until then.
- Future work recorded in notes.md: hash-pinning, uv/pip-tools,
  Dependabot.
