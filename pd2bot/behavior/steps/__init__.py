"""The step handlers behind the run vocabulary: what each TOML step does.

P4 declared the step NAMES and validated `runs/cold-plains.toml` against
them; this is where each name gets a ticking implementation. Steps are
supplied their collaborators through `RunServices` at registry-build time,
so a run file never mentions a town layer or a combat module — it says
`town_preamble` and the wiring decides what that means.

Two shapes of step live here, and the difference matters:

**Blocking steps** (`town_preamble`, `waypoint`) do their whole job inside
one tick, because the layers beneath them are already written that way —
`run_preamble` walks across town and back, `take` polls until the area id
changes. That is safe precisely where they run: town is the one place the
survival ladder has nothing to say, and the waypoint trip is a loading
screen. The reflex ladder is not consulted during them, which would be
unacceptable anywhere else.

**Ticked steps** (`clear_radius`, `pickup`) do one small thing per tick and
return, so the ladder gets a look between every decision. Everything that
happens in Hell is one of these — that is the whole reason the engine is a
loop rather than a script.
"""

from pd2bot.behavior.steps.basic import DoneStep, TownPreambleStep, WaypointStep
from pd2bot.behavior.steps.clear import ClearRadiusStep, PickupStep
from pd2bot.behavior.steps.countess import ClearCountessStep
from pd2bot.behavior.steps.patrol import _PatrolMixin
from pd2bot.behavior.steps.pickup import _PickupMixin
from pd2bot.behavior.steps.registry import build_registry
from pd2bot.behavior.steps.services import RunServices
from pd2bot.behavior.steps.survey import SurveyStep
from pd2bot.behavior.steps.traverse import TraverseStep
from pd2bot.behavior.steps.util import _chebyshev, _route_leg

__all__ = [
    "ClearCountessStep",
    "ClearRadiusStep",
    "DoneStep",
    "PickupStep",
    "RunServices",
    "SurveyStep",
    "TownPreambleStep",
    "TraverseStep",
    "WaypointStep",
    "build_registry",
    "_PatrolMixin",
    "_PickupMixin",
    "_chebyshev",
    "_route_leg",
]
