from __future__ import annotations

from .. import config, confirm, fsutil, paths
from . import python_cmd


def _venvs_using_base(base_dir) -> list:
    """Best-effort match: uv writes the interpreter's directory into each
    venv's pyvenv.cfg as `home`. If that path sits under (or matches) the
    base Python's directory, the venv was built from it."""
    matches = []
    if not paths.VENVS_DIR.exists():
        return matches

    base_resolved = str(base_dir.resolve())
    for v in sorted(paths.VENVS_DIR.iterdir()):
        if not v.is_dir():
            continue
        cfg = v / "pyvenv.cfg"
        if not cfg.exists():
            continue
        try:
            text = cfg.read_text()
        except OSError:
            continue
        for line in text.splitlines():
            if line.strip().lower().startswith("home"):
                home_value = line.split("=", 1)[1].strip()
                if home_value.startswith(base_resolved) or base_resolved.startswith(home_value):
                    matches.append(v)
                break
    return matches


def run(args) -> int:
    tag = getattr(args, "tag", None)
    if not tag:
        print("Usage: seed remove-python <tag>")
        return 1

    base_dir = python_cmd.resolve_base(tag)
    if base_dir is None:
        print(f"No base Python installed with tag '{tag}'. Run: seed python-list")
        return 1

    affected_venvs = _venvs_using_base(base_dir)

    if confirm.preview_requested(args):
        items = [f"{base_dir}  (base Python '{tag}')"]
        items += [f"{v}  (venv built from it)" for v in affected_venvs]
        items.append(f"{paths.base_alias_file(tag)}  (alias file)")
        confirm.print_preview(
            f"delete base Python '{tag}' and {len(affected_venvs)} venv(s)",
            items,
            notes=[fsutil.ESCALATION_NOTE],
        )
        return 0

    if not confirm.auto_confirmed(args):
        print(f"This will delete base Python '{tag}' ({base_dir.name})")
        if affected_venvs:
            print(f"and the {len(affected_venvs)} venv(s) built from it:")
            for v in affected_venvs:
                print(f"  - {v.name}")
        print(f"({fsutil.ESCALATION_NOTE}.)")
    if not confirm.confirm(args):
        print("Aborted. Nothing was deleted.")
        return 1

    all_failures: list[str] = []
    for v in affected_venvs:
        all_failures.extend(fsutil.remove_tree(v, label=v.name))

    all_failures.extend(fsutil.remove_tree(base_dir, label=tag))
    paths.base_alias_file(tag).unlink(missing_ok=True)

    if config.get_default_base() == tag:
        remaining = sorted(
            p.name[: -len(".alias.json")] for p in paths.BASE_DIR.glob("*.alias.json")
        )
        new_default = remaining[0] if remaining else None
        cfg = config.load()
        cfg["default_base"] = new_default
        config.save(cfg)
        if new_default:
            print(f"Default base for `seed venv` switched to '{new_default}'.")
        else:
            print("No base Python interpreters left; `seed venv` will need one installed first.")

    if all_failures:
        print("Some files could not be removed after several attempts:")
        for f in all_failures:
            print(f"  - {f}")
        return 1

    print(f"Removed base Python '{tag}' and {len(affected_venvs)} associated venv(s).")
    return 0
