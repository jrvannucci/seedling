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

import re
import tomllib
from argparse import Namespace
from dataclasses import dataclass, field
from pathlib import Path

from .. import colors, config, confirm, paths, profile as profile_mod, uv_tool
from . import editors, forge_cmd, python_cmd, repo_cmd, venv_cmd


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
    return paths.venv_python(name)


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
            found.add(_canonical(part[0]))
    return found


def _canonical(name: str) -> str:
    """PEP 503 name normalization, so `ruff_lsp`, `Ruff-LSP` and `ruff.lsp`
    all compare equal -- what's declared in a profile and what `uv pip list`
    reports need not agree on punctuation."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def _requirement_name(spec: str) -> str:
    """'ruff>=0.5' -> 'ruff'. Comparison only -- the full spec is what gets
    installed."""
    for sep in ("[", "=", ">", "<", "!", "~", " "):
        spec = spec.split(sep)[0]
    return _canonical(spec)


def _repo_dist_name(repo_dir: Path) -> str | None:
    """The distribution an editable install of this repo would create, so
    apply can tell whether a given venv already has it.

    None when there's nothing to compare against: no pyproject.toml (a
    requirements.txt-only repo installs no distribution of its own), or a
    name computed at build time rather than written down. Callers fall back
    to "install it when the venv is new", which is the pre-existing
    behavior."""
    pyproject = repo_dir / "pyproject.toml"
    if not pyproject.exists():
        return None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    name = data.get("project", {}).get("name")
    if isinstance(name, str) and name.strip():
        return _canonical(name)
    return None


@dataclass
class _RepoAction:
    """What apply will do about one [[repo]]: clone it (or not), and which of
    its venvs it still has to be installed into.

    Computed ONCE, before any venv is created, and used by both the plan and
    the run -- so a venv the profile is about to build looks equally "doesn't
    have this repo yet" to `--preview` and to the real thing."""
    repo: profile_mod.Repo
    name: str
    clone: bool
    install: list[profile_mod.RepoTarget] = field(default_factory=list)
    satisfied: list[profile_mod.RepoTarget] = field(default_factory=list)


def _repo_actions(prof: profile_mod.Profile, *, force: bool) -> list[_RepoAction]:
    """Resolve every [[repo]] against what's on disk right now.

    A repo is installed into a target venv when that venv doesn't already
    have it -- which covers the two cases that matter: a venv being created
    for the first time, and a venv being REBUILT after `seed remove-venv`.
    The clone survives a venv rebuild, so keying the install off the clone
    (as this used to) left the new venv without the repo it was supposed to
    have."""
    probed: dict[str, set[str]] = {}

    def installed_in(venv_name: str) -> set[str]:
        if venv_name not in probed:
            probed[venv_name] = _installed_packages(venv_name)
        return probed[venv_name]

    actions: list[_RepoAction] = []
    for repo in prof.repos:
        name = repo_cmd._derive_name(repo.url)
        cloned = paths.repo_dir(name).exists()
        # Only meaningful once the clone is on disk; a repo about to be
        # cloned is installed into all of its targets regardless.
        dist = _repo_dist_name(paths.repo_dir(name)) if cloned else None

        action = _RepoAction(repo=repo, name=name, clone=not cloned)
        for target in repo.targets:
            venv_name = target.venv
            if not cloned or force or not paths.venv_dir(venv_name).exists():
                # Nothing worth probing: the repo is new, the venv is about
                # to be (re)built, or --force says install regardless.
                action.install.append(target)
            elif dist is not None and dist not in installed_in(venv_name):
                action.install.append(target)
            else:
                # Extras don't show up here: the probe answers "is this repo's
                # distribution present", and adding an extra to a profile
                # doesn't change that name. Widening extras on a venv that
                # already has the repo is an `--force` job, like packages.
                action.satisfied.append(target)
        actions.append(action)
    return actions


def _venv_list(names: list[str]) -> str:
    label = "venv" if len(names) == 1 else "venvs"
    return f"{label} " + ", ".join(repr(n) for n in names)


def _target_list(targets: list[profile_mod.RepoTarget]) -> str:
    """Targets as the plan shows them, spelled like the profile that asked
    for them: `venvs 'dev[gui,test]', 'analysis'`. Extras belong in the
    preview -- they change what gets installed."""
    return _venv_list([t.venv + t.spec_suffix for t in targets])


def _plan(prof: profile_mod.Profile, *, force: bool,
          repo_actions: list[_RepoAction] | None = None) -> list[tuple[str, str]]:
    """[(action, description)] for everything that would change. Built before
    anything runs so --preview and the real run can never disagree.

    `repo_actions` is passed in by run() so the repo decisions -- the only
    ones that cost a subprocess to work out -- are made once and shared."""
    steps: list[tuple[str, str]] = []
    if repo_actions is None:
        repo_actions = _repo_actions(prof, force=force)

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

    for action in repo_actions:
        if action.clone:
            detail = f"clone {action.repo.url}"
            if action.install:
                detail += f" and install it into {_target_list(action.install)}"
            steps.append(("repo", detail))
        else:
            steps.append(("skip", f"repo {action.name!r} already cloned"))
            if action.install:
                steps.append(("repo-install",
                              f"install repo {action.name!r} into "
                              f"{_target_list(action.install)}"))
        for target in action.satisfied:
            steps.append(("skip", f"repo {action.name!r} already installed "
                                  f"in venv {target.venv!r}"))

    for tool in prof.tools:
        name = forge_cmd._spec_name(tool)
        if paths.forge_manifest_file(name).exists():
            steps.append(("skip", f"conda-forge tool {name!r} already installed"))
        else:
            steps.append(("tool", f"install conda-forge tool {tool}"))

    # The editor comes last of the installs: it's the biggest download by far
    # (hundreds of MB), so a profile that also fails somewhere cheap fails
    # before spending that rather than after.
    for name in prof.editors:
        entry = editors.REGISTRY.get(name)
        if entry is None:
            # Registry changed under a profile validated against an older
            # build. Report rather than crash -- everything else still applies.
            steps.append(("skip", f"unknown editor {name!r}; skipped"))
        elif entry.is_installed():
            steps.append(("skip", f"{entry.label} already installed"))
        else:
            steps.append(("editor",
                          f"install {entry.label} ({entry.download_note})"))

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

    if getattr(args, "print_editor", False):
        # Machine-readable, for the installers: the editor this profile
        # declares, or nothing. Deliberately silent otherwise -- the caller
        # is a shell capturing stdout, and an empty answer means "the
        # profile doesn't say", which is what SEEDLING_AUTO_VSCODE is for.
        # Space-separated on one line: the callers are install.sh and
        # install.ps1, and both find that easier to test for membership than
        # multiple lines. Empty means "the profile doesn't say".
        if prof.editors:
            print(" ".join(prof.editors))
        return 0

    print(f"Profile: {path}")
    force = getattr(args, "force", False)
    # Resolved before anything is created: a venv this run is about to build
    # must still read as "doesn't have the repo yet" when the repos are
    # reached, several steps later.
    repo_actions = _repo_actions(prof, force=force)
    steps = _plan(prof, force=force, repo_actions=repo_actions)
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

    for action in repo_actions:
        if action.clone and repo_cmd.clone(
                Namespace(url=action.repo.url)) != 0:
            failed.append(f"repo {action.name}")
            continue
        # Named explicitly rather than through VIRTUAL_ENV: a repo can target
        # several venvs, and each install has to land in the one it was
        # declared for regardless of what this shell has active.
        for target in action.install:
            venv_name = target.venv
            if not paths.venv_dir(venv_name).exists():
                # Its creation failed earlier in this run and is already in
                # `failed`; a second entry for the knock-on effect would only
                # obscure the cause.
                print(f"skipping {action.name!r} -> venv {venv_name!r}: "
                      "that venv isn't there.")
                continue
            # The repo's extras go through as the same `name[extras]` spec a
            # user would type, so a profile can only ask for what `seed
            # repo-install` already does.
            spec = action.name + target.spec_suffix
            if repo_cmd.install_repo(
                    Namespace(name=spec, venv=venv_name)) != 0:
                failed.append(f"{action.name} in venv {venv_name}")

    for tool in prof.tools:
        name = forge_cmd._spec_name(tool)
        if paths.forge_manifest_file(name).exists():
            continue
        # conda_channel is already in place (seedling.conf at install time), so
        # an offline bundle installs these from its own conda-channel.
        if forge_cmd.install(Namespace(spec=tool)) != 0:
            failed.append(f"tool {name}")

    for name in prof.editors:
        entry = editors.REGISTRY.get(name)
        if entry is not None and not entry.is_installed():
            # -y: apply is provisioning, and the profile declaring an editor
            # IS the consent the first-run prompt would otherwise ask for.
            # --no-open so a fleet rollout never pops a window on someone's
            # screen mid-install.
            rc = entry.run(Namespace(
                path=None, no_open=True, yes=True, non_interactive=True,
                reinstall=False, venv=None))
            if rc != 0:
                failed.append(f"editor {entry.label}")

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
