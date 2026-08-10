"""
`seed spyder` / `seed spyder-repo` -- the Spyder IDE, as a bundled editor.

Spyder is a Python application, so the install itself is just `seed
tool-install spyder` underneath. What this module adds is the wiring that
makes Spyder actually usable against a seedling venv, which a generic
application install cannot know to do:

  1. Containment. Spyder writes its settings to ~/.config/spyder-6 (or
     %APPDATA%) by default. Pointed at SPYDER_CONFDIR instead, everything
     stays inside ~/seedling, so `seed purge` really does leave nothing.
  2. The interpreter. Unlike VS Code -- whose Python extension discovers
     environments on its own -- Spyder must be told which interpreter to
     use, via its own config file.
  3. spyder-kernels. Spyder's console only attaches to an interpreter with a
     COMPATIBLE spyder-kernels installed. Get it wrong and the console fails
     to connect with a message about versions, which is precisely the
     failure the audience for a preconfigured environment cannot diagnose.
     The version is read from Spyder's own environment rather than pinned
     here, so it can't drift when Spyder is upgraded.

Steps 2 and 3 are the reason this is a command rather than a line in the
docs telling people to run `seed tool-install spyder`.
"""

from __future__ import annotations

import configparser
import os
import platform
import re
from pathlib import Path

from .. import colors, paths, venv_target
from . import editors, tool_cmd

APP_NAME = "spyder"
DOWNLOAD_NOTE = "~200 MB download"

# PyQt5 publishes its Qt payload (pyqt5-qt5, pyqtwebengine-qt5) for x86_64
# only -- no macosx_*_arm64, no manylinux aarch64. Spyder itself is pure
# Python, so the failure surfaces as an unresolvable dependency rather than
# anything mentioning Qt, which is a miserable thing to debug.
_X86_ONLY_NOTE = (
    "Spyder installs from PyPI, and its Qt dependency publishes no arm64 "
    "wheels, so `seed spyder` can't work on this machine.\n"
    "  Use the conda-forge build instead, which does ship arm64:\n"
    "    seed forge-install spyder")


def is_installed() -> bool:
    return tool_cmd.is_installed(APP_NAME)


def _is_arm() -> bool:
    return platform.machine().lower() in ("arm64", "aarch64")


def _shim() -> str:
    """The launcher uv wrote for Spyder's gui_scripts entry point. On Windows
    that's a pythonw-backed exe, so it detaches from the console by itself."""
    exe = "spyder.exe" if os.name == "nt" else "spyder"
    return str(paths.APP_SHIMS_DIR / exe)


def _kernels_version() -> str | None:
    """The spyder-kernels version inside Spyder's own environment.

    Read rather than hardcoded: the venv needs a version compatible with
    whatever Spyder was installed with, and pinning a constant here would go
    stale the first time Spyder is upgraded."""
    env = paths.APPS_DIR / APP_NAME
    for info in env.glob("**/spyder_kernels-*.dist-info"):
        found = re.search(r"-(\d[^-]*)\.dist-info$", info.name)
        if found:
            return found.group(1)
    return None


def _kernels_requirement() -> str | None:
    """`spyder-kernels==3.1.*` for an installed 3.1.5 -- pinned to the minor
    series, which is the compatibility unit Spyder actually cares about."""
    version = _kernels_version()
    if not version:
        return None
    parts = version.split(".")
    if len(parts) < 2:
        return None
    return f"spyder-kernels=={parts[0]}.{parts[1]}.*"


def resolve_venv(args=None) -> tuple[object | None, str | None]:
    """The venv Spyder should run code in, and whether a failure is fatal.

    The precedence -- `--venv <name>`, then VIRTUAL_ENV, then `default_venv`
    -- is shared with `seed run` and `seed which` and lives in venv_target.
    VIRTUAL_ENV is honored even when it points outside ~/seedling, because
    `seed install` installs into whatever is active and it would be strange
    for Spyder to disagree about what "the current environment" is. Because
    the kernel is prepared before Spyder launches, switching venvs and
    reopening switches the console with it.

    What is Spyder's OWN is the policy when it doesn't resolve:

      - An explicit `--venv <name>` that can't be honored is fatal. Opening
        a DIFFERENT environment than the one asked for by name is worse
        than not opening at all.
      - Anything else degrades. Spyder is an editor, and refusing to launch
        because `default_venv` names a deleted venv is the wrong trade --
        it opens with its own interpreter and says so. That is why this
        asks venv_target for `lenient` resolution, where `seed run` and
        `seed which` take the strict default.

    Returns (target, None) or (None, fatal message). A (None, None) result
    means "no venv, but carry on".
    """
    target, failure = venv_target.resolve(getattr(args, "venv", None),
                                          lenient=True)
    if failure is not None and failure.source == venv_target.SOURCE_ARGUMENT:
        return None, failure.message
    return target, None


def _site_packages(interpreter) -> list[Path]:
    """The site-packages directories of the venv `interpreter` belongs to."""
    root = Path(interpreter).parent.parent
    if os.name == "nt":
        return [root / "Lib" / "site-packages"]
    return list(root.glob("lib/python*/site-packages"))


def _venv_package_version(interpreter, package: str) -> str | None:
    """Version of `package` inside that venv, read from its dist-info.

    Read off disk rather than by running `uv pip show`: this is called twice
    around an install just to notice a version change, and two subprocesses
    for a diagnostic message isn't a good trade."""
    candidates = (package.replace("-", "_"), package)
    for directory in _site_packages(interpreter):
        if not directory.is_dir():
            continue
        for name in candidates:
            for info in directory.glob(f"{name}-*.dist-info"):
                found = re.search(r"-(\d[^-]*)\.dist-info$", info.name)
                if found:
                    return found.group(1)
    return None


def _version_tuple(version: str) -> tuple[int, ...]:
    """'6.31.0' -> (6, 31, 0). Leading digits only, so '7.0.0rc1' still
    compares as 7.0.0 -- enough to tell a downgrade from an upgrade."""
    parts = []
    for chunk in version.split("."):
        digits = ""
        for char in chunk:
            if not char.isdigit():
                break
            digits += char
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _warn_if_downgraded(venv_name: str, before: str | None,
                        after: str | None) -> None:
    """Say so when preparing the venv rolled ipykernel BACK.

    spyder-kernels caps ipykernel below 7, while seedling's default venv
    packages install a newer one -- so this fires on a stock venv. It is
    required for Spyder's console to work at all, but it silently changes a
    package the user may be relying on elsewhere (Jupyter, VS Code
    notebooks), and everything else in seedling that costs something says so
    first. Detected by comparing before/after rather than predicted from
    metadata: the constraint lives upstream and is already being relaxed
    (spyder-kernels 3.2 raises the cap), so hardcoding the expectation here
    would start lying the moment that ships.
    """
    if not before or not after:
        return
    if _version_tuple(after) >= _version_tuple(before):
        return
    print(colors.warn(
        f"Note: ipykernel was downgraded {before} -> {after} in "
        f"'{venv_name}'."))
    print("  spyder-kernels requires ipykernel<7, and Spyder's console "
          "won't connect without it.")
    print("  If you also use this venv for Jupyter or VS Code notebooks, "
          "they get the older ipykernel too.")


def _ensure_kernels(interpreter, venv_name: str = "") -> bool:
    """Install a compatible spyder-kernels into the target venv. Returns
    False only if the install was attempted and failed."""
    from .. import uv_tool

    requirement = _kernels_requirement()
    if not requirement:
        # Spyder is installed but its kernels package couldn't be located --
        # don't guess a version; say so and let Spyder report the mismatch.
        print(colors.warn(
            "Couldn't determine Spyder's spyder-kernels version, so the "
            "venv wasn't prepared. Spyder's console may not connect."))
        return True

    print(f"Preparing the venv for Spyder ({requirement}) ...")
    before = _venv_package_version(interpreter, "ipykernel")
    result = uv_tool.run(
        ["pip", "install", "--python", str(interpreter), requirement],
        check=False)
    if result.returncode != 0:
        print(colors.warn(
            f"Could not install {requirement} into the venv. Spyder will "
            "open, but its console won't connect to that environment."))
        return False
    _warn_if_downgraded(venv_name, before,
                        _venv_package_version(interpreter, "ipykernel"))
    return True


def _write_config(interpreter) -> None:
    """Point Spyder at `interpreter` in its own spyder.ini.

    Merges rather than overwrites: this file is Spyder's live configuration
    once it has run, and clobbering it would throw away the user's settings
    every time they ran `seed spyder`.
    """
    paths.SPYDER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ini_path = paths.SPYDER_CONFIG_DIR / "spyder.ini"

    parser = configparser.ConfigParser()
    if ini_path.exists():
        try:
            parser.read(ini_path, encoding="utf-8")
        except (OSError, configparser.Error):
            parser = configparser.ConfigParser()

    if not parser.has_section("main_interpreter"):
        parser.add_section("main_interpreter")
    # `default = False` + `custom = True` is what makes Spyder use
    # custom_interpreter instead of the Python it is itself running on.
    parser.set("main_interpreter", "default", "False")
    parser.set("main_interpreter", "custom", "True")
    parser.set("main_interpreter", "custom_interpreter", f"'{interpreter}'")
    parser.set("main_interpreter", "custom_interpreters_list",
               f"['{interpreter}']")

    try:
        with open(ini_path, "w", encoding="utf-8") as handle:
            parser.write(handle)
    except OSError as e:
        print(colors.warn(f"Could not write {ini_path} ({e}); Spyder will "
                          "open with its own interpreter setting."))


def _prepare(args) -> bool:
    """Install Spyder if needed and wire it to the default venv. Returns
    False if the user declined or the platform can't run it."""
    if _is_arm() and not is_installed():
        print(colors.warn(_X86_ONLY_NOTE))
        return False

    target, fatal = resolve_venv(args)
    if fatal is not None:
        print(colors.warn(
            f"No usable venv named '{getattr(args, 'venv', '')}'. "
            "Nothing was changed."))
        print("  See what exists with:  seed venv-list")
        return False
    name = target.name if target else None
    interpreter = target.python if target else None

    if not tool_cmd.ensure_installed(args, APP_NAME, note=DOWNLOAD_NOTE):
        return False

    if interpreter is None:
        print(colors.warn(
            "No venv is active and no default is set, so Spyder will use its "
            "own interpreter and won't see your packages."))
        print("  Activate one first (seed activate <name>), or set a default "
              "with:  seed venv-default <name>")
        return True

    print(f"Spyder will run code in the '{name}' venv.")
    _ensure_kernels(interpreter, str(name))
    _write_config(interpreter)
    return True


def _launch(path: str, *, as_project: bool) -> None:
    """Open Spyder, detached, with its config kept inside seedling."""
    flag = "--project" if as_project else "--workdir"
    editors.open_detached(
        [_shim(), "--conf-dir", str(paths.SPYDER_CONFIG_DIR), flag], path)


def run(args) -> int:
    if not _prepare(args):
        return 0
    open_path = getattr(args, "path", None) or os.getcwd()
    if getattr(args, "no_open", False):
        print("Spyder is installed and ready. Open it with:  seed spyder")
        return 0
    print(f"Opening Spyder -> {open_path}")
    _launch(open_path, as_project=False)
    return 0


def spyder_repo(args) -> int:
    """`seed spyder-repo <name>` -- open a cloned repo as a Spyder project."""
    name = getattr(args, "name", None)
    if not name:
        print("Usage: seed spyder-repo <name>")
        return 1

    target = paths.repo_dir(name)
    if not target.exists():
        print(f"No repo named '{name}' found in {paths.REPO_DIR}")
        return 1

    if not _prepare(args):
        return 0
    print(f"Opening Spyder -> {target}")
    _launch(str(target), as_project=True)
    return 0


editors.register(editors.Editor(
    key=APP_NAME,
    label="Spyder",
    command="spyder",
    args_hint="[path]",
    summary="Install (once) and open Spyder",
    download_note=DOWNLOAD_NOTE,
    is_installed=is_installed,
    run=lambda args: run(args),
    repo_command="spyder-repo",
    repo_summary="Open a cloned repo in Spyder",
))
