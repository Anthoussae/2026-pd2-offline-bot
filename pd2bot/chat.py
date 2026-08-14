"""Command shim: `python -m pd2bot.chat` — the machinery lives in input/chat.py."""

from pd2bot.input.chat import main

if __name__ == "__main__":
    raise SystemExit(main())
