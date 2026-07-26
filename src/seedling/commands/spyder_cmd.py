"""
`seed spyder` / `seed repo-spyder` -- the Spyder IDE, as a bundled editor.

Spyder is a Python application, so the install itself is just `seed
app-install spyder` underneath. What this module adds is the wiring that
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
docs telling people to run `seed app-install spyder`.
"""

from __future__ import annotations

import configparser
import os
import platform
import re

from .. import colors, config, paths
from . import app_cmd, editors
from .venv_cmd import _python_interpreter_path_venv

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
    "    seed tool-install spyder")


def is_installed() -> bool:
    return app_cmd.is_installed(APP_NAME)


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


def target_venv() -> tuple[str, object] | tuple[None, None]:
    """The venv Spyder should run code in: the configured default. Returns
    (name, interpreter path), or (None, None) if there isn't a usable one."""
    name = config.get("default_venv")
    if not name:
        return None, None
    interpreter = _python_interpreter_path_venv(paths.venv_dir(str(name)))
    if interpreter is None:
        return None, None
    return str(name), interpreter


def _ensure_kernels(interpreter) -> bool:
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
    result = uv_tool.run(
        ["pip", "install", "--python", str(interpreter), requirement],
        check=False)
    if result.returncode != 0:
        print(colors.warn(
            f"Could not install {requirement} into the venv. Spyder will "
            "open, but its console won't connect to that environment."))
        return False
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

    if not app_cmd.ensure_installed(args, APP_NAME, note=DOWNLOAD_NOTE):
        return False

    name, interpreter = target_venv()
    if interpreter is None:
        print(colors.warn(
            "No default venv is set, so Spyder will use its own interpreter "
            "and won't see your packages."))
        print("  Set one with:  seed venv-default <name>")
        return True

    print(f"Spyder will run code in the '{name}' venv.")
    _ensure_kernels(interpreter)
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


def repo_spyder(args) -> int:
    """`seed repo-spyder <name>` -- open a cloned repo as a Spyder project."""
    name = getattr(args, "name", None)
    if not name:
        print("Usage: seed repo-spyder <name>")
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
    repo_command="repo-spyder",
    repo_summary="Open a cloned repo in Spyder",
))
