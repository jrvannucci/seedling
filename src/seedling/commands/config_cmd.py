"""
`seed config` -- view and change seedling's own settings.

    seed config                     show every setting (and where the file is)
    seed config get <key>           print one value
    seed config set <key> <value>   change a value
    seed config unset <key>         reset a value to its built-in default

List-valued keys (venv_default_packages) take comma-separated input:
    seed config set venv_default_packages "ipython,ruff,requests"

The keys worth knowing about:
  - update_source: lets `seed update-commands` work on networks with their
    own GitHub host (set a git URL) or no git hosting at all (set a plain
    directory path, e.g. a network drive holding a copy of this repo).
  - default_venv: auto-activated by every new shell.
"""

from __future__ import annotations

import json

from .. import colors, config, paths

_LIST_KEYS = {"venv_default_packages"}
_BOOL_KEYS = {"native_tls", "auto_activate"}


def _format_value(value) -> str:
    if value is None:
        return colors.dim("(not set)")
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _parse_value(key: str, raw: str):
    if key in _LIST_KEYS:
        return [item.strip() for item in raw.split(",") if item.strip()]
    if key in _BOOL_KEYS:
        # Booleans are true/false (any case) -- stored as a real bool, since
        # the string "false" would otherwise read back as truthy.
        return raw.strip().lower() == "true"
    return raw


def _validate(key: str, value) -> str | None:
    """Returns an error message, or None if the value is acceptable."""
    if key == "default_venv" and isinstance(value, str):
        if not paths.venv_dir(value).exists():
            return (f"warning-only: no venv named '{value}' exists yet "
                    f"(expected at {paths.venv_dir(value)})")
    if key == "default_base" and isinstance(value, str):
        if not paths.base_alias_file(value).exists():
            return (f"warning-only: no base Python '{value}' is installed yet "
                    f"(run `seed python {value}`)")
    return None


def show(args) -> int:
    data = config.load()
    print(f"seedling settings ({paths.CONFIG_FILE}):")
    print()
    for key, description in config.KNOWN_KEYS.items():
        print(f"  {colors.bold(key)} = {_format_value(data.get(key))}")
        print(colors.dim(f"      {description}"))
    unknown = sorted(set(data) - set(config.KNOWN_KEYS))
    if unknown:
        print()
        print(colors.warn("Keys in settings.json that seedling doesn't recognize:"))
        for key in unknown:
            print(f"  {key} = {json.dumps(data[key])}")
    print()
    print("Change one with:  seed config set <key> <value>")
    return 0


def get(args) -> int:
    key = args.key
    if key not in config.KNOWN_KEYS:
        print(f"Unknown key '{key}'. Known keys: {', '.join(config.KNOWN_KEYS)}")
        return 1
    value = config.get(key)
    if isinstance(value, list):
        print(",".join(str(v) for v in value))
    elif value is not None:
        print(value)
    # not-set prints nothing, so scripts can test for emptiness
    return 0


def set_(args) -> int:
    key = args.key
    if key not in config.KNOWN_KEYS:
        print(f"Unknown key '{key}'. Known keys: {', '.join(config.KNOWN_KEYS)}")
        return 1
    value = _parse_value(key, args.value)
    warning = _validate(key, value)
    if warning:
        print(colors.warn(warning))
    config.set_value(key, value)
    print(colors.ok(f"Set {key} = {_format_value(value)}"))
    if key == "default_venv":
        print("New shells will auto-activate it. (Existing shells are unaffected.)")
    return 0


def unset(args) -> int:
    key = args.key
    if key not in config.KNOWN_KEYS:
        print(f"Unknown key '{key}'. Known keys: {', '.join(config.KNOWN_KEYS)}")
        return 1
    config.unset(key)
    print(colors.ok(f"Reset {key} to its default: {_format_value(config.default_of(key))}"))
    return 0


def run(args) -> int:
    action = getattr(args, "action", None)
    if action == "get":
        return get(args)
    if action == "set":
        return set_(args)
    if action == "unset":
        return unset(args)
    return show(args)
