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
    assert run.steps[2].params == {"center": "arrival", "radius": 150}


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
    assert run.steps[0].params == {"center": "arrival", "radius": 99}


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


def test_declared_but_unimplemented_step_refuses_to_build():
    # The default registry declares the M5 vocabulary; the handlers are
    # P5's. Building a run over them must fail loudly, not skip silently.
    registry = default_registry()
    run = load_run(REPO / "runs" / "cold-plains.toml", registry)
    with pytest.raises(RunError, match="no handler"):
        build_states(run, registry)


def test_default_registry_vocabulary():
    assert default_registry().names() == [
        "clear_radius", "done", "pickup", "town_preamble", "waypoint",
    ]
