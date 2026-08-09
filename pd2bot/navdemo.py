"""Live probes for the input layer — the human-in-the-loop calibration tool.

    python -m pd2bot.navdemo gate                # print the gate's verdict, send nothing
    python -m pd2bot.navdemo click-test          # predict only (no click)
    python -m pd2bot.navdemo click-test --send   # gated click 20 subtiles NE, compare

Requires Administrator, and --send requires you at the machine: it foregrounds
the game and sends one real click through the gate. Run `gate` in three states
(normal play / ESC menu open / window backgrounded) to see the gate refuse for
the right reasons — that is the M1 incident's regression test against reality.

click-test measures the projection: it predicts where the player will end up
if the isometric constants in screen.py are right, clicks, waits, and prints
predicted vs actual. A clean projection lands within a few subtiles.
"""

from __future__ import annotations

import argparse
import sys
import time

from pd2bot import offsets, screen
from pd2bot.input import GatedInput, InputRefused
from pd2bot.perception.memory import GameNotRunning, GameSession, NeedsAdministrator
from pd2bot.perception.units import player_unit, unit_position
from pd2bot.screen import projection_for
from pd2bot.window import WindowNotFound

# A hop big enough to measure, small enough to stay on screen and (usually)
# walkable: 20 subtiles toward +x (screen: down-right).
_TEST_OFFSET = (20, 0)
# The walk is over when the position stops changing for this long...
_SETTLED_SECONDS = 1.2
# ...but never watch longer than this (stuck against something).
_MAX_WATCH_SECONDS = 10.0


def _player_position(session: GameSession) -> tuple[int, int] | None:
    unit = player_unit(session)
    if unit is None:
        return None
    return unit_position(session, unit, offsets.UNIT_TYPE_PLAYER)


def cmd_gate(gated: GatedInput, focus: bool) -> int:
    """Print the gate's verdict, sending nothing.

    The three states worth testing and how to produce them:
    - blocking panel: open the ESC menu in game, alt-tab here, run plain
      `gate` — the panel check reads game memory, so focus does not matter.
    - not foreground: close all panels, run plain `gate` from this terminal
      (the terminal having focus IS the tested condition).
    - allowed: run `gate --focus` — the game must be foreground at the
      moment of the check, and you cannot be pressing Enter here while it
      is, so the tool brings the game forward itself (exactly what the bot
      does before walking).
    """
    if focus:
        took = gated.window.bring_to_foreground()
        print(f"focus request: {'game is now foreground' if took else 'REFUSED by Windows'}")
    try:
        gated.check()
    except InputRefused as refused:
        print(f"gate: REFUSED — {refused}")
        return 0
    print("gate: input allowed (in game, no blocking panel, window foreground)")
    return 0


def cmd_click_test(gated: GatedInput, send: bool) -> int:
    session = gated.session
    start = _player_position(session)
    if start is None:
        print("not in a game — enter a game first", file=sys.stderr)
        return 1

    target = (start[0] + _TEST_OFFSET[0], start[1] + _TEST_OFFSET[1])
    rect = gated.window.client_rect()
    predicted_pixel = projection_for(start, rect).world_to_screen(*target)
    print(f"player at {start}, target {target}")
    print(f"client rect {rect}, predicted click pixel {predicted_pixel}")

    if not send:
        print("(dry run — pass --send to click)")
        return 0

    if not gated.window.bring_to_foreground():
        print("could not foreground the game window; nothing sent", file=sys.stderr)
        return 1
    try:
        used_pixel = gated.click_world(*target)
    except InputRefused as refused:
        print(f"gate refused: {refused}", file=sys.stderr)
        return 1
    print(f"clicked at {used_pixel}; watching until the character stops...")

    # Watch until the position is still for a while — a fixed window can cut
    # a slow walk short and fake an undershoot.
    hard_deadline = time.monotonic() + _MAX_WATCH_SECONDS
    last = start
    last_changed = time.monotonic()
    while time.monotonic() < hard_deadline:
        time.sleep(0.15)
        now = _player_position(session)
        if now is not None and now != last:
            last, last_changed = now, time.monotonic()
        elif time.monotonic() - last_changed >= _SETTLED_SECONDS:
            break
    still_moving = time.monotonic() >= hard_deadline

    error = (last[0] - target[0], last[1] - target[1])
    print(f"ended at {last}; target was {target}; error {error} subtiles"
          + ("  [WARNING: still moving at cutoff]" if still_moving else ""))

    # If the click's screen offset and the walked world offset disagree on
    # scale, that ratio IS the true pixels-per-subtile (e.g. the game
    # rendering at a lower resolution than the window and stretching).
    walked = (last[0] - start[0], last[1] - start[1])
    rect_center = rect.center
    screen_offset = (used_pixel[0] - rect_center[0], used_pixel[1] - rect_center[1])
    iso_x = walked[0] - walked[1]  # what the x-axis pixel offset divides by
    iso_y = walked[0] + walked[1]
    if abs(iso_x) >= 8 and abs(iso_y) >= 8:  # too short a walk = too noisy
        print(f"implied px/subtile: x {screen_offset[0] / iso_x:.2f} "
              f"(configured {screen.PX_PER_SUBTILE_X}), "
              f"y {screen_offset[1] / iso_y:.2f} "
              f"(configured {screen.PX_PER_SUBTILE_Y})")
        print("  (one short hop quantises to +/-1 subtile, so expect a couple of "
              "px of scatter around the configured values)")
    print("Error within ~2 subtiles: the projection is calibrated for this "
          "window. A consistent, systematic error instead means the render "
          "scale changed — re-run `navdemo calibrate`.")
    return 0


def _walk_and_measure(gated: GatedInput, pixel_offset: tuple[int, int]) -> tuple | None:
    """Click `pixel_offset` from the client centre, wait for the walk to
    finish, and return (offset, walked_subtiles). None if nothing moved."""
    session = gated.session
    start = _player_position(session)
    if start is None:
        return None
    rect = gated.window.client_rect()
    target_pixel = (rect.center[0] + pixel_offset[0], rect.center[1] + pixel_offset[1])
    try:
        gated.click_screen(*target_pixel)
    except InputRefused as refused:
        print(f"  skipped {pixel_offset}: {refused}")
        return None

    hard_deadline = time.monotonic() + _MAX_WATCH_SECONDS
    last, last_changed = start, time.monotonic()
    while time.monotonic() < hard_deadline:
        time.sleep(0.15)
        now = _player_position(session)
        if now is not None and now != last:
            last, last_changed = now, time.monotonic()
        elif time.monotonic() - last_changed >= _SETTLED_SECONDS:
            break

    walked = (last[0] - start[0], last[1] - start[1])
    if abs(walked[0]) + abs(walked[1]) < 4:
        print(f"  skipped {pixel_offset}: barely moved (blocked?)")
        return None
    return (pixel_offset, walked)


# Eight directions, all inside the reliable click radius. Different
# directions decorrelate the two axes; several samples average out the
# +/-1 subtile quantisation that makes any single measurement ambiguous.
_CALIBRATION_OFFSETS = [
    (320, 0), (-320, 0), (0, 160), (0, -160),
    (240, 120), (-240, 120), (240, -120), (-240, -120),
]

# Deliberately beyond it. These are NOT fitted — the first calibration run
# (2026-07-28) found long clicks complete only 60-70% of their distance,
# and including them dragged the fit badly. They are still walked, and
# reported separately, because the reach limit is worth re-checking: it is
# what sets the waypoint spacing cap.
_REACH_CHECK_OFFSETS = [(480, 0), (-480, 0), (360, 180), (-360, -180)]


def cmd_calibrate(gated: GatedInput) -> int:
    """Measure pixels-per-subtile by walking known screen offsets.

    Derivation, so the numbers can be checked: for a walk of (dx, dy)
    subtiles produced by a click at screen offset (ox, oy),
        ox = (dx - dy) * px_x      oy = (dx + dy) * px_y
    Each sample gives one equation per axis; the least-squares fit over all
    samples is px = sum(offset * iso) / sum(iso^2).
    """
    if not gated.window.bring_to_foreground():
        print("could not foreground the game window", file=sys.stderr)
        return 1

    total = len(_CALIBRATION_OFFSETS) + len(_REACH_CHECK_OFFSETS)
    print(f"calibrating with {total} short walks — keep clear of walls; "
          "samples that hit something are skipped\n")
    samples = []
    for offset in _CALIBRATION_OFFSETS:
        result = _walk_and_measure(gated, offset)
        if result is None:
            continue
        samples.append(result)
        (ox, oy), (dx, dy) = result
        print(f"  clicked ({ox:+5d},{oy:+5d})  walked ({dx:+4d},{dy:+4d})")

    if len(samples) < 4:
        print(f"\nonly {len(samples)} usable samples — move to open ground and retry",
              file=sys.stderr)
        return 1

    num_x = sum(ox * (dx - dy) for (ox, _), (dx, dy) in samples)
    den_x = sum((dx - dy) ** 2 for _, (dx, dy) in samples)
    num_y = sum(oy * (dx + dy) for (_, oy), (dx, dy) in samples)
    den_y = sum((dx + dy) ** 2 for _, (dx, dy) in samples)
    if not den_x or not den_y:
        print("\ndegenerate samples (all along one axis); retry", file=sys.stderr)
        return 1
    px_x, px_y = num_x / den_x, num_y / den_y

    # Residuals: how far each sample's prediction lands from what happened.
    errors = []
    for (ox, oy), (dx, dy) in samples:
        predicted_x = (dx - dy) * px_x
        predicted_y = (dx + dy) * px_y
        errors.append(max(abs(predicted_x - ox) / px_x, abs(predicted_y - oy) / px_y))
    worst = max(errors)

    print(f"\n{len(samples)} samples inside the reliable radius")
    print(f"  PX_PER_SUBTILE_X = {px_x:.2f}   (currently {screen.PX_PER_SUBTILE_X})")
    print(f"  PX_PER_SUBTILE_Y = {px_y:.2f}   (currently {screen.PX_PER_SUBTILE_Y})")
    print(f"  x/y ratio {px_x / px_y:.3f} (must be ~2.0 if this model is right)")
    print(f"  worst residual {worst:.1f} subtiles")
    if worst > 3:
        print("  ^ large residuals: the model may not fit — paste this output "
              "rather than trusting the numbers")

    # How far do long clicks actually carry? Sets the waypoint spacing cap.
    print(f"\nreach check (beyond {screen.RELIABLE_CLICK_RADIUS_PX} px — not fitted):")
    for offset in _REACH_CHECK_OFFSETS:
        result = _walk_and_measure(gated, offset)
        if result is None:
            continue
        (ox, oy), (dx, dy) = result
        wanted = max(abs(ox) / px_x, abs(oy) / px_y)
        got = max(abs(dx - dy), abs(dx + dy))
        print(f"  clicked ({ox:+5d},{oy:+5d})  walked ({dx:+4d},{dy:+4d})"
              f"   {got / wanted:.0%} of the way")
    print("well under 100% confirms long clicks fall short, and that waypoints "
          f"must stay within ~{screen.RELIABLE_CLICK_RADIUS_PX} px "
          f"({screen.RELIABLE_CLICK_RADIUS_PX // screen.PX_PER_SUBTILE_X} subtiles).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gate = sub.add_parser("gate", help="print the gate verdict; sends nothing")
    gate.add_argument(
        "--focus",
        action="store_true",
        help="bring the game window to the foreground first (for the 'allowed' test)",
    )
    click = sub.add_parser("click-test", help="one hop: predicted vs actual")
    click.add_argument("--send", action="store_true", help="actually click (gated)")
    sub.add_parser("calibrate", help="measure px-per-subtile over many walks")
    args = parser.parse_args(argv)

    try:
        session = GameSession()
        gated = GatedInput(session)
    except (GameNotRunning, NeedsAdministrator, WindowNotFound) as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.command == "gate":
        return cmd_gate(gated, args.focus)
    if args.command == "calibrate":
        return cmd_calibrate(gated)
    return cmd_click_test(gated, args.send)


if __name__ == "__main__":
    raise SystemExit(main())
