# 001 — the run chat-abort shares a one-line buffer with the bot's own says

**Severity:** P3

**Where:** `pd2bot/wiring.py::run_stop_channel` (39d3946), against
`pd2bot/input/chat.py::Chat.say` and
`pd2bot/perception/chatread.py::ChatListener`.

## What is wrong

`Chat.say` sends UNPREFIXED text (the `[claude]` prefix is partyline's
own addition, not Chat's), and the client keeps ONE chat line. Two
consequences for the new run abort channel:

1. **A typed abort can be overwritten.** The operator types `abort` →
   the buffer holds it → if the bot says anything before the next
   `should_stop` poll reads the buffer, the abort is gone. The window
   is small (the poll runs every tick and inside every walk, while the
   bot says a handful of lines per round), but it exists — and it is
   widest exactly when the battery is chatty (round scores, gather
   nags).
2. **Bot lines are read back as human.** `ChatListener._is_our_echo`
   filters on the `[claude]` prefix, which run-side says do not carry.
   Today this is harmless — an abort trips only on a line EQUAL to an
   abort word, and no announcement is one — but any future run-side
   say that echoes operator text (a confirmation quote, say) could
   self-abort the run.

## Why it matters

The abort channel was built precisely because launch 1 could not be
stopped; a lost abort re-opens that hole for one press. The cancel FILE
remains reliable, and the ESC kill switch remains, so the exposure is a
retype, not a trapped run.

## Suggested fix

Either have run-side chat register its says with the listener
(`ChatListener.remember`, the partyline/drill pattern — the wiring owns
both objects and can thread them), or hold unclaimed lines the way
`DrillRun._chat_line` does so a bot say cannot displace an unread
human line. Prefer the first: it also fixes the echo hazard.

## Validation

A unit test where the fake buffer receives "abort" followed by a bot
say before the next poll — `should_stop()` must still return True.

## Resolution

RESOLVED 2026-08-14 (P6 closeout): `wiring.registered_say` wraps every run-side say - polls the abort channel FIRST (sticky once seen), registers the text with the listener (`remember`), then speaks. Both hazards closed; validated by test_a_bot_say_cannot_displace_an_unread_abort.
