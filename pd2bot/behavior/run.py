"""Runs as declarative data: an ordered list of steps in a TOML file.

A run says WHAT happens — `town_preamble`, then `waypoint {dest = 3}`, then
`clear_radius {radius = 150}` — and nothing about how, which class does it,
or which game structures are involved. Steps map to handlers registered in a
`StepRegistry`; the Cold Plains run is `runs/cold-plains.toml`, and a future
Countess run should be a new file, not new code (roadmap decision 5).

Everything fails at LOAD time, not mid-run: an unknown step name, an
unknown or missing parameter, a wrong type — each is a loud `RunError`
before the bot has moved at all. The alternative — discovering a typo'd
step name in Hell, three steps into a run — is the failure mode the
robustness priority forbids.

P4 registers the step NAMES and their parameter schemas (that is what
validating cold-plains.toml needs); the handlers behind them are P5's work,
and building states for a declared-but-unimplemented step is itself a loud
error rather than a silent skip.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pd2bot.behavior.engine import StepState


class RunError(RuntimeError):
    """A run definition is unusable; the message names file, step and key."""


@dataclass(frozen=True)
class ParamSpec:
    """One parameter a step accepts. `required` params must appear in the
    TOML; optional ones fall back to `default` (an EXPLICIT default declared
    here, visible in one place — not a scattering of .get() calls)."""

    name: str
    kind: type
    required: bool = True
    default: object = None


@dataclass(frozen=True)
class StepSpec:
    """A registered step: its name, its parameters, and (once P5 supplies
    it) the factory that turns validated params into a ticking state."""

    name: str
    params: tuple[ParamSpec, ...] = ()
    factory: Callable[[dict], StepState] | None = None


@dataclass(frozen=True)
class RunStep:
    name: str
    params: dict


@dataclass(frozen=True)
class RunDefinition:
    name: str
    steps: tuple[RunStep, ...]

    def with_radius(self, radius: int) -> RunDefinition:
        """A copy whose `clear_radius` steps use `radius` instead.

        For the `--radius` override (user request: *make the radius value
        easy to alter*). The staged-acceptance numbers are the ones that
        get tuned most, and editing a data file to try 120 instead of 96
        is friction the operator pays while standing at the machine.

        Raises when the run has no `clear_radius` step at all: a flag
        that appears to work and silently does nothing is exactly the
        class of failure this project keeps paying for.
        """
        steps = tuple(
            RunStep(s.name, {**s.params, "radius": radius})
            if s.name == "clear_radius"
            else s
            for s in self.steps
        )
        if steps == self.steps:
            raise RunError(
                f"--radius {radius} has nothing to apply to: run "
                f"{self.name!r} has no clear_radius step"
            )
        return RunDefinition(name=self.name, steps=steps)

    @property
    def radius(self) -> int | None:
        """The clearance radius this run will use, for the pre-flight print."""
        return next(
            (s.params.get("radius") for s in self.steps if s.name == "clear_radius"),
            None,
        )


class StepRegistry:
    """The known steps. Runs are validated against this at load."""

    def __init__(self) -> None:
        self._specs: dict[str, StepSpec] = {}

    def register(self, spec: StepSpec) -> None:
        if spec.name in self._specs:
            raise RunError(f"step {spec.name!r} is already registered")
        self._specs[spec.name] = spec

    def spec(self, name: str) -> StepSpec:
        found = self._specs.get(name)
        if found is None:
            raise RunError(
                f"unknown step {name!r} (known: "
                f"{', '.join(sorted(self._specs)) or 'none'})"
            )
        return found

    def names(self) -> list[str]:
        return sorted(self._specs)


def default_registry() -> StepRegistry:
    """The M5 step vocabulary. Factories arrive in P5; the names and
    parameter schemas are what load-time validation runs against."""
    registry = StepRegistry()
    registry.register(StepSpec("town_preamble"))
    registry.register(
        StepSpec("waypoint", params=(ParamSpec("dest", int),))
    )
    registry.register(
        StepSpec(
            "clear_radius",
            params=(
                ParamSpec("center", str, required=False, default="arrival"),
                ParamSpec("radius", int),
                # Must stay in step with build_registry's copy: this is the
                # schema the run linter and the drills validate against, and
                # two vocabularies that disagree would pass a run file here
                # that the bot then refuses in Hell.
                ParamSpec("patrol", bool, required=False, default=False),
                # M6 P3: the combat posture for this step. The NAME is
                # only checkable against a loaded class config, so this
                # registry validates the type and build_registry's
                # factory validates the value.
                ParamSpec("posture", str, required=False, default=None),
            ),
        )
    )
    registry.register(
        # Must stay in step with build_registry's copy (the standing
        # rule): the linter validates run files against THIS vocabulary.
        StepSpec(
            "traverse",
            params=(
                ParamSpec("dest", int),
                ParamSpec("posture", str, required=False, default=None),
            ),
        )
    )
    registry.register(StepSpec("pickup"))
    # Must stay in step with build_registry's copy (same rule as
    # clear_radius's params above): this schema is what the run linter
    # validates against, and a survey run that lints here but is unknown
    # to the live registry would refuse to start in Hell.
    registry.register(StepSpec("survey"))
    registry.register(StepSpec("done"))
    return registry


def _validate_params(
    step_name: str, raw: dict, spec: StepSpec, where: str
) -> dict:
    allowed = {p.name for p in spec.params}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise RunError(
            f"{where}: step {step_name!r} does not take "
            f"{', '.join(map(repr, unknown))} (takes: "
            f"{', '.join(sorted(allowed)) or 'no parameters'})"
        )
    params: dict = {}
    for param in spec.params:
        if param.name not in raw:
            if param.required:
                raise RunError(
                    f"{where}: step {step_name!r} is missing required "
                    f"parameter {param.name!r}"
                )
            params[param.name] = param.default
            continue
        value = raw[param.name]
        # bool subclasses int; without this a `true` would pass as an int.
        if param.kind in (int, float) and isinstance(value, bool):
            raise RunError(
                f"{where}: {step_name}.{param.name} expected "
                f"{param.kind.__name__}, got bool"
            )
        if param.kind is float and isinstance(value, int):
            value = float(value)
        if not isinstance(value, param.kind):
            raise RunError(
                f"{where}: {step_name}.{param.name} expected "
                f"{param.kind.__name__}, got {type(value).__name__}"
            )
        params[param.name] = value
    return params


def load_run(path: str | Path, registry: StepRegistry) -> RunDefinition:
    """Parse and validate one run file against the registry. Loud on any
    problem; a returned RunDefinition is fully checked."""
    path = Path(path)
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    where = path.name

    unknown = sorted(set(data) - {"name", "step"})
    if unknown:
        raise RunError(
            f"{where}: unknown top-level key(s) {', '.join(map(repr, unknown))}"
        )
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise RunError(f"{where}: a run needs a non-empty string 'name'")
    raw_steps = data.get("step")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RunError(f"{where}: a run needs at least one [[step]]")

    steps: list[RunStep] = []
    for i, raw in enumerate(raw_steps, 1):
        if not isinstance(raw, dict) or "name" not in raw:
            raise RunError(f"{where}: [[step]] #{i} has no 'name'")
        step_name = raw["name"]
        spec = registry.spec(step_name)  # unknown names fail loudly here
        params = _validate_params(
            step_name, {k: v for k, v in raw.items() if k != "name"}, spec, where
        )
        steps.append(RunStep(name=step_name, params=params))
    return RunDefinition(name=name, steps=tuple(steps))


def build_states(run: RunDefinition, registry: StepRegistry) -> list[StepState]:
    """Turn a validated run into ticking states. A declared step without a
    factory is a loud error — running past it would silently hollow out the
    run, which is worse than not starting."""
    states: list[StepState] = []
    for step in run.steps:
        spec = registry.spec(step.name)
        if spec.factory is None:
            raise RunError(
                f"step {step.name!r} is declared but has no handler yet "
                "(its factory arrives with P5) — refusing to build a run "
                "that would skip it"
            )
        states.append(spec.factory(dict(step.params)))
    return states
