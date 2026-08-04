"""The run loader: everything fails at load time, nothing fails mid-run."""

from pathlib import Path

import pytest

from pd2bot.behavior.engine import StepOutcome
from pd2bot.behavior.run import (
    ParamSpec,
    RunError,
    StepRegistry,
    StepSpec,
    build_states,
    default_registry,
    load_run,
)

REPO = Path(__file__).resolve().parent.parent


def write_run(tmp_path, text):
    path = tmp_path / "run.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_shipped_cold_plains_run_validates():
    run = load_run(REPO / "runs" / "cold-plains.toml", default_registry())
    assert run.name == "cold-plains"
    assert [s.name for s in run.steps] == [
        "town_preamble", "waypoint", "clear_radius", "pickup", "done",
    ]
    assert run.steps[1].params == {"dest": 3}  # Cold Plains, live-verified id
    # patrol on: 150 is more than perception's 80, so the circle has to be
    # walked for the number to mean anything (2026-08-01).
    assert run.steps[2].params == {
        "center": "arrival", "radius": 150, "patrol": True, "posture": None
    }


def test_unknown_step_name_fails_at_load(tmp_path):
    path = write_run(
        tmp_path, 'name = "x"\n[[step]]\nname = "teleport_to_baal"\n'
    )
    with pytest.raises(RunError, match="teleport_to_baal"):
        load_run(path, default_registry())


def test_unknown_parameter_fails_at_load(tmp_path):
    path = write_run(
        tmp_path, 'name = "x"\n[[step]]\nname = "waypoint"\ndest = 3\nspeed = 9\n'
    )
    with pytest.raises(RunError, match="'speed'"):
        load_run(path, default_registry())


def test_missing_required_parameter_fails_at_load(tmp_path):
    path = write_run(tmp_path, 'name = "x"\n[[step]]\nname = "waypoint"\n')
    with pytest.raises(RunError, match="dest"):
        load_run(path, default_registry())


def test_wrong_parameter_type_fails_at_load(tmp_path):
    path = write_run(
        tmp_path, 'name = "x"\n[[step]]\nname = "waypoint"\ndest = "three"\n'
    )
    with pytest.raises(RunError, match="expected int"):
        load_run(path, default_registry())


def test_bool_does_not_pass_as_int(tmp_path):
    path = write_run(
        tmp_path, 'name = "x"\n[[step]]\nname = "waypoint"\ndest = true\n'
    )
    with pytest.raises(RunError, match="got bool"):
        load_run(path, default_registry())


def test_optional_parameter_gets_its_declared_default(tmp_path):
    path = write_run(
        tmp_path,
        'name = "x"\n[[step]]\nname = "clear_radius"\nradius = 99\n',
    )
    run = load_run(path, default_registry())
    # `patrol` joined them on 2026-08-01 and defaults off; `posture`
    # joined at M6 P3 and defaults None — either way, every run written
    # before behaves exactly as it did.
    assert run.steps[0].params == {
        "center": "arrival", "radius": 99, "patrol": False, "posture": None
    }


def test_the_radius_override_applies_to_the_clearance(tmp_path):
    # `--radius`, so the number the operator tunes most can be changed
    # without editing a data file while standing at the machine.
    path = write_run(
        tmp_path,
        'name = "x"\n[[step]]\nname = "clear_radius"\nradius = 96\n',
    )
    run = load_run(path, default_registry()).with_radius(150)
    assert run.radius == 150
    assert run.steps[0].params["patrol"] is False  # nothing else disturbed


def test_the_radius_override_refuses_when_it_has_nothing_to_apply_to(tmp_path):
    # A flag that appears to work and silently does nothing is the class
    # of failure this project keeps paying for.
    path = write_run(tmp_path, 'name = "x"\n[[step]]\nname = "done"\n')
    run = load_run(path, default_registry())
    with pytest.raises(RunError, match="no clear_radius step"):
        run.with_radius(150)


def test_a_run_without_a_clearance_reports_no_radius(tmp_path):
    path = write_run(tmp_path, 'name = "x"\n[[step]]\nname = "done"\n')
    assert load_run(path, default_registry()).radius is None


def test_run_needs_a_name_and_steps(tmp_path):
    with pytest.raises(RunError, match="name"):
        load_run(write_run(tmp_path, '[[step]]\nname = "done"\n'),
                 default_registry())
    with pytest.raises(RunError, match="at least one"):
        load_run(write_run(tmp_path, 'name = "x"\n'), default_registry())


def test_unknown_top_level_key_fails(tmp_path):
    path = write_run(
        tmp_path, 'name = "x"\nauthor = "me"\n[[step]]\nname = "done"\n'
    )
    with pytest.raises(RunError, match="'author'"):
        load_run(path, default_registry())


def test_step_without_a_name_fails(tmp_path):
    path = write_run(tmp_path, 'name = "x"\n[[step]]\ndest = 3\n')
    with pytest.raises(RunError, match="no 'name'"):
        load_run(path, default_registry())


def test_duplicate_registration_is_refused():
    registry = StepRegistry()
    registry.register(StepSpec("a"))
    with pytest.raises(RunError, match="already registered"):
        registry.register(StepSpec("a"))


class _State:
    def __init__(self, name, params):
        self.name = name
        self.params = params

    def step(self, snap, ctx):
        return StepOutcome(done=True)


def test_build_states_uses_factories_in_order(tmp_path):
    registry = StepRegistry()
    registry.register(
        StepSpec(
            "go",
            params=(ParamSpec("where", str),),
            factory=lambda p: _State("go", p),
        )
    )
    registry.register(StepSpec("stop", factory=lambda p: _State("stop", p)))
    path = write_run(
        tmp_path,
        'name = "x"\n[[step]]\nname = "go"\nwhere = "north"\n'
        '[[step]]\nname = "stop"\n',
    )
    states = build_states(load_run(path, registry), registry)
    assert [s.name for s in states] == ["go", "stop"]
    assert states[0].params == {"where": "north"}


def test_the_shipped_survey_runs_validate():
    field = load_run(REPO / "runs" / "survey-cold-plains.toml", default_registry())
    assert [s.name for s in field.steps] == [
        "town_preamble", "waypoint", "survey", "done",
    ]
    assert field.steps[1].params == {"dest": 3}
    town = load_run(REPO / "runs" / "survey-town.toml", default_registry())
    assert [s.name for s in town.steps] == ["town_preamble", "survey", "done"]


def test_declared_but_unimplemented_step_refuses_to_build():
    # The default registry declares the M5 vocabulary; the handlers are
    # P5's. Building a run over them must fail loudly, not skip silently.
    registry = default_registry()
    run = load_run(REPO / "runs" / "cold-plains.toml", registry)
    with pytest.raises(RunError, match="no handler"):
        build_states(run, registry)


def test_default_registry_vocabulary():
    assert default_registry().names() == [
        "clear_radius", "done", "pickup", "survey", "town_preamble", "waypoint",
    ]
