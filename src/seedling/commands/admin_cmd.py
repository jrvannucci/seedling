"""
The `admin-*` command family: elevated, cross-user teardown of a
shared-root install. Hidden from normal help (see `seed help --admin`).

Every command here:
  - refuses to run unless elevated (Administrator / root),
  - operates on ANOTHER user's home (or all of them), resolved under the
    shared root,
  - seizes ownership before deleting so user-owned / read-only / runtime
    files don't block the teardown,
  - honors --preview / -y / --non-interactive like the ordinary
    destructive commands.
"""

from __future__ import annotations


from .. import admin, colors, confirm
from . import kill_cmd


def _report(failures: list) -> int:
    if failures:
        print()
        print(colors.warn("Some files could not be removed even after taking "
                          "ownership:"))
        for f in failures:
            print(f"  - {f}")
        print("Something outside seedling may still hold them open (a logged-in "
              "session, antivirus). Close it and re-run.")
        return 1
    return 0


# --- whole-machine and whole-user ------------------------------------------

def purge_all_users(args) -> int:
    """admin-purge-all-users -- remove every user's seedling home under the
    shared root, plus every user's shell hook."""
    if not admin.require_elevation():
        return 1
    root = admin.require_shared_root()
    if root is None:
        return 1
    homes = admin.list_user_homes()
    if not homes:
        print(f"No per-user seedling installs found under {root}. Nothing to do.")
        return 0

    if confirm.preview_requested(args):
        confirm.print_preview(
            f"purge ALL {len(homes)} user install(s) under {root}",
            [str(h) for h in homes],
            notes=["ownership is taken first, so other users' protected files "
                   "are removed too",
                   "every user's `seed` shell hook is stripped from their profile",
                   "running Python/VS Code processes (all users) are force-closed"],
        )
        return 0

    if not confirm.auto_confirmed(args):
        print(colors.danger(f"This removes EVERY user's seedling install under {root}:"))
        for h in homes:
            print(f"  - {h}")
        print("It takes ownership of their files, force-closes all Python/VS "
              "Code processes, and strips every user's shell hook.")
    if not confirm.confirm(args):
        print("Aborted. Nothing was removed.")
        return 1
    print()

    print("Closing Python and VS Code processes so nothing is left in use...")
    kill_cmd.kill_python_and_vscode()

    failures: list = []
    for h in homes:
        print(f"Removing {h} ...")
        failures.extend(admin.force_delete(h))

    # the shared root itself, once empty
    if root.exists() and not any(root.iterdir()):
        failures.extend(admin.force_delete(root))

    stripped = _strip_all_hooks(root)
    print()
    if stripped:
        print(f"Removed the seedling shell hook from {stripped} user profile(s).")
    print(colors.ok("All-users purge complete."))
    return _report(failures)


def remove_user(args) -> int:
    """admin-remove-user <user> -- remove one user's entire seedling home."""
    if not admin.require_elevation():
        return 1
    if admin.require_shared_root() is None:
        return 1
    user = getattr(args, "user", None)
    if not user:
        print("Usage: seed admin-remove-user <user>")
        return 1
    home = admin.resolve_user_home(user)
    if home is None:
        print(f"No seedling install for user '{user}' under {admin.shared_root()}.")
        return 1
    return _confirm_and_delete(args, f"remove {user}'s entire seedling install",
                               [home], close_procs=True)


# --- granular per-user removes ---------------------------------------------

def venv_remove(args) -> int:
    """admin-remove-venv <user> <name>"""
    home = _user_home_or_none(args)
    if home is None:
        return 1
    target = home / "python" / "venvs" / args.name
    if not target.exists():
        print(f"No venv '{args.name}' for user '{args.user}'.")
        return 1
    return _confirm_and_delete(args, f"remove {args.user}'s venv '{args.name}'",
                               [target], close_procs=True)


def venv_remove_all(args) -> int:
    """admin-remove-venv-all <user>"""
    home = _user_home_or_none(args)
    if home is None:
        return 1
    venvs_dir = home / "python" / "venvs"
    venvs = sorted(d for d in venvs_dir.iterdir() if d.is_dir()) if venvs_dir.exists() else []
    if not venvs:
        print(f"User '{args.user}' has no venvs.")
        return 0
    return _confirm_and_delete(args, f"remove all {len(venvs)} of {args.user}'s venvs",
                               venvs, close_procs=True)


def python_remove(args) -> int:
    """admin-remove-python <user> <tag> -- base Python + venvs built on it."""
    home = _user_home_or_none(args)
    if home is None:
        return 1
    base_dir = home / "python" / "base"
    alias = base_dir / f"{args.tag}.alias.json"
    if not alias.exists():
        print(f"No base Python '{args.tag}' for user '{args.user}'.")
        return 1
    import json
    try:
        target = base_dir / json.loads(alias.read_text())["target"]
    except (json.JSONDecodeError, KeyError, OSError):
        target = None
    targets = [alias]
    if target and target.exists():
        targets.append(target)
        targets.extend(_venvs_using_base(home, target))
    return _confirm_and_delete(
        args, f"remove {args.user}'s base Python '{args.tag}' and its venvs",
        targets, close_procs=True)


def repo_remove(args) -> int:
    """admin-remove-repo <user> <name>"""
    home = _user_home_or_none(args)
    if home is None:
        return 1
    target = home / "repo" / args.name
    if not target.exists():
        print(f"No repo '{args.name}' for user '{args.user}'.")
        return 1
    return _confirm_and_delete(args, f"remove {args.user}'s repo '{args.name}'",
                               [target], close_procs=True)


# --- shared helpers ---------------------------------------------------------

def _user_home_or_none(args):
    if not admin.require_elevation():
        return None
    if admin.require_shared_root() is None:
        return None
    user = getattr(args, "user", None)
    if not user:
        print("Usage: seed admin-<command> <user> ...")
        return None
    home = admin.resolve_user_home(user)
    if home is None:
        print(f"No seedling install for user '{user}' under {admin.shared_root()}.")
        return None
    return home


def _venvs_using_base(home, base_dir) -> list:
    """Venvs under `home` whose pyvenv.cfg points at `base_dir`."""
    matches = []
    venvs_dir = home / "python" / "venvs"
    if not venvs_dir.exists():
        return matches
    base_resolved = str(base_dir.resolve())
    for v in sorted(venvs_dir.iterdir()):
        cfg = v / "pyvenv.cfg"
        if not cfg.exists():
            continue
        try:
            for line in cfg.read_text().splitlines():
                if line.strip().lower().startswith("home"):
                    val = line.split("=", 1)[1].strip()
                    if val.startswith(base_resolved) or base_resolved.startswith(val):
                        matches.append(v)
                    break
        except OSError:
            continue
    return matches


def _confirm_and_delete(args, title, targets, close_procs=False) -> int:
    if confirm.preview_requested(args):
        confirm.print_preview(
            title, [str(t) for t in targets],
            notes=["ownership is taken first, so files owned by that user are "
                   "removed too"])
        return 0
    if not confirm.auto_confirmed(args):
        print(colors.danger(f"This will {title}:"))
        for t in targets:
            print(f"  - {t}")
        print("Ownership of those files is taken first (they belong to another user).")
    if not confirm.confirm(args):
        print("Aborted. Nothing was removed.")
        return 1
    print()
    if close_procs:
        print("Closing Python and VS Code processes so nothing is left in use...")
        kill_cmd.kill_python_and_vscode()
    failures: list = []
    for t in targets:
        failures.extend(admin.force_delete(t))
    if not failures:
        print(colors.ok("Done."))
    return _report(failures)


def _strip_all_hooks(shared_root) -> int:
    """Remove seedling hook lines from every user's profile. A hook line
    here references the shared root and a seed shell script."""
    marker = str(shared_root)
    count = 0
    for profile in admin.all_user_profiles():
        try:
            if not profile.exists():
                continue
            lines = profile.read_text().splitlines()
        except OSError:
            # Best-effort across every user's home: a profile we lack rights
            # to even stat (another user's file, a 0700 home like /root when
            # not elevated) is skipped, not fatal. `exists()` itself calls
            # stat(), so the guard has to cover it too -- not just read_text().
            continue
        kept = [ln for ln in lines
                if not (ln.strip() == "# seedling"
                        or (marker in ln and ("seed.ps1" in ln or "seed.sh" in ln)))]
        if kept != lines:
            try:
                profile.write_text("\n".join(kept).rstrip() + "\n" if kept else "")
                count += 1
            except OSError:
                pass
    return count
