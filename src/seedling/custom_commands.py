"""
`custom-commands.toml`: an organization's own `seed custom <name>` commands
-- EVERY one, whether it's a simple fixed argv or a script with real logic,
declared as one `[[command]]` entry each. One file, one parser, one place to
audit the whole list.

A command is exactly one of two shapes:
  - `run = [...]`     a fixed argv, optionally against a named `venv`.
  - `script = "..."`  a `.py`/`.sh`/`.ps1` file, resolved relative to this
                       TOML file's own directory. For anything that needs
                       real logic, a companion data file, or to chain several
                       `seed` subcommands together -- and for that last case,
                       no special API: `seed` is already a full CLI, so a
                       script just shells out to it (`seed venv ...`,
                       `seed run -n <venv> -- ...`), the same thing
                       `apply_cmd.py` already does internally.

Read only when `config.get("custom_commands")` is set at all, and a bad file
degrades to "no custom commands this run" rather than breaking every other
`seed` command -- see `load()`. This mirrors `profile.py`'s strict-validation
style (fail the whole file, name the offending key) but NOT its "only `seed
apply` reads it" blast radius: this file is read on every invocation that
touches `seed custom`/`seed help`/a `startup_commands` entry, so a typo must
never brick unrelated commands like `seed venv`.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import config

# Same identifier rule `tool_cmd` already uses for conda-forge tool names --
# keeps a custom command's name filesystem/shell-safe and consistent with
# the rest of the codebase.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# .py is the one extension that runs identically on every platform (seed-cli
# runs it with its own interpreter, sys.executable -- always present, no
# dependency on a system python3). .sh/.ps1 are for something that's
# fundamentally a shell one-liner or needs OS-specific behavior.
_SCRIPT_EXTENSIONS = (".py", ".sh", ".ps1")


class CustomCommandsError(ValueError):
    """A custom-commands.toml that cannot be used as written."""


@dataclass
class CustomCommand:
    name: str
    run: list[str] | None = None
    script: Path | None = None
    description: str = ""
    venv: str | None = None
    toplevel: bool = False


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise CustomCommandsError(msg)


def _reject_unknown_keys(entry: dict, known: set[str], where: str) -> None:
    """Same reasoning as profile.py's identical helper: a typo'd key is
    otherwise silently ignored by tomllib, which is exactly the "discovered
    by users, one at a time" failure mode "validation is strict" exists to
    avoid."""
    unknown = sorted(set(entry) - known)
    _require(not unknown,
             f"{where}: unknown key(s) {', '.join(unknown)} -- "
             f"expected only {', '.join(sorted(known))}")


def parse(text: str, *, path: Path | None = None) -> list[CustomCommand]:
    """Parse and validate custom-commands.toml. Raises CustomCommandsError
    naming the offending key -- fails the whole file rather than skipping a
    bad entry, same reasoning as `profile.parse()`: a typo that silently
    drops a command would be discovered by users, one at a time.

    `path` is this file's own location, used to resolve a `script` value
    (relative to the directory THIS file lives in, so an org's scripts ship
    alongside their custom-commands.toml with no separate directory setting
    to keep in sync). Left relative when `path` is None -- fine for parsing
    a raw string that will never actually dispatch a script command."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise CustomCommandsError(f"not valid TOML: {e}") from e

    _reject_unknown_keys(raw, {"command"}, "custom-commands.toml")

    entries = raw.get("command", [])
    _require(isinstance(entries, list), "[[command]] must be a list of tables")

    base_dir = path.parent if path is not None else None

    commands: list[CustomCommand] = []
    names: set[str] = set()
    for entry in entries:
        _require(isinstance(entry, dict), "each [[command]] must be a table")
        _reject_unknown_keys(
            entry, {"name", "run", "script", "description", "venv", "toplevel"},
            "[[command]]")

        name = entry.get("name")
        _require(isinstance(name, str) and name.strip(),
                 "every [[command]] needs a non-empty name")
        name = name.strip()
        _require(_NAME_RE.match(name) is not None,
                 f"command {name!r}: name must start with a letter or digit "
                 f"and contain only letters, digits, '.', '_', or '-'")
        _require(name not in names, f"duplicate command name {name!r}")
        names.add(name)

        run = entry.get("run")
        script = entry.get("script")
        _require(run is not None or script is not None,
                 f"command {name!r}: needs either run or script")
        _require(run is None or script is None,
                 f"command {name!r}: run and script are mutually exclusive "
                 f"-- pick one")

        if run is not None:
            _require(isinstance(run, list) and bool(run),
                     f"command {name!r}: run must be a non-empty list of "
                     f"strings")
            for token in run:
                _require(isinstance(token, str) and token != "",
                         f"command {name!r}: every item in run must be a "
                         f"non-empty string")
            run = list(run)

        script_path = None
        if script is not None:
            _require(isinstance(script, str) and script.strip(),
                     f"command {name!r}: script must be a non-empty string")
            script = script.strip()
            _require(
                any(script.lower().endswith(ext) for ext in _SCRIPT_EXTENSIONS),
                f"command {name!r}: script must end with "
                f"{'/'.join(_SCRIPT_EXTENSIONS)}")
            script_path = Path(script)
            if base_dir is not None and not script_path.is_absolute():
                script_path = base_dir / script_path

        description = entry.get("description", "")
        _require(isinstance(description, str),
                 f"command {name!r}: description must be a string")

        venv = entry.get("venv")
        _require(venv is None or (isinstance(venv, str) and venv.strip()),
                 f"command {name!r}: venv must be a non-empty string")
        _require(venv is None or run is not None,
                 f"command {name!r}: venv only applies to run, not script -- "
                 f"a script already runs in seed-cli's own interpreter/shell "
                 f"and reaches a venv itself via `seed run -n <venv> -- ...`")

        toplevel = entry.get("toplevel", False)
        _require(isinstance(toplevel, bool),
                 f"command {name!r}: toplevel must be true or false")

        commands.append(CustomCommand(
            name=name,
            run=run,
            script=script_path,
            description=description.strip(),
            venv=venv.strip() if isinstance(venv, str) else None,
            toplevel=toplevel,
        ))
    return commands


def resolve_path() -> Path | None:
    """Where custom-commands.toml is, per settings.json -- or None when the
    feature isn't configured at all."""
    raw = config.get("custom_commands")
    if not raw:
        return None
    return Path(str(raw)).expanduser()


def load() -> list[CustomCommand] | None:
    """The parsed commands, or None on ANY problem (missing file, bad TOML,
    a failed validation rule). Deliberately swallows rather than raises:
    unlike a profile (only read by `seed apply`), this is read on every
    `seed custom`/`seed help` invocation, and a typo in an org's file must
    degrade to "no custom commands available" rather than crash. Callers
    that need the actual error message for `seed custom`'s own output should
    call `load_or_raise()` instead."""
    try:
        return load_or_raise()
    except (OSError, CustomCommandsError):
        return None


def load_or_raise() -> list[CustomCommand]:
    path = resolve_path()
    if path is None:
        return []
    text = path.read_text(encoding="utf-8-sig")
    return parse(text, path=path)
