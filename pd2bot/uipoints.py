"""Named, hover-calibrated points inside in-game panels.

D2's panels expose no readable control structs (the M4 Save-and-Exit
precedent), so every clickable thing inside one is a client-rect fraction
measured by watching a human's cursor. Before this module each such point
was its own `TownConfig` field with its own consumer — and the copies
drifted, exactly the way the three NPC dialog steps drifted before they
were merged into `open_npc_dialog` (R78).

The user's framing (R87) is the right one: *opening a dialog with an NPC is
the same task regardless of the NPC, and clicking a line is the same task
regardless of the line.* So a point is data, not code:

    UIPoint(name, panel, fraction, opens)

    panel     must be open for the click to mean anything — it is also
              what `PanelInput` is told to guard on
    fraction  where, as a fraction of the client rect; None = uncalibrated,
              and an uncalibrated point REFUSES rather than guessing
    opens     the panel the click is expected to raise, when the effect is
              a panel; None when the proof is something better (durability
              restored, a live merc, an area change) which the caller
              supplies

That last distinction is the load-bearing one. A click's success is never
"we clicked": it is an observed change, and where a real-world effect is
available it beats a UI flag every time.

Calibration provenance is recorded per point, because a measurement is only
as good as the procedure that produced it — and one bad procedure already
poisoned two of these (R86): a capture that armed immediately fired on the
cursor resting where the user had just clicked the NPC, so the "trade/repair
row" was really Charsi's portrait, 488 px off. Points measured that way are
marked uncalibrated here rather than left in place looking plausible.
"""

from __future__ import annotations

from dataclasses import dataclass

from pd2bot import offsets


@dataclass(frozen=True)
class UIPoint:
    """One calibrated click target inside one panel.

    Two kinds of target, because D2 has two kinds of panel:

    *Screen-anchored* (`fraction`) — the stash, the waypoint list, a
    vendor's shop screen. These are furniture: they appear in the same place
    every time, so a client-rect fraction locates them forever.

    *NPC-anchored* (`anchor_npc` + `npc_offset`) — the rows of an NPC
    conversation. These are drawn relative to the NPC, and NPCs wander (user
    diagnosis, R97), so a fraction cannot locate one at all: it captures one
    accidental arrangement. Measured live in T29, the vertical offset held to
    5 px across openings while the NPC's screen position moved by 60+ px.
    Vertical is the axis that matters — rows stack 180 px apart (T28), so
    being wrong in Y means clicking a different option, which is exactly how
    the repair step came to click Cancel.

    The history this encodes is worth keeping: three separate fractions were
    stored for `charsi.trade_repair`, each verified by effect at the moment
    it was taken, and each failed later. They were not sloppy measurements —
    they were measurements of the wrong kind of thing.
    """

    name: str
    panel: int
    fraction: tuple[float, float] | None = None
    opens: int | None = None
    note: str = ""
    anchor_npc: int | None = None
    npc_offset: tuple[int, int] | None = None
    keyboard_row: int | None = None  # 1-based row, chosen by arrows + Enter
    row_count: int | None = None  # how many rows that menu has, for the record

    @property
    def by_keyboard(self) -> bool:
        """Selected by ordinal rather than by position — the best kind.

        An NPC dialog is keyboard-navigable: the highlight opens on row 1,
        Down advances it, and it wraps at the end (T34). So row N is reached
        with N-1 Downs and confirmed with Enter, and nothing on screen needs
        locating at all. That immunity is the point: the row's PIXELS move
        when the NPC paces, but the row's INDEX does not.
        """
        return self.keyboard_row is not None

    @property
    def npc_anchored(self) -> bool:
        return self.anchor_npc is not None and not self.by_keyboard

    @property
    def calibrated(self) -> bool:
        if self.by_keyboard:
            return True
        if self.npc_anchored:
            return self.npc_offset is not None
        return self.fraction is not None

    def pixel(self, rect) -> tuple[int, int]:
        """Screen pixel for a SCREEN-anchored point in `rect`.

        NPC-anchored points cannot be resolved from the rect alone — they
        need the NPC's position now — so they refuse here rather than
        silently returning a plausible wrong pixel.
        """
        if self.npc_anchored:
            raise ValueError(
                f"{self.name} is anchored to an NPC; resolve it with the "
                "NPC's projected screen position, not the client rect alone"
            )
        if self.fraction is None:
            raise ValueError(f"{self.name} is not calibrated")
        return (
            rect.left + round(self.fraction[0] * rect.width),
            rect.top + round(self.fraction[1] * rect.height),
        )

    def pixel_from_npc(self, npc_screen: tuple[int, int]) -> tuple[int, int]:
        """Screen pixel for an NPC-anchored point, given where the NPC is."""
        if not self.npc_anchored or self.npc_offset is None:
            raise ValueError(f"{self.name} is not NPC-anchored")
        return (
            npc_screen[0] + self.npc_offset[0],
            npc_screen[1] + self.npc_offset[1],
        )


# Every point the bot may click, with what must be open to click it and
# what the click should do. Keyed by a dotted name so a calibration drill
# can be handed a list of names and nothing else.
#
# 1536x864 window. Re-run the calibration after any window or resolution
# change — the standing rule since M4's Save-and-Exit fractions.
def default_points() -> dict[str, UIPoint]:
    points = (
        UIPoint(
            "charsi.trade_repair",
            offsets.UI_NPCMENU,
            opens=offsets.UI_NPCSHOP,
            anchor_npc=offsets.NPC_CHARSI,
            keyboard_row=2,
            row_count=3,
            note=(
                "T34: row 2 of 3 (Talk / Trade-Repair / Cancel), selected with "
                "1 Down then Enter. Every outcome of that drill fits one "
                "model — the highlight opens on row 1, Down advances, and it "
                "wraps: 0 downs left the dialog open (Talk), 1 opened the "
                "shop, 2 closed it (Cancel), 3 wrapped back to Talk.\n\n"
                "This replaces a long line of positional attempts, all of "
                "which failed for the same reason and none of which could "
                "have worked: three screen fractions (0.5879/0.2072, "
                "0.4635/0.2500, 0.4154/0.3079), each verified by effect when "
                "taken and each stale within a run, and then an NPC-anchored "
                "offset of (8, -211) that scored 4/5. The row's PIXELS move "
                "when Charsi paces; its INDEX does not. Kept anchored to her "
                "only so the dialog can still be attributed to the right NPC.\n\n"
                "Proven end to end by T19, which had failed four times on the "
                "positional approaches and passed first time on this one: 6 "
                "worn items, 12 durability missing -> 0."
            ),
        ),
        UIPoint(
            "akara.trade",
            offsets.UI_NPCMENU,
            opens=offsets.UI_NPCSHOP,
            anchor_npc=offsets.NPC_AKARA,
            keyboard_row=2,
            row_count=3,
            note=(
                "Akara's menu is Talk / Trade / Cancel (operator-confirmed, "
                "2026-08-10), the same three-row shape as Charsi's "
                "trade/repair: 1 Down then Enter selects TRADE (row 2) and "
                "opens the shop. Same discipline as charsi.trade_repair — "
                "the row INDEX is stable while its pixels move as she paces; "
                "verified by effect (UI_NPCSHOP opens)."
            ),
        ),
        UIPoint(
            "charsi.repair_all",
            offsets.UI_NPCSHOP,
            (0.4648, 0.7650),
            note=(
                "T25 run 2, hovered at (714, 661); durability went to 0 "
                "missing, which is the proof — the button raises no panel of "
                "its own, so `opens` stays None and the caller supplies the "
                "durability check. Within ~11 px of T18's value, which was "
                "its re-armed second capture and so never had the defect."
            ),
        ),
        UIPoint(
            "kashya.resurrect",
            offsets.UI_NPCMENU,
            anchor_npc=offsets.NPC_KASHYA,
            keyboard_row=2,
            row_count=4,
            note=(
                "DEAD-MERC STATE ONLY. Row 2 of 4, read off the live menu by "
                "the user in a real dead-merc window (R105):\n"
                "    1 TALK   2 RESURRECT <name>: 50000   3 HIRE   4 CANCEL\n\n"
                "**With the merc ALIVE the resurrect row does not exist**, so "
                "the menu is TALK / HIRE / CANCEL and row 2 becomes HIRE — "
                "the same index, an entirely different action (R56). This is "
                "why `resurrect_merc_if_dead` re-confirms the merc is dead "
                "immediately before selecting rather than trusting its "
                "earlier check, and proves success by BOTH a live merc and "
                "gold actually spent.\n\n"
                "Read rather than probed, deliberately: T34 could sweep "
                "Charsi's menu because every wrong row there is free, and a "
                "wrong row here costs 50,000 gold and consumes the very "
                "state being measured. Proven first time by T21 — merc alive "
                "(rogue) and gold 878725 -> 828725, exactly 50,000.\n\n"
                "Its old screen fraction (0.3763, 0.1875) is void — an NPC "
                "dialog row cannot be located by a fraction at all (R97), "
                "and the one live click that used it worked by luck of where "
                "the character happened to be standing."
            ),
        ),
        # The waypoint list. A destination click raises no panel — it closes
        # the one you are in and loads an area — so `opens` stays None and
        # the proof is the area id read back (waypoint.py's `await_arrival`).
        # The act TABS of the waypoint list (M6 P2). Screen-anchored
        # furniture like the rows. Clicking a tab swaps the destination
        # list and raises no panel; travel on a subsequently-clicked row
        # is the proof the tab click took.
        UIPoint(
            "waypoint.tab_act1",
            offsets.UI_WPMENU,
            (0.2363, 0.1308),  # T69, 2026-08-05, window 1536x864
        ),
        UIPoint(
            "waypoint.tab_act2",
            offsets.UI_WPMENU,
            (0.2930, 0.1319),  # T69, 2026-08-05, window 1536x864
        ),
        UIPoint(
            "waypoint.tab_act5",
            offsets.UI_WPMENU,
            (0.4720, 0.1250),  # T69, 2026-08-05, window 1536x864
        ),
        UIPoint(
            "waypoint.black_marsh",
            offsets.UI_WPMENU,
            (0.2370, 0.4664),  # T69, 2026-08-05, window 1536x864
        ),
        UIPoint(
            "waypoint.arcane_sanctuary",
            offsets.UI_WPMENU,
            (0.3503, 0.6400),  # T69, 2026-08-05, window 1536x864
        ),
        UIPoint(
            "waypoint.halls_of_pain",
            offsets.UI_WPMENU,
            (0.2318, 0.5255),  # T69, 2026-08-05, window 1536x864
        ),
        UIPoint(
            "waypoint.cold_plains",
            offsets.UI_WPMENU,
            (0.3249, 0.2928),
            note=(
                "T25 waypoint battery: hovered at (499, 253) in the town "
                "list, and the click ARRIVED in area 3 — the strongest proof "
                "any of these points has, since travelling is the whole "
                "effect. Confirmed AREA_COLD_PLAINS = 3 while it was there."
            ),
        ),
        UIPoint(
            "waypoint.rogue_encampment",
            offsets.UI_WPMENU,
            (0.3197, 0.2384),
            note=(
                "Same battery, measured from the Cold Plains end and proved "
                "by arriving back in area 1. Note it sits 47 px ABOVE the "
                "Cold Plains row, so the two are not interchangeable and the "
                "list is not re-ordered by where you are standing."
            ),
        ),
        UIPoint(
            "stash.gold_button",
            offsets.UI_STASH,
            (0.5801, 0.8356),
            note=(
                "T37: hovered at (891, 722); the bot's click then ENTER moved "
                "12435 gold, carried 12435 -> 0 and stashed 805539 -> 817974. "
                "A fraction is legitimate here — the stash really is fixed "
                "furniture, unlike an NPC dialog row (R97).\n\n"
                "**The amount dialog raises NO panel flag**: the set stayed "
                "['stash'] across the click. So it cannot be gated on or even "
                "detected, and `PanelInput` can only ever guard on the stash "
                "behind it. Two consequences the deposit has to live with — "
                "the dialog's presence is unverifiable, and an ENTER sent "
                "when it is NOT open opens the chat console instead (R89's "
                "mechanism), which is a blocking panel. Hence: verify by the "
                "gold balance, and clear a stray console before retrying.\n\n"
                "The dialog defaults to the whole carried amount, so one "
                "Enter deposits everything."
            ),
        ),
        UIPoint(
            "stash.materials_tab",
            offsets.UI_STASH,
            (0.2188, 0.8426),
            note=(
                "T15, and re-armed against the previous point, so it does not "
                "share T18's defect; T16 then clicked it successfully twice."
            ),
        ),
    )
    return {p.name: p for p in points}
