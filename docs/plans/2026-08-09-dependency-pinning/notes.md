# Notes — dependency pinning (lightweight lockfile)

Created 2026-08-09. Planning artifact for reproducible dependency
installs without heavy tooling. Origin: the structure assessment of
2026-08-09 named "no dependency lockfile" as a gap; user asked for a
best-practice-but-not-onerous solution.

## Initial understanding

- Today three surfaces each name the dependencies slightly differently:
  `pyproject.toml` (loose floors: `pymem>=1.14`, dev `pytest>=8`,
  `ruff>=0.6`), the README ("pip install pymem pytest ruff"), and the
  CI workflow (same unpinned trio). None is reproducible: a fresh
  install today and one in six months can get different versions.
- Counterweight to respect (from the task statement): CI installing
  latest currently doubles as an early-warning that a new pymem/pytest/
  ruff breaks the project. Pure pinning silences that signal.

## Discovery findings

- **The venv contains stowaways.** `pip freeze` on the known-good venv
  lists `cmake==4.4.0` and `ninja==1.13.0` — build tools from the
  d2mapapi_mod C++ side-project, not bot dependencies. A naive
  `pip freeze > requirements.txt` would lock them in. The lockfile must
  be curated, and the update procedure must not be "freeze whatever the
  venv has".
- **The real graph is 8 packages**: direct `Pymem==1.14.0` (no deps),
  `pytest==9.1.1` (transitives: colorama 0.4.6, iniconfig 2.3.0,
  packaging 26.2, pluggy 1.6.0, Pygments 2.20.0), `ruff==0.16.0` (no
  deps). Python 3.12.10, pip 25.0.1.
- **No editable install exists or may exist** (pyproject deliberately
  has no build system; the OneDrive-crawl comment explains it), so
  `pip install -r requirements.txt` is the natural single command — it
  replaces the README's ad-hoc trio without touching how the package
  itself is imported.
- **CI is one day old** (`.github/workflows/ci.yml`, archived plan
  `docs/archive/plans/2026-08-09-ci-github-actions/`): single `checks`
  job on windows-latest, installs the unpinned trio. Repo went PUBLIC
  today → Actions minutes now free, so an extra scheduled job costs
  nothing.
- Local suite green today: 1169 tests, ruff clean (so today's versions
  are a valid known-good set to pin).

## Direction (proposed)

Two-track, both cheap:

1. **`requirements.txt` — the curated lockfile.** All 8 packages, exact
   `==` pins, hand-curated from the known-good set, with comments
   marking direct vs transitive and the stowaway warning. README and CI
   both switch to `pip install -r requirements.txt`. `pyproject.toml`
   keeps its loose floors as the human-readable *intent* (direct deps
   only), with a comment pointing at the lockfile as the derived,
   authoritative install set. Documented update ritual: bump in venv →
   run checks → edit pins → push (CI re-proves on a fresh machine).
2. **A weekly "canary" job keeps the early-warning signal.** A second
   workflow job (scheduled, Mondays) installs the UNPINNED trio and
   runs the same checks. Red canary = a new upstream version breaks us,
   discovered on schedule instead of mid-setup on a new machine; the
   pinned main job stays green throughout, so the badge and merges are
   unaffected. This resolves the reproducibility-vs-signal trade-off
   named in the task instead of picking a side.

Rejected as too heavy for 8 packages: pip-tools/uv/poetry lock
workflows (a second toolchain to learn and maintain), hash-pinning
(`--require-hashes`; real supply-chain value but meaningful ceremony —
noted as future work if the project ever grows contributors).

## Questions

- Q1–Q5 confirmation batch issued as R238 — see instruction log.

## User answers / scope changes

- R238 answered **"yes all"** (2026-08-09), with implementation
  requested in the same message ("then /yona-implement"). Q1–Q5 all as
  suggested; no overrides. The commit+push (required to validate the CI
  change, per the R237 precedent) is covered by the same instruction.
- Planning note discovered while designing the canary: **scheduled
  workflows only fire from the default branch**, so the Monday canary
  stays dormant until the M6 merge lands `ci.yml` on `main`. A
  `workflow_dispatch` trigger is added so it can also be fired by hand.

## Out of scope / future work

- Hash-pinned requirements (`pip-compile --generate-hashes`) if the
  dependency list or contributor count ever grows.
- Adopting `uv` wholesale (fast installer + lockfile in one tool) — the
  modern choice if tooling appetite ever changes; deliberately not now.
- Auto-update PRs (Dependabot/Renovate) — GitHub-native Dependabot
  would file version-bump PRs against requirements.txt; pairs well with
  the canary but adds PR noise a solo project may not want.
