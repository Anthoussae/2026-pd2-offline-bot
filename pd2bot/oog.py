"""Command shim: `python -m pd2bot.oog` — the machinery lives in perception/oog.py."""

from pd2bot.perception.oog import main

if __name__ == "__main__":
    raise SystemExit(main())
