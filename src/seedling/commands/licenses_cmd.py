"""
`seed venv-licenses` / `seed whl-licenses` / `seed forge-licenses` --
what is everything here licensed under, and what needs a decision?

Three commands rather than one that switches on its argument, because they
answer different people's questions at different moments: a developer asking
what they're running, an admin asking what is about to go onto a share, and
the same admin asking it about the non-Python half. Each sits beside its own
family (`venv-list`, `upload-whls`, `forge-list`) and they share everything
below the surface.

The report leads with the shape and then names the exceptions, because that
is the actual work: 170 packages is not a review, 11 is.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .. import colors, licenses, venv_target

SCHEMA = 1


def _site_packages(venv_dir: Path) -> Path | None:
    """Where a venv keeps its distributions, on either layout."""
    windows = venv_dir / "Lib" / "site-packages"
    if windows.is_dir():
        return windows
    for lib in sorted((venv_dir / "lib").glob("python*")):
        candidate = lib / "site-packages"
        if candidate.is_dir():
            return candidate
    return None


def _emit(packages: list[licenses.PackageLicence], args, *, subject: str) -> int:
    """One report for all three commands."""
    show_all = getattr(args, "all", False)
    fail_on = {f.strip() for f in (getattr(args, "fail_on", None) or "").split(",")
               if f.strip()}
    attention = licenses.needs_attention(packages)

    if getattr(args, "json", False):
        print(json.dumps({
            "schema": SCHEMA,
            "subject": subject,
            "total": len(packages),
            "summary": licenses.summarize(packages),
            "packages": [p.as_dict() for p in packages],
        }, indent=2))
    else:
        print(f"Licences in {subject}  ({len(packages)} package"
              f"{'' if len(packages) == 1 else 's'})")
        print()
        if not packages:
            print("  Nothing found here.")
            return 0
        for family, count in licenses.summarize(packages).items():
            label = colors.ok(f"{family:18}") if family in licenses.ROUTINE \
                else colors.warn(f"{family:18}")
            print(f"  {label} {count:5}   {licenses.OBLIGATIONS.get(family, '')}")
        print()

        listed = packages if show_all else attention
        if not listed:
            print(colors.ok("  Everything here is permissive or public domain."))
        else:
            heading = "Every package:" if show_all else \
                f"Needs a decision ({len(attention)}):"
            print(heading)
            rank = {f: i for i, f in enumerate(licenses.SEVERITY)}
            for p in sorted(listed, key=lambda q: (rank.get(q.family, 99),
                                                   q.name.lower())):
                print(f"  {p.family:16} {p.name[:26]:27} {p.version[:11]:12}"
                      f"{(p.licence or '-')[:32]:34}{p.source}")
        if not show_all and attention:
            print()
            print(colors.dim("  --all lists every package; --json for the "
                             "machine-readable form."))

    if fail_on:
        hit = [p for p in packages if p.family in fail_on]
        if hit:
            print()
            print(colors.danger(
                f"{len(hit)} package(s) in {', '.join(sorted(fail_on))}: "
                + ", ".join(p.name for p in hit[:8])
                + (" ..." if len(hit) > 8 else "")))
            return 1
    return 0


def venv_licenses(args) -> int:
    """The active venv, or the one named with -n."""
    requested = getattr(args, "venv", None)
    if requested:
        resolved, failure = venv_target.resolve(requested)
        if failure is not None:
            print(f"error: {failure}")
            return 1
        venv_dir, label = resolved.path, requested
    else:
        active = os.environ.get("VIRTUAL_ENV")
        if not active:
            print("No venv is active, and none was named.")
            print("  seed venv-licenses -n <name>   # a specific venv")
            print("  seed activate <name>           # or activate one first")
            return 1
        venv_dir, label = Path(active), Path(active).name

    site = _site_packages(venv_dir)
    if site is None:
        print(f"error: no site-packages under {venv_dir}")
        return 1
    return _emit(licenses.scan_venv(site), args, subject=f"venv {label!r}")


def whl_licenses(args) -> int:
    """A flat directory of wheels -- a wheelhouse, or a bundle's wheels/."""
    target = getattr(args, "directory", None)
    if not target:
        print("Usage: seed whl-licenses <dir> [--all] [--json] "
              "[--fail-on FAMILY,...]")
        return 1
    directory = Path(target).expanduser()
    # A bundle root is the obvious thing to point this at, so accept it.
    if not directory.is_dir() and (directory / "wheels").is_dir():
        directory = directory / "wheels"
    if not directory.is_dir():
        print(f"error: no such directory: {directory}")
        return 1
    if (directory / "wheels").is_dir() and not any(directory.glob("*.whl")):
        directory = directory / "wheels"

    packages = licenses.scan_wheelhouse(directory)
    if not packages:
        print(f"No .whl files in {directory}")
        return 1
    return _emit(packages, args, subject=str(directory))


def forge_licenses(args) -> int:
    """A bundled conda channel, read from its repodata."""
    target = getattr(args, "directory", None)
    from .. import config
    if not target:
        configured = config.get("conda_channel")
        if configured and "://" not in str(configured):
            target = str(configured)
    if not target:
        print("Usage: seed forge-licenses <channel-dir>")
        print("Defaults to the configured conda_channel when it's a "
              "directory (an offline bundle's conda-channel/).")
        return 1
    directory = Path(target).expanduser()
    if not directory.is_dir():
        print(f"error: no such directory: {directory}")
        return 1
    packages = licenses.scan_conda_channel(directory)
    if not packages:
        print(f"No repodata.json found under {directory}")
        return 1
    return _emit(packages, args, subject=str(directory))
