"""T11 — snake-sweep inventory calibration (dense pass), user-designed.

The four-corner pass (T10) fitted the grid from four points; this verifies
that fit at EVERY usable cell, which is what catches a non-uniform pitch,
a gutter between sections, or an extent the corners mis-implied.

No hovering: D2 moves an item by click-to-pick and click-to-place, and both
clicks land INSIDE the cell involved. The body watches the tracked potion
flip between 'inventory' and 'cursor' and records the cursor position at
each flip — up to two samples per cell per visit, uniformly spread within
the cell instead of aimed at its centre. Per-cell means + a least-squares
fit over the whole sweep beat four aimed hovers precisely because the error
here is random, not the systematic aiming bias T8/R58 exposed.

Run through the bridge (from the repo root):
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t11_snake_sweep
"""

import sys
import time
from pathlib import Path

# Drills are scripts, not package members: invoked as a file, sys.path[0] is
# drills/ and pd2bot is invisible (T11's first launch died exactly there).
# One line makes every invocation style work.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.items import read_carried_items  # noqa: E402

POLL_S = 0.05  # 20 Hz — the cursor barely moves between samples
IDLE_FINISH_S = 20.0
MIN_CELLS = 6
SWEEP_BUDGET_S = 900.0

DRILL = Drill(
    test_id="T11",
    title="Snake-sweep inventory calibration",
    kind="human calibration",
    instructions=(
        "Open INVENTORY and put ONE potion from the belt in the TOP-LEFT usable cell.",
        "Then move it cell by cell: RIGHT along the row, DOWN one, LEFT along "
        "the next row - snaking through every cell. With 4 rows the sweep "
        "ends at the BOTTOM-LEFT (user correction, R61 post-run).",
        "I record silently at each pick-up and put-down. Stop moving when done; "
        "I finish after 20s of stillness.",
    ),
)


def fit(points):
    """Least-squares a + b*cell over (cell, fraction) pairs."""
    n = len(points)
    if n < 2:
        return None, None
    sx = sum(c for c, _ in points)
    sy = sum(f for _, f in points)
    sxy = sum(c * f for c, f in points)
    sxx = sum(c * c for c, _ in points)
    denominator = n * sxx - sx * sx
    if denominator == 0:
        return None, None
    b = (n * sxy - sx * sy) / denominator
    return (sy - b * sx) / n, b


def tracked_state(run: DrillRun, uid: int):
    """('inventory', cell) | ('cursor', None) | (None, None)."""
    carried = read_carried_items(run.session)
    for item in carried.inventory:
        if item.unit_id == uid:
            return "inventory", item.position
    held = carried.cursor_item
    if held is not None and held.unit_id == uid:
        return "cursor", None
    return None, None


def body(run: DrillRun) -> str:
    baseline = set(run.inventory_container())
    start = run.await_new_inventory_item(
        baseline, "Waiting for a potion in the TOP-LEFT usable cell..."
    )
    if start is None:
        raise DrillAborted("no starting potion appeared")
    tracked = start.unit_id
    print(f"tracking item {tracked} (kind {start.kind}) from {start.position}", flush=True)
    run.say("Tracking it - snake away. I record silently.")

    samples: dict[tuple[int, int], list[tuple[int, int]]] = {}
    visited: list[tuple[int, int]] = []
    state, cell = tracked_state(run, tracked)
    previous_cursor = run.cursor()
    last_change = time.time()
    end_by = time.time() + SWEEP_BUDGET_S

    while time.time() < end_by:
        now_cursor = run.cursor()
        new_state, new_cell = tracked_state(run, tracked)
        if new_state != state or (new_state == "inventory" and new_cell != cell):
            # The click that caused this transition happened at (or within a
            # frame of) the PREVIOUS cursor sample.
            if state == "inventory" and new_state == "cursor" and cell is not None:
                samples.setdefault(cell, []).append(previous_cursor)
            elif new_state == "inventory" and new_cell is not None:
                samples.setdefault(new_cell, []).append(previous_cursor)
                if new_cell not in visited:
                    visited.append(new_cell)
                    print(f"cell {new_cell} visited ({len(visited)})", flush=True)
            state, cell = new_state, new_cell
            last_change = time.time()
        if (
            len(visited) >= MIN_CELLS
            and time.time() - last_change > IDLE_FINISH_S
            and state == "inventory"
        ):
            break
        previous_cursor = now_cursor
        time.sleep(POLL_S)

    if len(visited) < MIN_CELLS:
        raise DrillAborted(f"only {len(visited)} cells seen — sweep never happened")

    # -- the fit and the verdict --------------------------------------------------
    rect = run.window.client_rect()
    centres = {
        cell_key: (
            sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points),
            len(points),
        )
        for cell_key, points in samples.items()
    }
    origin_fx, cell_fx = fit(
        [(c[0], (mx - rect.left) / rect.width) for c, (mx, _, _) in centres.items()]
    )
    origin_fy, cell_fy = fit(
        [(c[1], (my - rect.top) / rect.height) for c, (_, my, _) in centres.items()]
    )

    xs = sorted({c[0] for c in centres})
    ys = sorted({c[1] for c in centres})
    print(f"\n== {len(visited)} cells, {sum(len(v) for v in samples.values())} samples ==")
    print(f"cells spanned: x {min(xs)}..{max(xs)}  y {min(ys)}..{max(ys)}")
    missing = [
        (x, y)
        for y in range(min(ys), max(ys) + 1)
        for x in range(min(xs), max(xs) + 1)
        if (x, y) not in centres
    ]
    if missing:
        print(f"cells never visited: {missing}")

    print(f"\ninventory_origin = ({origin_fx:.4f}, {origin_fy:.4f})")
    print(f"inventory_cell   = ({cell_fx:.4f}, {cell_fy:.4f})")
    print(f"  pitch in px: ({cell_fx * rect.width:.1f}, {cell_fy * rect.height:.1f})")

    print("\nper-cell residual (predicted centre - measured mean, px):")
    worst, worst_cell = 0.0, None
    for cell_key in sorted(centres, key=lambda c: (c[1], c[0])):
        mean_x, mean_y, count = centres[cell_key]
        px = rect.left + (origin_fx + cell_key[0] * cell_fx) * rect.width
        py = rect.top + (origin_fy + cell_key[1] * cell_fy) * rect.height
        dx, dy = px - mean_x, py - mean_y
        if max(abs(dx), abs(dy)) > worst:
            worst, worst_cell = max(abs(dx), abs(dy)), cell_key
        print(f"  {cell_key}: ({dx:+6.1f}, {dy:+6.1f})  n={count}")
    print(
        f"worst residual {worst:.1f} px at {worst_cell} — click samples land "
        "anywhere inside a cell, so up to ~half the pitch on one cell is "
        "normal; systematic drift along a row/column is what would matter"
    )

    # Compare with T10's four-corner fit (the shipped TownConfig defaults).
    t10_origin, t10_cell = (0.5257, 0.4404), (0.0273, 0.0467)
    d_origin = (
        (origin_fx - t10_origin[0]) * rect.width,
        (origin_fy - t10_origin[1]) * rect.height,
    )
    d_cell = (
        (cell_fx - t10_cell[0]) * rect.width,
        (cell_fy - t10_cell[1]) * rect.height,
    )
    print(
        f"\nvs T10: origin delta ({d_origin[0]:+.1f}, {d_origin[1]:+.1f}) px, "
        f"pitch delta ({d_cell[0]:+.2f}, {d_cell[1]:+.2f}) px/cell"
    )

    return (
        f"{len(visited)} cells, {sum(len(v) for v in samples.values())} samples; "
        f"origin ({origin_fx:.4f}, {origin_fy:.4f}), cell ({cell_fx:.4f}, {cell_fy:.4f}); "
        f"worst per-cell residual {worst:.1f} px; "
        f"origin delta vs T10 ({d_origin[0]:+.1f}, {d_origin[1]:+.1f}) px"
    )


if __name__ == "__main__":
    raise SystemExit(0 if run_drill(DRILL, body) == "PASS" else 1)
