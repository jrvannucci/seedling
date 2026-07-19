from __future__ import annotations

import os

from .. import confirm, fsutil, paths

_KILL_NOTE = fsutil.ESCALATION_NOTE


def _warn_if_active(target) -> None:
    active = os.environ.get("VIRTUAL_ENV")
    if active and os.path.abspath(active) == os.path.abspath(str(target)):
        print(f"Note: '{target.name}' looks like your currently active venv. "
              "Anything still running from it will be closed if it blocks "
              "deletion; your shell deactivates it automatically once it's "
              "gone.")




def run_all(args) -> int:
    if not paths.VENVS_DIR.exists():
        print("No venvs to remove.")
        return 0

    venvs = sorted(d for d in paths.VENVS_DIR.iterdir() if d.is_dir())
    if not venvs:
        print("No venvs to remove.")
        return 0

    if confirm.preview_requested(args):
        confirm.print_preview(
            f"delete {len(venvs)} venv(s)",
            [str(v) for v in venvs],
            notes=[_KILL_NOTE],
        )
        return 0

    for v in venvs:
        _warn_if_active(v)

    if not confirm.auto_confirmed(args):
        print(f"This will permanently delete {len(venvs)} venv(s) from {paths.VENVS_DIR}:")
        for v in venvs:
            print(f"  - {v.name}")
        print(f"({fsutil.ESCALATION_NOTE}.)")
    if not confirm.confirm(args):
        print("Aborted. Nothing was deleted.")
        return 1

    all_failures: list[str] = []
    removed = 0
    for v in venvs:
        failures = fsutil.remove_tree(v, label=v.name)
        if failures:
            all_failures.extend(failures)
        else:
            removed += 1

    print(f"Deleted {removed} venv(s).")
    if all_failures:
        print("Some files could not be removed after several attempts:")
        for f in all_failures:
            print(f"  - {f}")
        return 1
    return 0


def run_one(args) -> int:
    if not args.name:
        print("Usage: seed remove-venv <name>")
        return 1

    target = paths.venv_dir(args.name)
    if not target.exists():
        print(f"No venv named '{args.name}' found in {paths.VENVS_DIR}")
        return 1

    if confirm.preview_requested(args):
        confirm.print_preview(
            f"delete venv '{args.name}'",
            [str(target)],
            notes=[_KILL_NOTE],
        )
        return 0

    _warn_if_active(target)

    if not confirm.confirm(
        args,
        f"Delete venv '{args.name}' at {target}?",
    ):
        print("Aborted. Nothing was deleted.")
        return 1

    failures = fsutil.remove_tree(target, label=args.name)
    if failures:
        print(f"Some files in '{args.name}' could not be removed after several attempts:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"Deleted venv '{args.name}'.")
    return 0
