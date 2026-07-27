from __future__ import annotations

import os

from .. import lock, uv_tool


def run(args) -> int:
    packages = getattr(args, "packages", None) or []
    if not packages:
        print("Usage: seed install <package> [<package> ...]")
        print("(anything after `install` is passed straight through to `uv pip install`)")
        return 1

    if not os.environ.get("VIRTUAL_ENV"):
        print("Note: no venv looks active (VIRTUAL_ENV isn't set). "
              "Run `seed activate <name>` first, or uv will fall back to "
              "whatever it can find (e.g. a .venv in the current directory).")

    # Held for the whole install: two of these unpacking wheels into one
    # site-packages can leave a half-written distribution behind.
    with lock.active_venv_lock():
        uv_tool.run(["pip", "install", *packages])
    return 0
