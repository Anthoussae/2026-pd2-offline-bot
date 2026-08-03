"""Pickit: which items are worth having, as an editable rule list.

Human-readable and easily updatable is an explicit user requirement
(R46 Q3, restated R117) — the rules live in `config/pickit.toml` as
commented tables, the item vocabulary lives in `config/item_ids.toml`, and
the code here only evaluates them. Rules are checked top-down and **the
first match wins**: a broad rule placed above a narrow one silences the
narrow one, which is the one thing a reader must understand to edit safely.

Two hard constraints shape everything here:

**The vocabulary is bounded by perception.** A `GroundItem` carries kind,
quality, and (pending the T38 drill) a socket count — nothing else. So
rules can speak of item type, quality tier, and sockets; stat-based rules
("+2 skills") need M6's item-stat perception, and a config language that
pretended otherwise would hold rules nobody can evaluate.

**No id is trusted untested.** PD2 renumbered item kinds (the potions,
R54), so names resolve through `item_ids.toml`, where every number cites
its provenance and unverified names are explicitly *pending*. A rule
naming a pending item loads fine and matches nothing — an item not picked
is recoverable, a wrong id acted on is not.

Evaluation runs in two modes, because two different callers ask two
different questions:

    strict      "should I pick this up?" — a condition that cannot be
                evaluated (unknown sockets, no carried-state) fails the
                rule. Used by the pickup steps.
    permissive  "might I have wanted this?" — an unevaluable condition
                passes. Used by the inventory cleanse (R117), whose
                mistake direction is dropping a keeper on the ground.

And one structural safety on top: `cleanse_keep` returns None — cleansing
disabled entirely — while any keep-rule still names pending items, because
a whitelist that cannot recognise a Worldstone Shard must never be allowed
to throw one away.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pd2bot import offsets
from pd2bot.items import CarriedItem, CarriedItems
from pd2bot.units import GroundItem


class PickitError(RuntimeError):
    """A pickit or item-table file is unusable; the message names the key."""


# What a rule's `action` may say, and what each means downstream.
#
#   keep  — pick it up; it rides home in the inventory (potions excepted)
#   belt  — pick it up; it is a potion (the game routes it to belt first)
#   pick  — pick it up (gold: it goes nowhere, it just accumulates)
#   skip  — leave it on the ground
ACTIONS = frozenset({"keep", "belt", "pick", "skip"})

_QUALITY_IDS = {name: qid for qid, name in offsets.QUALITY_NAMES.items()}

# The potion groups stay in code: the belt logic shares these exact tables
# (items.py is_*_potion), and two copies of "what is a healing potion"
# would drift. Everything else lives in config/item_ids.toml.
_POTION_GROUPS: dict[str, frozenset[int]] = {
    "healing_potion": frozenset(offsets.HEALING_POTION_KINDS),
    "mana_potion": frozenset(offsets.MANA_POTION_KINDS),
    "rejuv_potion": frozenset(offsets.REJUV_POTION_KINDS),
    "any_potion": frozenset(offsets.POTION_KINDS),
}
_POTION_TYPE_OF_GROUP = {
    "healing_potion": "healing",
    "mana_potion": "mana",
    "rejuv_potion": "rejuv",
}

# Belt capacity per type under the R53 permanent layout (columns of 4:
# healing owns two columns). The class config is the authority at wiring
# time; this default matches config/necro.toml so a bare Pickit behaves.
DEFAULT_BELT_CAPACITY = {"healing": 8, "mana": 4, "rejuv": 4}


# -- the item vocabulary -------------------------------------------------------


@dataclass(frozen=True)
class ItemTable:
    """name -> the kind id(s) it covers, plus the names still unresolved.

    A name maps to a TUPLE, not a single id, because one item as a human
    names it can be several records to the game. PD2 proved this the
    expensive way (T39/R126): it carries the classic gem and rune records
    AND an `s`-suffixed parallel set (`r15` and `r15s` are both "Hel
    Rune"), and it is the `s` family that actually drops. A name bound to
    one of the two would silently never match.
    """

    ids: dict[str, tuple[int, ...]]
    pending: frozenset[str]
    groups: dict[str, tuple[str, ...]]

    def known(self, name: str) -> bool:
        return (
            name in self.ids
            or name in self.pending
            or name in self.groups
            or name in _POTION_GROUPS
        )


def _as_ids(value, where: str) -> tuple[int, ...]:
    """One id or a list of them -> a tuple. Bools are not ints here."""
    values = value if isinstance(value, list) else [value]
    if not values:
        raise PickitError(f"{where}: an empty id list matches nothing")
    out = []
    for item in values:
        if isinstance(item, bool) or not isinstance(item, int):
            raise PickitError(
                f"{where}: expected an integer id (or a list of them), "
                f"got {item!r}"
            )
        out.append(item)
    return tuple(out)


def load_item_codes(path: str | Path) -> dict[str, tuple[int, ...]]:
    """code -> the kind id(s) carrying it, from the T42-generated table.

    A code maps to a TUPLE for the same reason a name does: PD2 carries
    parallel records for some items (R126's `r15`/`r15s`), and both must
    bind or the one that actually drops is missed.
    """
    with open(Path(path), "rb") as fh:
        data = tomllib.load(fh)
    by_code: dict[str, list[int]] = {}
    for kind, code in (data.get("codes") or {}).items():
        by_code.setdefault(code, []).append(int(kind))
    return {code: tuple(sorted(kinds)) for code, kinds in by_code.items()}


def load_item_table(path: str | Path) -> ItemTable:
    """Load the vocabulary, merging drill-learned entries over the pending list.

    The hand-written file (`item_ids.toml`) keeps its comments and its
    pending list; the T39 drill appends discoveries to a sidecar
    (`item_ids.learned.toml`), and the merge happens here — a learned entry
    moves its name from pending to verified. A learned name that is
    neither pending nor identically verified is a loud error: it means
    the two files disagree about reality, and one of them is wrong.

    **Names are anchored to D2 ITEM CODES, not to numeric kinds** (R144).
    A `[codes]` entry says `wire_fleece = "utu"` and the id is resolved
    through `item_codes.toml`, which the T42 drill generates from the live
    game. Numeric `[verified]` entries still load, for anything the code
    table cannot name.

    The reason is a defect this cost us. Kinds are renumbered every season
    and nobody can check one without the game, so R128's review of 53
    proposed ids — an eyeball pass over numbers — approved SIX wrong elite
    armours. The bot then picked up a Wire Fleece believing it was a Kraken
    Shell (its id, 445, was bound to the wrong name) and could never pick up
    an actual one. A code is checkable against any D2 reference in seconds,
    which makes the review a question a human can actually answer.
    """
    path = Path(path)
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    where = path.name

    unknown = sorted(set(data) - {"verified", "codes", "pending", "groups"})
    if unknown:
        raise PickitError(
            f"{where}: unknown top-level key(s) {', '.join(map(repr, unknown))}"
        )

    codes_path = path.with_name("item_codes.toml")
    by_code = load_item_codes(codes_path) if codes_path.exists() else {}

    def resolve_codes(table: dict, source: str) -> dict[str, tuple[int, ...]]:
        out: dict[str, tuple[int, ...]] = {}
        for name, value in table.items():
            wanted = value if isinstance(value, list) else [value]
            kinds: list[int] = []
            for code in wanted:
                if not isinstance(code, str):
                    raise PickitError(
                        f"{source}.codes.{name}: expected an item code string "
                        f"(or a list of them), got {code!r}"
                    )
                if code not in by_code:
                    raise PickitError(
                        f"{source}.codes.{name}: no item in the live game "
                        f"carries code {code!r}. Either it is a typo, or PD2 "
                        "changed and item_codes.toml needs a T42 re-run — "
                        "guessing an id here is what R144 exists to stop"
                    )
                kinds.extend(by_code[code])
            out[name] = tuple(sorted(set(kinds)))
        return out

    ids: dict[str, tuple[int, ...]] = {}
    for name, value in (data.get("verified") or {}).items():
        ids[name] = _as_ids(value, f"{where}.verified.{name}")
    for name, kinds in resolve_codes(data.get("codes") or {}, where).items():
        if name in ids and ids[name] != kinds:
            raise PickitError(
                f"{where}: {name} is given both as ids {list(ids[name])} and "
                f"as a code resolving to {list(kinds)} — they disagree"
            )
        ids[name] = kinds
    pending_raw = (data.get("pending") or {}).get("names", [])
    if not isinstance(pending_raw, list):
        raise PickitError(f"{where}.pending.names: expected a list of names")
    pending = frozenset(
        name for name in pending_raw if isinstance(name, str)
    )
    if len(pending) != len(pending_raw):
        raise PickitError(f"{where}.pending.names: every entry must be a string")
    overlap = pending & set(ids)
    if overlap:
        raise PickitError(
            f"{where}: {', '.join(sorted(overlap))} listed as both verified "
            "and pending — one of the two is wrong"
        )

    learned_path = path.with_name(path.stem + ".learned" + path.suffix)
    if learned_path.exists():
        with open(learned_path, "rb") as fh:
            learned_data = tomllib.load(fh)
        learned_entries: dict[str, tuple[int, ...]] = {
            name: _as_ids(raw, f"{learned_path.name}.verified.{name}")
            for name, raw in (learned_data.get("verified") or {}).items()
        }
        learned_entries.update(
            resolve_codes(learned_data.get("codes") or {}, learned_path.name)
        )
        for name, value in learned_entries.items():
            if name in ids:
                if ids[name] != value:
                    raise PickitError(
                        f"{learned_path.name}: {name} = {list(value)} "
                        f"contradicts {where}'s {list(ids[name])} — re-drill "
                        "before trusting either"
                    )
                continue
            if name not in pending:
                raise PickitError(
                    f"{learned_path.name}: {name!r} is not a pending name in "
                    f"{where} — the two files disagree about the vocabulary"
                )
            ids[name] = value
            pending = pending - {name}

    groups: dict[str, tuple[str, ...]] = {}
    for group_name, members in (data.get("groups") or {}).items():
        if group_name in _POTION_GROUPS:
            raise PickitError(
                f"{where}.groups.{group_name}: shadows a built-in potion group"
            )
        if not isinstance(members, list) or not members:
            raise PickitError(
                f"{where}.groups.{group_name}: expected a non-empty list"
            )
        for member in members:
            if member not in ids and member not in pending:
                raise PickitError(
                    f"{where}.groups.{group_name}: {member!r} is neither a "
                    "verified nor a pending item name"
                )
        groups[group_name] = tuple(members)
    return ItemTable(ids=ids, pending=pending, groups=groups)


# -- rules ---------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """One line of the pickit, resolved as far as the vocabulary allows."""

    name: str
    action: str
    kinds: frozenset[int] | None = None  # resolved ids
    pending_kinds: frozenset[str] = frozenset()  # named but not yet resolvable
    qualities: frozenset[int] | None = None
    sockets: frozenset[int] | None = None
    # Potion supply rule (R118 Q1): match while the belt has room for this
    # type OR the inventory reserve is short. Set with the type name.
    potion_reserve: int | None = None
    potion_type: str | None = None

    def _kinds_match(self, kind: int, permissive: bool) -> bool | None:
        """True/False, or None meaning 'named only pending items — cannot
        say'. None is distinct from False on purpose: `matchable` uses it."""
        if self.kinds is None and not self.pending_kinds:
            return True  # unconstrained by kind
        if self.kinds is not None and kind in self.kinds:
            return True
        if self.pending_kinds:
            return None  # the item MIGHT be one of the unresolved names
        return False

    def matches(
        self,
        item: GroundItem | CarriedItem,
        carried: CarriedItems | None,
        *,
        permissive: bool = False,
        belt_capacity: dict[str, int] | None = None,
    ) -> bool:
        """Every stated condition must hold; unstated ones do not constrain.

        In permissive mode a condition that cannot be evaluated counts as
        satisfied — including a kind test against still-pending names. That
        makes permissive strictly broader than strict, which is the property
        the cleanse relies on.
        """
        kind_result = self._kinds_match(item.kind, permissive)
        if kind_result is None:
            if not permissive:
                return False  # unresolved vocabulary never picks (fail-safe)
        elif not kind_result:
            return False
        if self.qualities is not None and item.quality not in self.qualities:
            return False
        if self.sockets is not None:
            sockets = getattr(item, "sockets", None)
            if sockets is None:
                if not permissive:
                    return False  # unknown sockets: do not pick on a guess
            elif sockets not in self.sockets:
                return False
        if self.potion_reserve is not None:
            if carried is None:
                return permissive
            capacity = (belt_capacity or DEFAULT_BELT_CAPACITY).get(
                self.potion_type or "", 0
            )
            in_belt = belt_count(carried, self.potion_type)
            in_inventory = _inventory_count(carried, self.potion_type)
            if in_belt >= capacity and in_inventory >= self.potion_reserve:
                return False
        return True


def belt_count(carried: CarriedItems, potion_type: str | None) -> int:
    """How many potions of `potion_type` are in the belt right now.

    Public because the pickup step compares it against capacity to tell a
    genuinely full belt from a click that missed (T56: three click misses
    were diagnosed as "belt full for healing" while the belt was SHORT,
    and the type-level write-off then refused every later healing potion
    in a game that ended on exactly that starvation)."""
    return sum(1 for i in carried.belt if potion_type_of(i) == potion_type)


def _inventory_count(carried: CarriedItems, potion_type: str | None) -> int:
    return sum(
        1 for i in carried.main_inventory if potion_type_of(i) == potion_type
    )


def potion_type_of(item: CarriedItem | GroundItem) -> str | None:
    """Which belt column this item wants, or None if it is not a potion.

    Public because the pickup step needs it too: a potion that will not
    come up means the BELT is full for its type, which is a completely
    different fact from "the inventory grid is full" (stage B run 4).
    """
    if item.kind in offsets.HEALING_POTION_KINDS:
        return "healing"
    if item.kind in offsets.MANA_POTION_KINDS:
        return "mana"
    if item.kind in offsets.REJUV_POTION_KINDS:
        return "rejuv"
    return None


# -- the pickit ----------------------------------------------------------------


@dataclass(frozen=True)
class Pickit:
    """An ordered rule list. First match wins; no match means leave it."""

    rules: tuple[Rule, ...]
    belt_capacity: dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_BELT_CAPACITY)
    )

    @property
    def pending_names(self) -> frozenset[str]:
        """Every unresolved item name a non-skip rule relies on."""
        names: set[str] = set()
        for rule in self.rules:
            if rule.action != "skip":
                names |= rule.pending_kinds
        return frozenset(names)

    def decide(
        self,
        item: GroundItem | CarriedItem,
        carried: CarriedItems | None = None,
        *,
        mode: str = "strict",
    ) -> tuple[str, str]:
        """Return (action, rule name) for one item.

        Unmatched items are left alone, and the reason says so explicitly
        rather than naming a rule — "no rule matched" and "a rule said skip"
        are different states, and a log that conflated them would hide a
        mis-ordered file.
        """
        permissive = mode == "permissive"
        for rule in self.rules:
            if rule.matches(
                item, carried,
                permissive=permissive, belt_capacity=self.belt_capacity,
            ):
                return rule.action, rule.name
        return "skip", "no rule matched"

    def wants(
        self,
        item: GroundItem | CarriedItem,
        carried: CarriedItems | None = None,
        *,
        mode: str = "strict",
    ) -> bool:
        return self.decide(item, carried, mode=mode)[0] != "skip"


def cleanse_keep(pickit: Pickit) -> Callable[[CarriedItem], bool] | None:
    """The inventory-cleanse whitelist, or None while cleansing is unsafe.

    Dropping is the one irreversible act in the inventory, so the whitelist
    must be able to recognise everything it is supposed to protect. While
    any keep-rule still names pending item ids, it cannot — a Worldstone
    Shard would look like junk — so the cleanse is disabled outright rather
    than run with a hole in it. The T39 drill closes the holes.

    Potions always survive a cleanse regardless of rules: their surplus is
    the town loop's business (drink it), never the ground's.

    Permissive is broader than strict by exactly one thing now: an item
    whose sockets did not read. Every other condition — kind, quality,
    potion reserve — evaluates identically on a carried item, and sockets
    joined them once `CarriedItem.sockets` existed (R132). Before that the
    gap was the whole difference between the two modes and it ran one way:
    a plain necro head or archon plate could not be judged, so it was kept
    and stashed, which is the clutter the cleanse exists to prevent. Feed
    this whitelist items read WITH sockets (`read_carried_items` does by
    default) or the gap reopens silently.
    """
    if pickit.pending_names:
        return None

    def keep(item: CarriedItem) -> bool:
        if potion_type_of(item) is not None:
            return True
        return pickit.wants(item, None, mode="permissive")

    return keep


# -- loading -------------------------------------------------------------------


def _resolve_kinds(
    names: list, table: ItemTable, where: str
) -> tuple[frozenset[int], frozenset[str], str | None]:
    """Names -> (resolved ids, pending names, potion type if purely one)."""
    ids: set[int] = set()
    pending: set[str] = set()
    potion_types: set[str | None] = set()
    for name in names:
        if not isinstance(name, str):
            raise PickitError(f"{where}: kind entries must be strings, got {name!r}")
        if name in _POTION_GROUPS:
            ids |= _POTION_GROUPS[name]
            potion_types.add(_POTION_TYPE_OF_GROUP.get(name))
        elif name in table.groups:
            for member in table.groups[name]:
                if member in table.ids:
                    ids.update(table.ids[member])
                else:
                    pending.add(member)
            potion_types.add(None)
        elif name in table.ids:
            ids.update(table.ids[name])
            potion_types.add(None)
        elif name in table.pending:
            pending.add(name)
            potion_types.add(None)
        else:
            raise PickitError(
                f"{where}: unknown item name {name!r} — not in "
                "config/item_ids.toml (verified, pending, or a group) and "
                "not a potion group. A name that resolves to nothing would "
                "never fire, which looks exactly like an item that never "
                "drops."
            )
    only_type = potion_types.pop() if len(potion_types) == 1 else None
    return frozenset(ids), frozenset(pending), only_type


def _resolve_qualities(names: list, where: str) -> frozenset[int]:
    qualities: set[int] = set()
    for name in names:
        if not isinstance(name, str) or name not in _QUALITY_IDS:
            raise PickitError(
                f"{where}: unknown quality {name!r} "
                f"(known: {', '.join(sorted(_QUALITY_IDS))})"
            )
        qualities.add(_QUALITY_IDS[name])
    return frozenset(qualities)


_RULE_KEYS = frozenset(
    {"name", "action", "kinds", "qualities", "sockets", "potion_reserve"}
)


def load_pickit(
    path: str | Path,
    *,
    item_table: ItemTable | None = None,
    belt_capacity: dict[str, int] | None = None,
) -> Pickit:
    """Parse and validate a pickit file. Loud on anything unrecognized.

    `item_table` defaults to `config/item_ids.toml` next to the pickit
    file; tests pass their own. `belt_capacity` comes from the class config
    at wiring time (the R53 layout's per-type belt room).
    """
    path = Path(path)
    if item_table is None:
        item_table = load_item_table(path.parent / "item_ids.toml")
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    where = path.name

    unknown = sorted(set(data) - {"rule"})
    if unknown:
        raise PickitError(
            f"{where}: unknown top-level key(s) {', '.join(map(repr, unknown))} "
            "— a pickit file holds [[rule]] tables and nothing else"
        )
    raw_rules = data.get("rule")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise PickitError(f"{where}: no [[rule]] entries — nothing would be picked")

    rules: list[Rule] = []
    for i, raw in enumerate(raw_rules, 1):
        label = f"{where}: rule #{i}"
        if not isinstance(raw, dict):
            raise PickitError(f"{label} is not a table")
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise PickitError(f"{label} needs a non-empty 'name' (it is the log line)")
        label = f"{where}: rule {name!r}"
        unknown = sorted(set(raw) - _RULE_KEYS)
        if unknown:
            raise PickitError(
                f"{label}: unknown key(s) {', '.join(map(repr, unknown))} "
                f"(allowed: {', '.join(sorted(_RULE_KEYS))})"
            )
        action = raw.get("action")
        if action not in ACTIONS:
            raise PickitError(
                f"{label}: action must be one of {', '.join(sorted(ACTIONS))}, "
                f"got {action!r}"
            )
        for field_name in ("kinds", "qualities", "sockets"):
            value = raw.get(field_name)
            if value is not None and not isinstance(value, list):
                raise PickitError(f"{label}: {field_name} must be a list")

        kinds = pending = None
        potion_type = None
        if raw.get("kinds") is not None:
            kinds, pending, potion_type = _resolve_kinds(
                raw["kinds"], item_table, label
            )
        qualities = (
            _resolve_qualities(raw["qualities"], label)
            if raw.get("qualities") is not None
            else None
        )
        sockets = None
        if raw.get("sockets") is not None:
            for count in raw["sockets"]:
                if isinstance(count, bool) or not isinstance(count, int):
                    raise PickitError(f"{label}: sockets must be integers")
            sockets = frozenset(raw["sockets"])

        reserve = raw.get("potion_reserve")
        if reserve is not None:
            if isinstance(reserve, bool) or not isinstance(reserve, int):
                raise PickitError(f"{label}: potion_reserve must be an integer")
            if potion_type is None:
                raise PickitError(
                    f"{label}: potion_reserve only makes sense on a rule "
                    "whose kinds are exactly one potion group "
                    "(healing_potion, mana_potion, or rejuv_potion) — the "
                    "reserve is counted per type"
                )

        rules.append(
            Rule(
                name=name,
                action=action,
                kinds=kinds,
                pending_kinds=pending or frozenset(),
                qualities=qualities,
                sockets=sockets,
                potion_reserve=reserve,
                potion_type=potion_type if reserve is not None else None,
            )
        )
    return Pickit(
        rules=tuple(rules),
        belt_capacity=dict(belt_capacity or DEFAULT_BELT_CAPACITY),
    )
