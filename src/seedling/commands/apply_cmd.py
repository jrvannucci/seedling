"""
`seed apply` -- bring this machine in line with a deployment profile.

Deliberately an ORCHESTRATOR: every step below is an existing `seed` command
(`python`, `venv`, `install`, `repo-clone`, `repo-install`, `config set`)
driven through its own entry point. Nothing here reimplements interpreter
resolution, venv creation or package installation, so a profile can only do
what a user could have done by hand -- and it inherits those commands' own
error handling, logging and offline behavior for free.

Idempotent by design. Applying a profile twice is a no-op, because the same
file is both the initial provisioning step at install time AND the mechanism
for keeping a fleet converged afterwards: the admin edits the profile, users
re-run `seed apply`, and only the difference is acted on.

It never destroys. An existing venv is left exactly as it is; --force adds
the profile's missing packages to it but still won't recreate or delete
anything. Removing something is `seed remove-venv`, explicitly, by a person
who meant it.
"""

from __future__ import annotations

from argparse import Namespace

import os

from .. import colors, config, confirm, paths, profile as profile_mod, uv_tool
from . import python_cmd, repo_cmd, venv_cmd


def _install_into(venv_name: str, packages: list[str]) -> bool:
    """Install into a SPECIFIC venv.

    Deliberately not `seed install`: that command targets whatever
    VIRTUAL_ENV points at, which during `seed apply` is either nothing or
    the user's current shell -- so routing profile packages through it would
    install them into the wrong environment. This mirrors how `seed venv`
    installs its own default packages: an explicit --python at the venv's
    interpreter."""
    venv_python = _venv_python(venv_name)
    if venv_python is None:
        print(f"warning: couldn't find {venv_name!r}'s python executable.")
        return False
    result = uv_tool.run(
        ["pip", "install", "--python", str(venv_python), *packages],
        check=False)
    return result.returncode == 0


def _venv_python(name: str):
    """The interpreter inside an existing venv, or None."""
    return venv_cmd._python_interpreter_path_venv(paths.venv_dir(name))


def _installed_packages(name: str) -> set[str]:
    """Distribution names already present in a venv, lowercased. Used to
    decide what --force still has to install; an empty set on any failure so
    a probe problem degrades into "install it again" (harmless) rather than
    "skip it" (leaves the venv wrong)."""
    from .. import uv_tool
    venv_python = _venv_python(name)
    if venv_python is None:
        return set()
    result = uv_tool.run_captured(
        ["pip", "list", "--python", str(venv_python)], check=False)
    if getattr(result, "returncode", 1) != 0:
        return set()
    found = set()
    for line in result.stdout.splitlines()[2:]:   # skip the table header
        part = line.split()
        if part:
            found.add(part[0].strip().lower())
    return found


def _requirement_name(spec: str) -> str:
    """'ruff>=0.5' -> 'ruff'. Comparison only -- the full spec is what gets
    installed."""
    for sep in ("[", "=", ">", "<", "!", "~", " "):
        spec = spec.split(sep)[0]
    return spec.strip().lower()


def _plan(prof: profile_mod.Profile, *, force: bool) -> list[tuple[str, str]]:
    """[(action, description)] for everything that would change. Built before
    anything runs so --preview and the real run can never disagree."""
    steps: list[tuple[str, str]] = []

    for version in prof.pythons:
        if python_cmd.resolve_base(version.replace(".", "")) is None:
            steps.append(("python", f"install Python {version}"))
        else:
            steps.append(("skip", f"Python {version} already installed"))

    for venv in prof.venvs:
        exists = paths.venv_dir(venv.name).exists()
        if not exists:
            detail = f"create venv {venv.name!r}"
            if venv.python:
                detail += f" from base {venv.python}"
            if venv.packages:
                detail += f" with {', '.join(venv.packages)}"
            steps.append(("venv", detail))
            continue
        if force and venv.packages:
            have = _installed_packages(venv.name)
            missing = [p for p in venv.packages
                       if _requirement_name(p) not in have]
            if missing:
                steps.append(("packages",
                              f"add to existing venv {venv.name!r}: "
                              f"{', '.join(missing)}"))
                continue
        steps.append(("skip", f"venv {venv.name!r} already exists"))

    for repo in prof.repos:
        name = repo_cmd._derive_name(repo.url)
        if (paths.REPO_DIR / name).exists():
            steps.append(("skip", f"repo {name!r} already cloned"))
        else:
            steps.append(("repo", f"clone {repo.url}"
                                  + (" and install its dependencies"
                                     if repo.install else "")))

    for key, value in prof.settings.items():
        current = config.get(key)
        if current == value:
            steps.append(("skip", f"{key} already {value!r}"))
        else:
            steps.append(("config", f"set {key} = {value!r}"))

    for venv in prof.venvs:
        if venv.default and config.get("default_venv") != venv.name:
            steps.append(("config", f"set default_venv = {venv.name!r}"))
    return steps


def run(args) -> int:
    explicit = getattr(args, "path", None)
    path = profile_mod.find(explicit)
    if path is None:
        print("No profile to apply.")
        print("Pass one explicitly (`seed apply <file>`), or put a "
              "seedling-profile.toml in this directory.")
        return 1

    try:
        prof = profile_mod.load(path)
    except profile_mod.ProfileError as e:
        # Exit 2, not 1: an invalid profile is a configuration error the
        # admin must fix, distinct from a step that failed at runtime.
        print(f"error: {path}: {e}")
        return 2

    print(f"Profile: {path}")
    force = getattr(args, "force", False)
    steps = _plan(prof, force=force)
    changes = [s for s in steps if s[0] != "skip"]

    if confirm.preview_requested(args):
        confirm.print_preview(
            f"apply {path}",
            [d for _, d in steps] or ["(nothing -- the profile is empty)"],
            notes=["'already ...' lines are skipped; nothing is ever "
                   "deleted or recreated by apply"],
        )
        return 0

    if not changes:
        print(colors.ok("Already up to date -- nothing to do."))
        return 0

    print(f"{len(changes)} change(s) to make:")
    for _, description in changes:
        print(f"  - {description}")
    print()

    failed: list[str] = []

    for version in prof.pythons:
        if python_cmd.resolve_base(version.replace(".", "")) is not None:
            continue
        if python_cmd.run(Namespace(version=version)) != 0:
            failed.append(f"python {version}")

    for venv in prof.venvs:
        if not paths.venv_dir(venv.name).exists():
            rc = venv_cmd.run(Namespace(
                name=venv.name,
                python=venv.python,
                no_default_packages=(venv.default_packages is False),
            ))
            if rc != 0:
                failed.append(f"venv {venv.name}")
                continue
            wanted = venv.packages
        elif force and venv.packages:
            have = _installed_packages(venv.name)
            wanted = [p for p in venv.packages
                      if _requirement_name(p) not in have]
        else:
            continue

        if wanted and not _install_into(venv.name, list(wanted)):
            failed.append(f"packages for {venv.name}")

    target_venv = next((v.name for v in prof.venvs if v.default), None)
    for repo in prof.repos:
        name = repo_cmd._derive_name(repo.url)
        if (paths.REPO_DIR / name).exists():
            continue
        if repo_cmd.clone(Namespace(url=repo.url)) != 0:
            failed.append(f"repo {name}")
            continue
        if not repo.install:
            continue
        # `seed repo-install` resolves its target from VIRTUAL_ENV, exactly
        # as it would after `seed activate`. Nothing is activated during an
        # apply, so point it at the profile's default venv for the duration
        # of the call rather than letting uv guess.
        if target_venv is None:
            print(f"warning: {name!r} declares install = true but the profile "
                  "has no default venv to install into; skipping.")
            continue
        previous = os.environ.get("VIRTUAL_ENV")
        os.environ["VIRTUAL_ENV"] = str(paths.venv_dir(target_venv))
        try:
            rc = repo_cmd.install_repo(Namespace(name=name))
        finally:
            if previous is None:
                os.environ.pop("VIRTUAL_ENV", None)
            else:
                os.environ["VIRTUAL_ENV"] = previous
        if rc != 0:
            failed.append(f"dependencies for {name}")

    for key, value in prof.settings.items():
        if config.get(key) != value:
            config.set_value(key, value)
            print(f"set {key} = {value!r}")

    for venv in prof.venvs:
        if venv.default and config.get("default_venv") != venv.name:
            config.set_value("default_venv", venv.name)
            print(f"set default_venv = {venv.name!r}")

    print()
    if failed:
        # Partial success is reported as failure: a half-applied profile
        # means this machine is NOT what the admin specified, and a script
        # driving `seed apply` needs to know that from the exit code.
        print(colors.warn(f"{len(failed)} step(s) did not complete: "
                          + ", ".join(failed)))
        print("Fix the cause and re-run `seed apply` -- what already "
              "succeeded is left alone.")
        return 1
    print(colors.ok("Profile applied."))
    return 0
