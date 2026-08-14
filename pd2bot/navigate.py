"""Command shim: `python -m pd2bot.navigate` — the machinery lives in nav/navigate.py."""

from pd2bot.nav.navigate import main

if __name__ == "__main__":
    raise SystemExit(main())
