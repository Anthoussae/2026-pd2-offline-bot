"""Command shim: `python -m pd2bot.collision` — the machinery lives in nav/collision.py."""

from pd2bot.nav.collision import main

if __name__ == "__main__":
    raise SystemExit(main())
