from __future__ import annotations

import os

from .. import lock, uv_tool


def run(args) -> int:
    packages = getattr(args, "packages", None) or []
    if not packages:
        print("Usage: seed uninstall <package> [<package> ...]")
        print("(anything after `uninstall` is passed straight through to `uv pip uninstall`)")
        return 1

    if not os.environ.get("VIRTUAL_ENV"):
        print("Note: no venv looks active (VIRTUAL_ENV isn't set). "
              "Run `seed activate <name>` first, or uv will fall back to "
              "whatever it can find (e.g. a .venv in the current directory).")

    # Same lock as `seed install` -- removing files from site-packages while
    # another command writes to it is the same race from the other side.
    with lock.active_venv_lock():
        uv_tool.run(["pip", "uninstall", *packages])
    return 0
