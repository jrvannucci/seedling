"""
`seed custom [name] [args...]` -- run an organization's own custom command.

Every command comes from one place, `custom_commands.py` (one `[[command]]`
entry per command, `run = [...]` or `script = "..."`) -- this module is just
the dispatcher: look a name up, execute it, and expose the two things
`cli.py` needs for `seed help` and the `toplevel` short-circuit. It has no
opinion about built-in seedling command names -- collision detection against
those lives in `cli.py`, which is the one place that already has the full
built-in list.
"""

from __future__ import annotations

import subprocess
import sys

from .. import config, custom_commands, paths, venv_target
from . import run_cmd

USAGE = "Usage: seed custom <name> [args...]"

# Launcher for a script command, by its own extension -- .py runs with
# seed-cli's own interpreter (always present, no dependency on a system
# python3); .sh/.ps1 use the platform's own shell.
_LAUNCHERS = {
    ".py": lambda path: [sys.executable, str(path)],
    ".sh": lambda path: ["sh", str(path)],
    ".ps1": lambda path: ["powershell", "-NoProfile", "-File", str(path)],
}


def _load_all() -> tuple[dict[str, "custom_commands.CustomCommand"], list[str]]:
    """{name: CustomCommand}, plus a warning worth surfacing (a whole-file
    TOML failure) that doesn't take everything else down."""
    warnings: list[str] = []
    try:
        commands = custom_commands.load_or_raise()
    except (OSError, custom_commands.CustomCommandsError) as e:
        return {}, [f"custom-commands.toml: {e}"]
    return {cmd.name: cmd for cmd in commands}, warnings


def _exec(argv: list[str], *, env=None) -> int:
    """Run argv, passing the child's exit code straight through -- same
    contract as `run_cmd.run()`'s tail (`src/seedling/commands/run_cmd.py`),
    including Ctrl-C -> 130."""
    try:
        completed = subprocess.run(argv, env=env, check=False)
    except OSError as e:
        print(f"error: couldn't run {argv[0]}: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return completed.returncode


def _run(cmd: "custom_commands.CustomCommand", trailing: list[str]) -> int:
    if cmd.run is not None:
        if cmd.venv:
            target, error = venv_target.resolve(cmd.venv)
            if target is None:
                print(f"error: {error}", file=sys.stderr)
                return 1
            env = run_cmd.child_env(target)
            program = run_cmd.resolve_command(cmd.run[0], env)
            if program is None:
                print(f"error: command not found in venv '{target.name}': "
                      f"{cmd.run[0]}", file=sys.stderr)
                return 127
            return _exec([program, *cmd.run[1:], *trailing], env=env)
        return _exec([*cmd.run, *trailing])

    # cmd.script -- validated at parse time to be one of _LAUNCHERS' keys.
    if not cmd.script.is_file():
        print(f"error: custom command '{cmd.name}': script not found at "
              f"{cmd.script}", file=sys.stderr)
        return 1
    launcher = _LAUNCHERS[cmd.script.suffix.lower()]
    return _exec([*launcher(cmd.script), *trailing])


def _print_available(index: dict, warnings: list[str]) -> None:
    if warnings:
        for w in warnings:
            print(f"warning: {w}")
    if not index:
        print("No custom commands configured.")
        return
    print("Custom commands:")
    for name in sorted(index):
        cmd = index[name]
        suffix = "  (also: seed " + name + ")" if cmd.toplevel else ""
        print(f"  {name:<20} {cmd.description}{suffix}")


def run(args) -> int:
    name = getattr(args, "name", None)
    trailing = getattr(args, "cmdargs", None) or []

    index, warnings = _load_all()

    if not name:
        print(USAGE)
        _print_available(index, warnings)
        return 1 if not index else 0

    for w in warnings:
        print(f"warning: {w}")

    cmd = index.get(name)
    if cmd is None:
        print(f"No custom command named '{name}'.")
        if index:
            print("Available: " + ", ".join(sorted(index)))
        return 1

    paths.ensure_layout()
    config.apply_runtime_env()
    return _run(cmd, trailing)


def help_rows() -> list[tuple[str, str, str]]:
    """`seed help`'s Custom commands group, same shape as
    `editors.help_rows()` (`src/seedling/commands/editors.py:150-170`).
    Silently empty (no group shown at all) when nothing is configured or the
    file can't be read -- `seed custom` is where load problems are
    surfaced, not the general help screen."""
    index, _warnings = _load_all()
    rows = []
    for name in sorted(index):
        cmd = index[name]
        desc = cmd.description
        if cmd.toplevel:
            desc = (desc + "  (also: seed " + name + ")").strip()
        rows.append(("custom " + name, "[args...]", desc))
    return rows


def known_names() -> set[str]:
    """Every declared custom command name. Used by `seed config set
    startup_commands` to warn about a name that isn't declared anywhere --
    never raises, since a config edit must not depend on custom-commands.toml
    being valid at that moment."""
    index, _warnings = _load_all()
    return set(index)


def toplevel_map() -> dict[str, "custom_commands.CustomCommand"]:
    """The toplevel=True entries, keyed by name -- for cli.py's pre-argparse
    `seed <name>` short-circuit. Never raises."""
    index, _warnings = _load_all()
    return {name: cmd for name, cmd in index.items() if cmd.toplevel}


def run_direct(cmd: "custom_commands.CustomCommand", trailing: list[str]) -> int:
    """Entry point for cli.py's top-level short-circuit -- same execution
    path as `seed custom <name>`, just reached via `seed <name>` instead."""
    paths.ensure_layout()
    config.apply_runtime_env()
    return _run(cmd, trailing)
