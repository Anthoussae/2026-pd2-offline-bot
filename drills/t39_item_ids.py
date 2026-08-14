"""T39 — map the R117 item names to PD2's real kind ids, conversationally.

PD2 renumbered item kinds (proven at R54: the potions sit where classic
runes used to), so every name in `config/item_ids.toml`'s [pending] list
needs its id read from the live game before a rule naming it can fire.

**The protocol is a conversation, not a checklist.** The first version of
this drill named items in alphabetical order and made the user hunt for
each one — ~100 rounds, in an order chosen by the machine. The chat return
channel (R120-R123, live-verified) inverts it: the USER puts an item in
the inventory, in whatever order suits them, and TYPES what it is. The bot
reads the kind the game itself files it under and pairs the two.

    user drops an item into the main inventory grid
    -> bot reads its kind and asks "what is this?"
    -> user types a name (or SKIP, or DONE)
    -> bot matches it against the pending list and records the id

Everything is bounded and reversible by design:

  * the match is echoed back before it is recorded, so a mistyped name is
    visible rather than silently wrong;
  * an ambiguous name lists its candidates and asks again;
  * every id is appended to `config/item_ids.learned.toml` IMMEDIATELY, so
    stopping after five items keeps five items;
  * an unfilled id simply stays pending, and a rule naming it keeps
    matching nothing — costing a missed pickup, never a wrong one.

Read-only: the bot sends nothing but its own chat messages.

Run from the repo root (bridge, elevated):
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t39_item_ids
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.perception.chatread import ChatListener  # noqa: E402
from pd2bot.perception.items import read_carried_items  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.pickit import load_item_table  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TABLE_PATH = REPO / "config" / "item_ids.toml"
LEARNED_PATH = REPO / "config" / "item_ids.learned.toml"

ITEM_WAIT_S = 420.0  # how long to wait for the next item before giving up
REPLY_WAIT_S = 180.0  # how long to wait for the user to type a name
MAX_CANDIDATES = 6  # how many near-matches to offer on an ambiguous name


T39 = Drill(
    test_id="T39",
    title="Item ids by conversation (the R117 vocabulary)",
    kind="perception",
    instructions=(
        "READ-ONLY - the bot sends nothing but these chat messages.",
        "Put an item from your stash into the main inventory grid (the top "
        "4 rows). I will read it and ask what it is.",
        "Answer by typing its name in chat - 'ber rune', 'shako', "
        "'worldstone shard'. Close enough is fine, I echo what I matched.",
        "Type SKIP to pass on an item, DONE to finish. Progress saves after "
        "every single item, so stopping early costs nothing.",
        "Items I already know, and items not on the wanted list, I say so "
        "and move on - no typing needed.",
    ),
)


def normalize(text: str) -> str:
    """Fold a typed name toward the vocabulary's naming convention."""
    cleaned = "".join(
        ch.lower() if ch.isalnum() else " " for ch in text
    ).split()
    return "_".join(cleaned)


def match_name(typed: str, pending: set[str]) -> tuple[str | None, list[str]]:
    """(exact-or-unique match, candidates). Never guesses between two."""
    key = normalize(typed)
    if not key:
        return None, []
    if key in pending:
        return key, []
    # A typed name may omit the category suffix ("ber" for "ber_rune") or
    # add words ("perfect ruby gem"). Both are ordinary human shorthand.
    starts = sorted(n for n in pending if n.startswith(key))
    contains = sorted(n for n in pending if key in n and n not in starts)
    tokens = [t for t in key.split("_") if t]
    token_hits = sorted(
        n for n in pending
        if tokens and set(tokens) <= set(n.split("_")) and n not in starts + contains
    )
    # Last tier: every typed word is the START of a word in the name. This
    # is what makes possessives and plurals forgiving — "lilith mirror"
    # finds "liliths_mirror", "trang oul jawbone" finds "trang_ouls_...".
    # Deliberately last, so it can never outrank an exact word match.
    seen = set(starts + contains + token_hits)
    loose = sorted(
        n for n in pending
        if n not in seen
        and tokens
        and all(any(w.startswith(t) for w in n.split("_")) for t in tokens)
    )
    ranked = starts + contains + token_hits + loose
    if len(ranked) == 1:
        return ranked[0], []
    return None, ranked[:MAX_CANDIDATES]


def append_learned(name: str, kind: int) -> None:
    """One line per discovery, appended immediately — a cancel or a crash
    after item 30 must not cost the first 29."""
    if not LEARNED_PATH.exists():
        LEARNED_PATH.write_text(
            "# Item ids read from the live game by the T39 drill.\n"
            "# Machine-appended; merged over item_ids.toml's [pending] list\n"
            "# at load time. Do not hand-edit ids here without a re-drill.\n"
            "[verified]\n",
            encoding="ascii",
        )
    stamp = time.strftime("%Y-%m-%d")
    with open(LEARNED_PATH, "a", encoding="ascii") as fh:
        fh.write(f"{name} = {kind} # T39 {stamp}\n")


def main_grid(session) -> dict[int, object]:
    return {i.unit_id: i for i in read_carried_items(session).main_inventory}


def t39_body(run: DrillRun) -> str:
    session = run.session
    table = load_item_table(TABLE_PATH)
    pending = set(table.pending)
    known_by_kind = {kind: name for name, kind in table.ids.items()}
    if not pending:
        return "nothing pending — the vocabulary is fully verified already"

    listener = ChatListener(
        session,
        console_open=lambda: run.panel_open(offsets.UI_CHAT_CONSOLE),
    )

    def say(text: str) -> None:
        """Say something and remember it, so it is never heard back as a
        reply — S1 answered its own question without this (R122)."""
        run.say(text)
        listener.remember(f"[claude] {text}")

    def await_reply(timeout_s: float = REPLY_WAIT_S) -> str | None:
        deadline = run.clock() + timeout_s
        while run.clock() < deadline:
            run.check_cancel()
            line = listener.poll()
            if line:
                return line.strip()
            run.sleep(0.2)
        return None

    say(f"{len(pending)} item names still need ids. Add one to your inventory.")
    seen: set[int] = set(main_grid(session))
    recorded: dict[str, int] = {}
    skipped = 0

    while pending:
        run.check_cancel()

        # Wait for an item that was not already sitting there.
        def fresh():
            return [
                item for uid, item in main_grid(session).items()
                if uid not in seen
            ]

        if not run.wait_until(lambda: bool(fresh()), timeout_s=ITEM_WAIT_S):
            say("No new item for a while - stopping here. Progress is saved.")
            break
        item = fresh()[0]
        seen.add(item.unit_id)
        kind = item.kind

        if kind in known_by_kind:
            say(f"That is kind {kind} - already known as {known_by_kind[kind]}. Next.")
            continue
        if kind in recorded.values():
            name = next(n for n, k in recorded.items() if k == kind)
            say(f"Kind {kind} - just recorded that as {name}. Next.")
            continue

        say(f"Kind {kind} (quality {item.quality}) - what is it? Type the name, or SKIP.")
        while True:
            reply = await_reply()
            if reply is None:
                say("No answer - stopping here. Progress is saved.")
                pending = set()  # break the outer loop too
                break
            command = normalize(reply)
            if command in ("done", "stop", "finish", "end"):
                say("Finishing up.")
                pending = set()
                break
            if command in ("skip", "pass", "next"):
                skipped += 1
                say(f"Skipped kind {kind}. Next item.")
                break

            name, candidates = match_name(reply, pending)
            if name is None:
                if candidates:
                    say("Did you mean: " + ", ".join(candidates[:MAX_CANDIDATES]) + "?")
                else:
                    say(
                        f"'{reply}' is not on the wanted list. Type another "
                        "name, or SKIP."
                    )
                continue

            recorded[name] = kind
            pending.discard(name)
            append_learned(name, kind)
            print(f"recorded: {name} = {kind} (quality {item.quality})", flush=True)
            say(f"Recorded {name} = kind {kind}. {len(pending)} left. Next item.")
            break

    say(
        f"T39 done: {len(recorded)} id(s) recorded, {skipped} skipped, "
        f"{len(pending)} still pending."
    )
    return (
        f"{len(recorded)} id(s) recorded to {LEARNED_PATH.name} "
        f"({', '.join(sorted(recorded)) if recorded else 'none'}); "
        f"{skipped} skipped; {len(pending)} still pending"
    )


if __name__ == "__main__":
    raise SystemExit(0 if run_drill(T39, t39_body, session=GameSession()) == "PASS" else 1)
