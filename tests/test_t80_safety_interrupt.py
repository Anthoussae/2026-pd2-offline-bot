"""T80's verdict logic, offline.

The drill itself needs the game; its criteria do not, and they are the
part worth pinning. The one that matters most is the third: a walk that
never started would raise instantly and "pass" while proving nothing.
That is the shape of failure this repo has paid for repeatedly — a test
that can pass without doing the thing it tests — so it lives in the
criteria rather than in a comment.
"""

from __future__ import annotations

from drills.t80_safety_interrupt import CAP_SLACK_S, PROMPT_S, verdict
from pd2bot.navigate import WALK_BUDGET_SECONDS

GOOD_CAP = WALK_BUDGET_SECONDS
GOOD_LATENCY = 0.1
MOVED = 12


def test_a_clean_run_passes():
    status, why = verdict(GOOD_CAP, GOOD_LATENCY, MOVED)
    assert status == "PASS"
    assert "0.10s after arming" in why


def test_a_walk_that_held_the_caller_too_long_fails():
    status, why = verdict(
        WALK_BUDGET_SECONDS + CAP_SLACK_S + 1.0, GOOD_LATENCY, MOVED
    )
    assert status == "FAIL"
    assert "budget" in why


def test_no_interrupt_at_all_fails():
    status, why = verdict(GOOD_CAP, None, MOVED)
    assert status == "FAIL"
    assert "no SafetyInterrupt" in why


def test_a_slow_interrupt_fails():
    status, why = verdict(GOOD_CAP, PROMPT_S + 0.5, MOVED)
    assert status == "FAIL"
    assert "to arrive" in why


def test_it_cannot_pass_on_a_walk_that_never_moved():
    """An instant interrupt against a stationary character proves the
    poll is wired, and nothing about whether a walk IN FLIGHT can be
    interrupted — which is the whole question."""
    status, why = verdict(GOOD_CAP, 0.0, 0)
    assert status == "FAIL"
    assert "not in flight" in why


def test_every_problem_is_reported_not_just_the_first():
    status, why = verdict(999.0, None, 0)
    assert status == "FAIL"
    assert "budget" in why and "no SafetyInterrupt" in why and "not in flight" in why
