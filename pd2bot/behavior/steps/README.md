# behavior/steps/ — what each run-file step actually does

A runs/*.toml file names steps; registry.py maps those names to the
classes here. Split from the old 3,327-line steps.py on 2026-08-09,
bodies unchanged.

| file | one job |
|---|---|
| util.py | hop geometry, route legs, shared constants |
| services.py | RunServices: the container of capabilities every step receives |
| basic.py | town_preamble, waypoint, done |
| pickup.py | _PickupMixin: sprite-aimed pickup + the cleanse hook |
| patrol.py | _PatrolMixin: patrol legs between anchors |
| clear.py | clear_radius and pickup steps |
| survey.py | survey: operator-steered atlas recording |
| traverse.py | traverse: cross an area to its exit |
| countess.py | clear_countess: the flagship kill |
| registry.py | step name -> class; unknown names fail at load |

Import step classes and `build_registry` from `pd2bot.behavior.steps`.
Step NAMES in run files must never change silently — they are the
public vocabulary of runs/*.toml.
