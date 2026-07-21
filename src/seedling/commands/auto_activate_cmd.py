"""
`seed auto-activate [True|False]` -- show or set whether new shells
auto-activate the `default_venv` at startup. Sugar over the `auto_activate`
setting, promoted to its own command because it's a thing people reach for
directly ("stop activating dev in every terminal") without wanting to think
about config keys.

Distinct from `default_venv`: that names WHICH venv; this decides WHETHER it
activates automatically. Turning auto-activation off leaves the default venv
set -- `seed activate` still works, and turning it back on resumes activating
the same venv.
"""

from __future__ import annotations

from .. import colors, config

_TRUE = {"true", "on", "yes", "1"}
_FALSE = {"false", "off", "no", "0"}


def run(args) -> int:
    state = getattr(args, "state", None)

    if state is None:
        enabled = config.get("auto_activate")
        default = config.get("default_venv")
        if enabled:
            if default:
                print(f"Auto-activation is ON: new shells activate '{default}'.")
            else:
                print("Auto-activation is ON, but no default venv is set, so "
                      "new shells start with none active.")
                print("Set one with:  seed venv-default <name>")
        else:
            suffix = f" (would be '{default}')" if default else ""
            print(f"Auto-activation is OFF{suffix}: new shells start with no "
                  "venv active.")
        print("Change it with:  seed auto-activate True|False")
        return 0

    raw = state.strip().lower()
    if raw in _TRUE:
        value = True
    elif raw in _FALSE:
        value = False
    else:
        print(f"error: expected True or False, got '{state}'.")
        print("Usage:  seed auto-activate True|False")
        return 1

    config.set_value("auto_activate", value)
    if value:
        default = config.get("default_venv")
        target = f" '{default}'" if default else " the default venv"
        print(colors.ok(f"Done. New shells will auto-activate{target}."))
    else:
        print(colors.ok("Done. New shells will not auto-activate any venv."))
    print("(Existing shells are unaffected -- open a new terminal to see it.)")
    return 0
