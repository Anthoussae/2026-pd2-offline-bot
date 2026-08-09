# Dependency pinning — 2026-08-09

*Cycle: locked the project's dependencies to exact versions in a curated
`requirements.txt`, with a weekly CI canary that still tests the latest
versions.*

## The big idea

"Install pymem, pytest, ruff" names *what* the project needs but not
*which versions* — so two installs months apart can produce different
environments, and "works here, fails there" follows. The fix is
**pinning**: writing exact versions (`pytest==9.1.1`) so every install —
yours, CI's, a new machine's — reproduces the environment that was
actually validated. A file that records the exact versions of everything
is a **lockfile**; ours is `requirements.txt`, installed with one
command.

## Key concepts

**Transitive dependencies.** You asked for three packages, but pytest
itself depends on five others (colorama, iniconfig, packaging, pluggy,
Pygments) — dependencies of your dependencies, which pip installs
without asking. Real reproducibility means pinning these too: eight
packages, not three. The lockfile is where the *full* graph lives; the
three direct dependencies stay declared loosely in `pyproject.toml` as
the human-readable statement of intent.

**A lockfile must be curated, not dumped.** The obvious shortcut —
`pip freeze > requirements.txt`, "write down whatever is installed" —
would have locked in `cmake` and `ninja`, build tools installed into the
same venv months ago for the C++ map-generator side-project. A venv
accumulates history; the lockfile must record what the project *needs*,
not what the venv *contains*. Ours says so in a comment, because the
shortcut will look tempting again someday.

**Pinning trades away a signal, so we bought the signal back.** While CI
installed "latest" on every push, a breaking new release of pytest would
have announced itself immediately. Pins silence that: CI now always
installs the known-good set. The compensation is a **canary** job — same
checks, but installing the latest unpinned versions, on a weekly
schedule. Red canary means "a new version breaks us; deal with it at
leisure" — it never blocks merges, because branch protection only
requires the pinned job. (Same idea as a canary release in deployment:
expose a small, expendable thing to danger first.)

**The update ritual.** A lockfile without a documented update path just
rots. Ours is four steps in the README: upgrade the package in the venv,
run the checks, edit the pin to match, push — and CI re-proves the new
set on a fresh machine.

Glossed over honestly: hash-pinning (locking the *contents* of each
package, not just the version — supply-chain protection) and lockfile
tools like `uv` or `pip-tools` that automate all this; both deliberately
skipped as heavyweight for eight packages, both recorded as future work.

## What we did, in these terms

Wrote the curated 8-package lockfile from the known-good venv; proved it
by building a throwaway venv from *only* that file and running all 1169
tests green; switched README and CI to install from it; added the weekly
canary job; documented the ritual. The scheduled canary stays dormant
until the workflow reaches the default branch at the M6 merge — GitHub
only fires schedules from there.

## Where you'd meet this professionally

Universally, one rung above CI: virtually every professional codebase
pins its dependencies somehow (lockfiles are built into npm, cargo, and
poetry/uv), and "the build is reproducible" is assumed table stakes.
The reproducibility-vs-freshness tension is real and teams solve it
exactly this way — pinned builds plus a scheduled job or a bot
(Dependabot/Renovate) watching for upstream movement. Knowing *why* the
lockfile exists, what transitives are, and why you never bare-freeze a
shared venv is working professional literacy.
