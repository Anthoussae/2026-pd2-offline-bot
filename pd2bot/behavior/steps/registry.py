"""The step registry: run-file step names mapped to their classes.

Split from steps.py 2026-08-09; bodies unchanged.
"""

from __future__ import annotations

from pd2bot.behavior.run import ParamSpec, StepRegistry, StepSpec
from pd2bot.behavior.steps.basic import DoneStep, TownPreambleStep, WaypointStep
from pd2bot.behavior.steps.clear import ClearRadiusStep, PickupStep
from pd2bot.behavior.steps.countess import ClearCountessStep
from pd2bot.behavior.steps.services import RunServices
from pd2bot.behavior.steps.survey import SurveyStep
from pd2bot.behavior.steps.traverse import TraverseStep


def _checked_posture(services: RunServices, name: str | None) -> str | None:
    """Validate a step's posture name at BUILD time (M6 P3).

    Reaching a game with an unknown posture would fail mid-run in Hell;
    this fails while the bot is still standing at the menus, the same
    place every other run-file mistake fails.
    """
    if name is None:
        return None
    if name not in services.postures:
        from pd2bot.behavior.run import RunError

        loaded = ", ".join(sorted(services.postures))
        raise RunError(
            f"unknown posture {name!r} (loaded: "
            f"{loaded or 'none — this environment has no postures'})"
        )
    return name


def build_registry(services: RunServices) -> StepRegistry:
    """The M5 step vocabulary, with handlers wired to `services`.

    Same names and parameter schemas as P4's `default_registry` — that one
    stays as the validate-without-a-game path (drills and the run linter),
    this one is what actually runs.
    """
    registry = StepRegistry()
    registry.register(
        StepSpec("town_preamble", factory=lambda p: TownPreambleStep(services))
    )
    registry.register(
        StepSpec(
            "waypoint",
            params=(ParamSpec("dest", int),),
            factory=lambda p: WaypointStep(services, dest=p["dest"]),
        )
    )
    registry.register(
        StepSpec(
            "clear_radius",
            params=(
                ParamSpec("center", str, required=False, default="arrival"),
                ParamSpec("radius", int),
                # Off by default so every run written before the patrol
                # existed keeps behaving exactly as it did.
                ParamSpec("patrol", bool, required=False, default=False),
                # M6 P3: which combat posture to fight this step in.
                # Absent = leave the module alone (cautious in practice).
                ParamSpec("posture", str, required=False, default=None),
            ),
            factory=lambda p: ClearRadiusStep(
                services,
                radius=p["radius"],
                centre_note=p["center"],
                patrol=p["patrol"],
                posture=_checked_posture(services, p["posture"]),
            ),
        )
    )
    registry.register(
        StepSpec(
            "traverse",
            params=(
                ParamSpec("dest", int),
                ParamSpec("posture", str, required=False, default=None),
            ),
            factory=lambda p: TraverseStep(
                services,
                dest=p["dest"],
                posture=_checked_posture(services, p["posture"]),
            ),
        )
    )
    registry.register(
        StepSpec(
            "clear_countess",
            params=(
                # The chamber anchor: her T68-measured position for this
                # seed, upgraded to the live boss read the moment she is
                # in perception. Two ints because run-file params are
                # scalars — the run file comments their provenance.
                ParamSpec("chamber_x", int),
                ParamSpec("chamber_y", int),
                ParamSpec("neighborhood_radius", int, required=False, default=30),
                ParamSpec("chamber_radius", int, required=False, default=25),
                ParamSpec("posture", str, required=False, default=None),
            ),
            factory=lambda p: ClearCountessStep(
                services,
                chamber=(p["chamber_x"], p["chamber_y"]),
                neighborhood_radius=p["neighborhood_radius"],
                chamber_radius=p["chamber_radius"],
                posture=_checked_posture(services, p["posture"]),
            ),
        )
    )
    registry.register(
        StepSpec(
            "pickup",
            factory=lambda p: PickupStep(services),
        )
    )
    registry.register(
        StepSpec("survey", factory=lambda p: SurveyStep(services))
    )
    registry.register(StepSpec("done", factory=lambda p: DoneStep(services)))
    return registry

