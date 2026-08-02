# 002 — Frontier edge sampling can miss a narrow doorway (P3)

**Where:** `pd2bot/survey.py`, `frontier_targets` (`EDGE_STRIDE = 8`).

**What:** room edges are probed every 8 subtiles; a doorway narrower
than the stride, sitting between two wall-faced samples, is never
offered as a frontier — the area can read "0 frontier open" with a
room genuinely reachable only through that door.

**Why it matters (mildly):** a premature "done" understates coverage.
In practice tonight's areas closed correctly (the walkable-scan behind
each sample absorbs most misalignment), and manual T52 walks bypass
the issue entirely.

**Suggested fix:** probe at stride AND at each edge's endpoints, or
drop the stride to 4 for the walkable scan only. Cheap; fold into the
next survey-touching phase (P5 is adjacent).

**Validation:** a unit test with a 4-subtile door centered between
stride samples must list the frontier.
