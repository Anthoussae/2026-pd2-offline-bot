# Glossary

Plain-language definitions of technical terms used in this project's
development, in alphabetical order. Maintained by the `teach` skill; each
entry may point to the explainer where the term first appeared.

**A\* ("A-star")** — the standard pathfinding algorithm in games: given a
grid of walkable and blocked squares, it finds the shortest route between
two points. Its trick is always extending the candidate route that scores
best on "distance walked so far + estimated distance remaining," so the
search heads toward the goal instead of flooding the whole map.

**collision map** — a grid representation of a game area marking which
squares can be walked on and which are blocked (walls, water, props).
Pathfinding algorithms like A* operate on this grid. Our bot gets its
collision maps from a map-generator tool that runs the game's own
map-building code.

**heuristic** — an informed estimate used to guide a search or decision
when computing the exact answer up front would be too slow; "good guess
math." In A*, the heuristic is the straight-line distance to the goal,
used to decide which route to try extending next.
