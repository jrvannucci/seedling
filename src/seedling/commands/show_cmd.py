"""
`seed show <package>` -- passthrough to `uv pip show` for the active venv,
the read-only counterpart of `seed install`/`seed package-list`.

`check=False`, not the default: `uv pip show` exits non-zero for a package
that isn't installed (uv's own "WARNING: Package(s) not found: ..." already
streams live), and that is the normal, expected way to learn a package
isn't there -- not a seedling-level failure worth wrapping in a second
"error: ... failed" line the way an unexpected uv crash would be.
"""

from __future__ import annotations

import os

from .. import uv_tool

_NO_VENV_NOTE = ("Note: no venv looks active (VIRTUAL_ENV isn't set). "
                 "Run `seed activate <name>` first, or uv will fall back to "
                 "whatever it can find (e.g. a .venv in the current directory).")


def run(args) -> int:
    packages = getattr(args, "packages", None) or []
    if not packages:
        print("Usage: seed show <package> [<package> ...]")
        print("(anything after `show` is passed straight through to `uv pip show`)")
        return 1

    if not os.environ.get("VIRTUAL_ENV"):
        print(_NO_VENV_NOTE)

    result = uv_tool.run(["pip", "show", *packages], check=False)
    return result.returncode
