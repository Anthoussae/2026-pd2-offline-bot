# Notes — CI (GitHub Actions) for this repo

Created 2026-08-09. Planning artifact for adding continuous integration:
run the offline checks (pytest + ruff) automatically on every push.

## Initial understanding

- The repo has strong offline checks (1169 tests, ruff clean as of
  today) but nothing runs them automatically; the `/yona-push` workflow
  runs them by discipline. CI closes the "forgot to run the tests"
  and "works only on my machine" gaps.
- Origin: chat discussion 2026-08-09 (structure assessment named "no CI"
  as the cheapest missing best practice; user asked to plan it).
- Expected shape: one workflow file under `.github/workflows/`.

## Discovery findings

- **Tests and lint are green locally**: `pytest -q` → 1169 passed in
  ~7 s; `ruff check .` → all checks passed. CI would start green.
- **Windows runner is required, not optional.**
  `pd2bot/window.py:20` and `pd2bot/input.py:42` evaluate
  `ctypes.windll` at module import time; `windll` does not exist on
  Linux/macOS, and the test suite imports these modules (e.g.
  `tests/test_input.py`). On `ubuntu-latest` collection would die at
  import. `runs-on: windows-latest` gives full parity with the dev
  machine instead.
- **The repo is PRIVATE** (`gh repo view` → PRIVATE). Consequences:
  GitHub Actions minutes are metered (free plan: 2,000 min/month) and
  Windows runners bill at 2× — effectively 1,000 Windows-minutes/month.
  A run should cost ~2–3 wall minutes (checkout + Python + pip install
  + 7 s of tests) → ~4–6 billed minutes per push. Dozens of pushes a
  month fits comfortably; pip caching keeps it down.
- **Default branch is `main`**; day-to-day work happens on milestone
  branches (currently `m6-countess`) pushed to origin, with PRs at
  milestone boundaries. So the trigger should be `push` on all branches
  plus `pull_request` targeting `main`.
- **Install story**: `pyproject.toml` deliberately has no build system
  (editable install crawls the OneDrive folder; see its comment), so CI
  must NOT `pip install -e .`. The README's recipe is the contract:
  `pip install pymem pytest ruff`, then run from the repo root
  (pytest's `pythonpath = ["."]` handles imports).
- **Python version**: `requires-python = ">=3.12"`; dev machine venv is
  3.12. Pin CI to 3.12 to test what's actually used.
- **Configs already centralised** in `pyproject.toml` (`testpaths`,
  ruff excludes for `spike/` and `kolbot/`), so the workflow is just
  two commands; no flags needed.
- `kolbot/`, `maps/`, `logs/` are gitignored, so the CI checkout is
  small and never sees them.

## Questions

- Q1–Q5 confirmation batch issued as R236 (runner OS, triggers, Python
  pin, install method, ruff as a failing check) — see instruction log.

## User answers / scope changes

- R236 answered **"yes all"** (2026-08-09): Q1 `windows-latest`, Q2
  push on all branches + PRs to `main`, Q3 Python pinned to 3.12,
  Q4 README install recipe (no editable install), Q5 ruff failures
  fail the build. No overrides; plan written to these answers.

## Out of scope / future work

- Branch protection on `main` (require green checks before merge) — a
  GitHub settings change, not a repo file; natural follow-up once CI
  exists.
- A badge in README.md showing CI status — cosmetic, cheap, optional.
- CI cannot verify live-game truths (memory offsets, calibrations);
  that remains the drills' job. No attempt to change that boundary.
