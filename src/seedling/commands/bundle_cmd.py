"""
`seed profile-check` -- will this profile actually apply here?

The air-gapped half of the bundle story. `build-offline` validates the
profiles it ships before it downloads anything, but the profiles that matter
most are often written LATER, by someone inside the network who wants a new
venv set for their team and has no way to find out what the share holds short
of applying it and watching it fail.

This answers that question directly, against the bundle on disk -- not
against what anyone intended it to contain.
"""

from __future__ import annotations

from pathlib import Path

from .. import bundle as bundle_mod, colors, config, profile as profile_mod


def _bundle_root(explicit: str | None) -> Path | None:
    """Where the bundle lives, cheapest source first.

    On a machine installed from a bundle, `package_index` already points at
    its wheels directory -- so the answer is one level up from a setting the
    install itself wrote, and the common case needs no argument at all."""
    if explicit:
        return Path(explicit).expanduser()
    index = config.get("package_index")
    if index and "://" not in str(index):
        wheels = Path(str(index)).expanduser()
        if wheels.name == "wheels" and wheels.parent.is_dir():
            return wheels.parent
    return None


def check(args) -> int:
    root = _bundle_root(getattr(args, "bundle", None))
    if root is None:
        print("Couldn't work out which bundle to check against.")
        print("  Pass one:  seed profile-check <profile.toml> --bundle <path>")
        print("  (it's found automatically when package_index is a directory "
              "of wheels inside a bundle)")
        return 1
    if not root.is_dir():
        print(f"No bundle at {root}")
        return 1

    profile_path = profile_mod.find(getattr(args, "profile", None))
    if profile_path is None:
        print("No profile to check. Pass one, or put a profile.toml in this "
              "directory.")
        return 1
    try:
        prof = profile_mod.load(profile_path)
    except profile_mod.ProfileError as e:
        # Exit 2 for "the profile itself is wrong", matching `seed apply` --
        # a broken file and an unsatisfiable one are different problems with
        # different fixes.
        print(f"error: {profile_path}: {e}")
        return 2

    inv = bundle_mod.Inventory.discover(root)
    problems = bundle_mod.check_profile(prof, inv)

    print(f"Profile: {profile_path}")
    print(f"Bundle:  {root}")
    print(f"  {len(inv.packages)} distributions, "
          f"{len(inv.pythons) or 'no'} interpreter(s), "
          f"{len(inv.tools)} conda-forge package(s)"
          + (", VS Code staged" if inv.vscode else ""))
    print()

    if not problems:
        print(colors.ok("This profile applies cleanly against this bundle."))
        return 0

    print(colors.warn(f"{len(problems)} thing(s) this bundle can't satisfy:"))
    for problem in problems:
        print(f"  - {problem}")
    print()
    print("Fix the profile, or rebuild the bundle with these included "
          "(offline-bundle.toml on the connected machine).")
    return 1
