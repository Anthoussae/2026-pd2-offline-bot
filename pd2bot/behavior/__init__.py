"""The behavior layer: the ticked engine, runs-as-data, and the reflex ladder.

M5 P4's package — everything above the town layer and below the game cycle.
The division of labor (the third expected ADR, drafted in
docs/adr/2026-07-29-behavior-architecture.md):

    engine.py   the ticked loop: snapshot -> safety monitor -> reflex
                ladder -> the current run step. Knows nothing about
                necromancers or Cold Plains.
    run.py      run definitions as declarative TOML (runs/*.toml) over a
                registry of step handlers. Unknown steps fail at load.
    reflex.py   the survival ladder (R49), evaluated every tick above
                offense; first firing rung wins.
    combat.py   the class-agnostic combat protocol; per-class TOML config
                (config/<class>.toml). Runs never name a class.
    actions.py  the declarative actions everything above emits and an
                executor turns into input (P5 wires the real one).
    runner.py   the run_games callback boundary: IdleBail counting and
                the loud idle-loop halt.

Sim-only in P4: nothing here sends input; tests drive everything through
fakes exactly as tests/test_town.py does.
"""
