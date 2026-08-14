# behavior/ — deciding

The brain: a ticked engine that observes, checks safety, runs reflexes,
then gives the current run step its turn. Runs are data (runs/*.toml).

| file | one job |
|---|---|
| engine.py | the tick loop and its ordering guarantees |
| reflex.py | the survival ladder (short-circuit: most urgent rung wins the tick) |
| necro.py | the poison-dagger necromancer: skills, curses, the wall |
| combat.py | class config loading, target selection, postures |
| execute.py | turn decided actions into verified sends |
| actions.py | the action vocabulary (MoveTo, Cast, InteractObject, ...) |
| run.py | run-file parsing: StepRegistry, StepSpec, validation |
| runner.py | drive one whole run start to finish |
| pickit.py | what loot is worth it: config/pickit.toml matching |
| town/ | town errands (own README) |
| steps/ | the run steps (own README) |

Doc: docs/architecture/behavior.md; ADR 2026-07-29-behavior-architecture.
