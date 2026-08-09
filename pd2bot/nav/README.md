# nav/ — moving through the world

| file | one job |
|---|---|
| pathing.py | A* over walkability grids |
| navigate.py | the walk loop: gated clicks, progress watching, escalation; safety-polled and wall-clock-capped |
| collision.py | read the live collision grid around the player |
| mapstore.py | the explored-map atlas: remembered room grids per seed |
| mapframe.py | stitch room grids into one queryable frame |
| survey.py | operator-steered recording of new areas |
| waypoint.py | waypoint panel travel (act tabs, row clicks) |
| mapdata.py | DORMANT offline map generator (blocked by PD2's DLLs) |

Other layers import: `NavigationError`, the navigator built by wiring.
Doc: docs/architecture/navigation.md
