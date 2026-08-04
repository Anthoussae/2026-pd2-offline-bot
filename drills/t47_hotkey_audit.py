"""T47 — what does each F-key ACTUALLY select? (stage B run 5)

The bot sends input: it presses F1-F6 and reads the right-skill slot back.
No casting, no clicking — a keypress changes which skill is selected and
nothing else.

Run 5 died on

    right skill reads 83 after 3 presses of the hotkey for skill 95

83 is Desecrate, 95 is Revive. So F5 selected desecrate correctly, and
three presses of F6 failed to move the slot to revive. `config/necro.toml`
maps revive to F6, and that mapping came from R52 drill A, where the user
pressed each hotkey while the slot was read — a snapshot of the bindings
as they were that day. Two things it could be now:

  * the client's bindings changed (or Revive was never on F6), so the
    config is stale; or
  * the keypress is not landing, in which case NO key would verify.

The difference is obvious once every key is tried, and guessing between
them would mean editing a config to match a theory. So this presses all
six and prints what each one selects, against what the config claims.

It also catches the quieter version of the same fault: a hotkey that is
merely bound to the WRONG skill still verifies, so the bot would cast the
wrong thing forever without a single error.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t47_hotkey_audit
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot.behavior.combat import load_class_config  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.player import read_active_skills  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

T47 = Drill(
    test_id="T47",
    title="which skill each hotkey actually selects",
    kind="bot control",
    sends_input=True,
    instructions=(
        "Stand in town, safe, with no panels open — then hands off.",
        "The bot presses F1 through F6 and reads back which skill each",
        "  one selected. It does NOT cast: a hotkey changes the selected",
        "  skill and nothing else.",
        "Cancel any time: powershell -File tools\\drill-cancel.ps1",
    ),
)


def t47_body(run: DrillRun) -> str:
    if run.player_is_dead():
        raise DrillAborted("the character is dead — this drill sends nothing")

    config = load_class_config(REPO / "config" / "necro.toml")
    by_id = {skill_id: name for name, skill_id in config.skills.items()}
    # config.hotkeys is {skill id: VK}; invert to ask "what should F_n be?"
    expected = {vk: skill_id for skill_id, vk in config.hotkeys.items()}

    gated = GatedInput(run.session, ui_array=run.ui_array)
    lines: list[str] = []
    for vk, wanted in sorted(expected.items()):
        run.check_cancel()
        key_name = f"VK {vk:#04x}"
        gated.press_key(vk)
        run.sleep(0.35)  # the client samples input per frame at 25 fps
        active = read_active_skills(run.session)
        got = None if active is None else active.right_id
        verdict = (
            "OK" if got == wanted
            else f"MISMATCH — config says {by_id.get(wanted, wanted)}"
        )
        lines.append(
            f"{key_name}: selected {got} ({by_id.get(got, 'unknown')}), "
            f"expected {wanted} ({by_id.get(wanted, wanted)}) — {verdict}"
        )
        print(f"  {lines[-1]}", flush=True)

    mismatches = [line for line in lines if "MISMATCH" in line]
    if len(mismatches) == len(lines):
        summary = (
            "EVERY key mismatched — that is a keypress problem, not a "
            "config one; do not edit necro.toml"
        )
    elif mismatches:
        summary = (
            f"{len(mismatches)} of {len(lines)} keys disagree with the "
            "config — the bindings moved; necro.toml [hotkeys] needs updating"
        )
    else:
        summary = "all six agree with the config"
    print(f"\n  {summary}", flush=True)
    run.make_chat_possible(may_send_input=True)
    run.say("T47 done — see the terminal.")
    return summary + "; " + "; ".join(lines)


if __name__ == "__main__":
    status = run_drill(T47, t47_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
