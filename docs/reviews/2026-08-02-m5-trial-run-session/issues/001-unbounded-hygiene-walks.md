# 001 — Cleanse hygiene walks were unbounded (P1) — FIXED IN-REVIEW

**Where:** `pd2bot/behavior/steps.py`, `maybe_cleanse` (both the
step-off-the-pile and walk-clear-of-wanted-item branches).

**What was wrong:** both hygiene walks looped on "the send succeeded".
A walk clamped at a wall ARRIVES (the honest-arrival rule) without
gaining an inch, so a boxed-in bot would send a fresh MoveTo every tick
forever. Every tick acts, so idle-bail and the refusal limit are both
blind — the same livelock shape as the survey's fight gate, found the
same night it was fixed there.

**Why it matters:** the R173 incident showed what a pinned character
costs (chicken at 49% after minutes in fire). This was the newest code
reintroducing the session's own signature bug class.

**Fix (applied):** hygiene-walk patience on RunServices — progress is
distance-from-repel-point GROWING; `patrol_attempts` progress-free
walks spend the patience and the hygiene yields (drops anyway / clears
the pile marker). One risky drop beats a pinned character.

**Validation:** `test_a_walk_away_that_gains_nothing_spends_its_patience`
and `test_a_step_off_that_gains_nothing_spends_its_patience` — both
fail against the pre-fix code (clamped executor, no player movement)
and pass now; full suite green.
