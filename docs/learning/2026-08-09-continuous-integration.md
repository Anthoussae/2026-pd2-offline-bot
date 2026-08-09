# Continuous integration — 2026-08-09

*Cycle: added GitHub Actions CI — every push now runs the full test
suite and the linter automatically on a rented Windows machine.*

## The big idea

Until today, this repo's checks (1169 tests, ruff) ran only when someone
typed the command. That is a discipline, and disciplines slip. The fix
is **continuous integration (CI)**: a service that notices every push to
GitHub, runs the checks itself on a fresh machine, and stamps the commit
green or red. Nothing about the checks changed — what changed is *who
is responsible for remembering them*: a machine now, instead of us.

## Key concepts

**The workflow file is the whole thing.** CI here is one 25-line text
file, `.github/workflows/ci.yml`. GitHub watches that path by
convention; anything in it describes when to run (every push, plus pull
requests into `main`) and what to run (install three packages, run
pytest, run ruff). There is no server to set up — pushing the file *is*
the setup.

**A fresh machine is the point, not a detail.** Each run starts on a
brand-new rented machine (a **runner**) that downloads the repo and
installs everything from scratch. That is slower than your PC but
catches what your PC structurally cannot: code that only works because
of an uncommitted file or something installed locally long ago. CI
tests *the commit*, not *your machine*.

**The runner's operating system is a real decision.** GitHub's default
runners are Linux (cheaper, faster to boot). This project cannot use
them: the bot imports Windows-only APIs (`ctypes.windll`) the moment its
modules load, so on Linux the test suite fails before a single test
runs. The workflow says `runs-on: windows-latest` — and this was
discovered by reading the imports during planning, not by pushing and
watching it fail.

**The push is the validation.** A CI setup cannot be proven locally, by
definition — the entire feature is "GitHub does something when a push
arrives." So acceptance was: push it, watch the first run, see green.
It ran in about 40 seconds and passed.

Glossed over honestly: caching (reusing installed packages between runs
— skipped as not worth it at 40 s/run), branch protection (making GitHub
*refuse* to merge red PRs — a settings change, deferred), and CD, the
"deployment" half of "CI/CD", which a bot running on your own PC does
not need.

## What we did, in these terms

Wrote the workflow file, added a README paragraph stating the boundary
(CI proves the offline half only — memory offsets and calibrations still
need the live game and the drills), pushed, and watched the first two
runs go green: one for the push itself, one because an open pull request
into `main` also re-checks its branch on every push.

## Where you'd meet this professionally

Everywhere, without exception — CI is as universal as version control.
On a professional team, a red CI check means your change may not merge,
full stop, and "don't break the build" is a social norm with your name
attached to the failing commit. Interviewers routinely ask about it, and
"I set up GitHub Actions for my project, chose the runner OS for a
platform-bound codebase, and know what CI can and cannot verify" is a
concrete, credible thing to be able to say.
