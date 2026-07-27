"""
Which venv does a command act on?

`seed which` and `seed run` both have to answer that before they can do
anything, and they must answer it the *same* way every other seedling
command does -- it would be its own bug class if `seed run -- pip list`
targeted a different environment than `seed install` just did.

The precedence is the one `seed spyder` already documents:

  1. An explicit name, when the caller says outright. An explicit request
     that can't be honored is an error, never a silent fallback to some
     other environment.
  2. VIRTUAL_ENV -- the venv active in THIS shell. Honored even when it
     points outside ~/seedling, because `seed install` installs into
     whatever is active and these two must not disagree with it about what
     "the current environment" is.
  3. `default_venv` -- so this still works from a shell with nothing
     activated.

Resolution never prints, and never decides policy. It returns a Target, or
a Failure carrying both a message and a machine-readable `reason` -- the
caller decides what that means and where the message belongs. The reason
code exists because the callers genuinely disagree: `seed run` treats any
failure as fatal, while `seed spyder` treats only an explicitly-named venv
as fatal and otherwise opens the editor anyway (see `lenient` on resolve).
Neither may write diagnostics to stdout, which is reserved for the resolved
path and the child's own output.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import config, paths

# Where the answer came from, for --json consumers and error messages.
SOURCE_ARGUMENT = "argument"
SOURCE_VIRTUAL_ENV = "VIRTUAL_ENV"
SOURCE_DEFAULT_VENV = "default_venv"

# Why resolution failed. A code rather than only prose, because callers make
# different decisions per reason and must not have to match on the message.
REASON_NOT_FOUND = "not_found"          # named venv isn't there
REASON_BROKEN = "broken"                # it's there, but has no interpreter
REASON_NONE_CONFIGURED = "none_configured"  # nothing named, active, or default


@dataclass
class Target:
    name: str
    path: Path
    python: Path
    source: str


@dataclass
class Failure:
    reason: str
    source: str | None
    message: str

    def __str__(self) -> str:
        return self.message


def _broken(path: Path) -> str:
    return (f"venv at {path} has no python interpreter at "
            f"{paths.venv_python_path(path)} -- recreate it with "
            f"`seed venv {path.name}`")


def resolve(explicit: str | None = None,
            lenient: bool = False) -> tuple[Target | None, Failure | None]:
    """Returns (target, None) or (None, failure). Exactly one is set.

    `lenient` changes what a BROKEN link does, not the precedence. Strict
    (the default) stops: `seed run` and `seed which` must never quietly act
    on a different environment than the one the caller is pointing at, so a
    dangling VIRTUAL_ENV or a stale default_venv is an error. Lenient keeps
    walking down the precedence and, failing that, reports
    REASON_NONE_CONFIGURED -- which is what `seed spyder` wants: an editor
    that refuses to open because `default_venv` names a deleted venv is
    worse than one that opens and says it has no environment.

    An EXPLICIT name is strict either way. Silently substituting a different
    venv for the one someone asked for by name is never the helpful move.
    """
    if explicit:
        venv_path = paths.venv_dir(explicit)
        if not venv_path.is_dir():
            return None, Failure(
                REASON_NOT_FOUND, SOURCE_ARGUMENT,
                f"no venv named '{explicit}' in {paths.VENVS_DIR} -- create "
                f"it with `seed venv {explicit}`, or see `seed venv-list`")
        interpreter = paths.venv_python(venv_path)
        if interpreter is None:
            return None, Failure(REASON_BROKEN, SOURCE_ARGUMENT,
                                 _broken(venv_path))
        return Target(explicit, venv_path, interpreter, SOURCE_ARGUMENT), None

    active = os.environ.get("VIRTUAL_ENV")
    if active:
        venv_path = Path(active)
        interpreter = paths.venv_python(venv_path)
        if interpreter is not None:
            return Target(venv_path.name, venv_path, interpreter,
                          SOURCE_VIRTUAL_ENV), None
        if not lenient:
            return None, Failure(
                REASON_BROKEN, SOURCE_VIRTUAL_ENV,
                f"VIRTUAL_ENV points at {venv_path}, but "
                f"{paths.venv_python_path(venv_path)} isn't there -- the "
                "active venv looks broken or was deleted")

    default_venv = config.get("default_venv")
    if default_venv:
        venv_path = paths.venv_dir(str(default_venv))
        interpreter = paths.venv_python(venv_path)
        if interpreter is not None:
            return Target(str(default_venv), venv_path, interpreter,
                          SOURCE_DEFAULT_VENV), None
        if not lenient:
            return None, Failure(
                REASON_BROKEN, SOURCE_DEFAULT_VENV,
                f"default_venv is set to '{default_venv}', but {venv_path} "
                f"isn't a usable venv -- fix it with `seed venv "
                f"{default_venv}`, or point it elsewhere with "
                "`seed venv-default <name>`")

    return None, Failure(
        REASON_NONE_CONFIGURED, None,
        "no venv to use: none was named, none is active (VIRTUAL_ENV isn't "
        "set), and no default_venv is configured -- name one explicitly or "
        "run `seed venv-default <name>`")
