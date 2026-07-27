"""
`seed which [name]` -- print the absolute path to a venv's Python
interpreter, and nothing else.

The point is the "nothing else". Every neighbouring command prints helpful
prose to stdout (`seed install` notes when no venv looks active, `venv-list`
prints a header), which is right for a person and fatal for
`$(seed which dev)`. So this command holds to one rule: **stdout carries the
path and only the path**; every diagnostic goes to stderr, and an
unresolvable venv is a non-zero exit rather than a message where a path
should be.

Scope is deliberately venvs only. `--python`/`--app`/`--tool` variants were
considered and dropped: the moment it resolves four unrelated families it
stops being "the venv interpreter" and belongs beside `seed where` as a
general install query instead. `seed summary --json` already answers the
broader question for anything that needs it.
"""

from __future__ import annotations

import json
import sys

from .. import paths, venv_target

# Bump when a field changes meaning or goes away, matching `summary --json`.
# Adding a field doesn't need a bump.
SCHEMA_VERSION = 1


def run(args) -> int:
    target, error = venv_target.resolve(getattr(args, "name", None))
    want_json = getattr(args, "json", False)

    if target is None:
        if want_json:
            # Even the failure is parseable: a consumer that always reads
            # JSON shouldn't have to special-case a bare stderr string.
            print(json.dumps({
                "schema": SCHEMA_VERSION,
                "found": False,
                "reason": error.reason,
                "error": error.message,
            }, indent=2))
        else:
            print(f"error: {error}", file=sys.stderr)
        return 1

    if want_json:
        print(json.dumps({
            "schema": SCHEMA_VERSION,
            "found": True,
            "name": target.name,
            "path": str(target.path),
            "python_executable": str(target.python),
            "bin_dir": str(paths.venv_bin_dir(target.path)),
            "source": target.source,
        }, indent=2))
        return 0

    print(str(target.python))
    return 0
