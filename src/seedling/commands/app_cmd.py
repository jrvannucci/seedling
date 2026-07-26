"""
`seed app-install / app-list / app-remove` -- Python applications from PyPI,
each installed into its own isolated environment.

This is the uv/PyPI counterpart to the conda-forge `tool-*` family. The split
is by where a thing comes from, because that is what actually differs:

  seed install        packages INTO the venv you're working in (uv pip)
  seed app-install    an application in its OWN venv, on PATH (uv tool)
  seed tool-install   a non-Python program from conda-forge (micromamba)

`app-install` is for things you run rather than import -- Spyder, JupyterLab,
httpie -- where putting the app's dependency tree in your project venv would
be actively harmful. uv builds the isolated environment and writes the
launchers; seedling only points it at the right directories and keeps the
offline settings applied.

Applications land in extensions/apps/<name>/ and their launchers in
system/shims/, which the shell hook puts on PATH.
"""

from __future__ import annotations

import re
import shutil

from .. import colors, config, confirm, paths, uv_tool

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _spec_name(spec: str) -> str:
    """'spyder==6.1.5' -> 'spyder'. The app (and uv tool) name."""
    for sep in ("==", ">=", "<=", "~=", "!=", "=", "<", ">", "[", " "):
        spec = spec.split(sep)[0]
    return spec.strip()


def installed_apps() -> list[str]:
    """Names of the applications installed under extensions/apps.

    Read from the directory rather than by shelling out to `uv tool list`:
    this runs on the help path, where spawning a subprocess for a cosmetic
    marker would be a poor trade, and uv records each tool as a directory
    holding a venv."""
    if not paths.APPS_DIR.is_dir():
        return []
    return sorted(d.name for d in paths.APPS_DIR.iterdir()
                  if d.is_dir() and not d.name.startswith("."))


def is_installed(name: str) -> bool:
    return (paths.APPS_DIR / name).is_dir()


def _index_label() -> str:
    """Where packages resolve from, for the install message -- so an offline
    or internal-index deployment says so instead of claiming PyPI."""
    index = config.get("package_index")
    return str(index) if index else "PyPI"


def app_version(name: str) -> str | None:
    """The installed version of `name`, read from its own venv metadata."""
    env = paths.APPS_DIR / name
    for pattern in (f"**/{name}-*.dist-info", f"**/{name.replace('-', '_')}-*.dist-info"):
        for info in env.glob(pattern):
            match = re.search(r"-(\d[^-]*)\.dist-info$", info.name)
            if match:
                return match.group(1)
    return None


def ensure_installed(args, spec: str, *, note: str = "") -> bool:
    """Install `spec` if it isn't already, asking first when it would mean a
    download. Returns True if the app is present afterwards.

    Shared with the editor front ends (`seed spyder`), which need exactly
    this and shouldn't reimplement the prompt."""
    name = _spec_name(spec)
    if is_installed(name):
        return True
    if note:
        print(f"{name} isn't installed yet ({note}).")
    if not confirm.ask(args, f"Install {name} now?"):
        print(f"Skipped. To install it later:  seed app-install {name} -y")
        return False
    return _install(spec) == 0


def _install(spec: str, *, with_packages: list[str] | None = None) -> int:
    """Run `uv tool install`, returning uv's exit code."""
    argv = ["tool", "install", spec]
    for extra in with_packages or []:
        argv += ["--with", extra]
    result = uv_tool.run(argv, env=uv_tool.app_install_env(), check=False)
    return result.returncode


def install(args) -> int:
    spec = getattr(args, "spec", None)
    if not spec:
        print("Usage: seed app-install <name>[==version]   "
              "(e.g. seed app-install spyder)")
        return 1

    name = _spec_name(spec)
    if not _NAME_RE.match(name):
        print(f"error: '{name}' is not a valid application name.")
        return 1

    paths.ensure_layout()
    if is_installed(name) and not getattr(args, "reinstall", False):
        print(f"'{name}' is already installed.")
        print(f"Reinstall it with:  seed app-install {name} --reinstall")
        return 0

    argv = ["tool", "install", spec]
    if getattr(args, "reinstall", False):
        argv += ["--force", "--reinstall"]
    print(f"Installing '{spec}' from {_index_label()} ...")
    result = uv_tool.run(argv, env=uv_tool.app_install_env(), check=False)
    if result.returncode != 0:
        print(colors.warn(f"Could not install '{spec}'."))
        return 1

    version = app_version(name)
    suffix = f" {version}" if version else ""
    print(colors.ok(f"Installed '{name}'{suffix}."))
    print(f"Its commands are in {paths.APP_SHIMS_DIR}; open a new terminal "
          "to run them by name.")
    return 0


def list_apps(args) -> int:
    names = installed_apps()
    if not names:
        print("No PyPI applications installed.")
        print("Install one with:  seed app-install <name>   "
              "(e.g. spyder, jupyterlab)")
        return 0

    print(f"Applications in {paths.APPS_DIR}:")
    for name in names:
        version = app_version(name)
        shown = colors.dim(f"  [{version}]") if version else ""
        print(f"  {colors.bold(name)}{shown}")
    return 0


def remove(args) -> int:
    name = getattr(args, "name", None)
    if not name:
        print("Usage: seed app-remove <name>")
        return 1
    name = _spec_name(name)

    if not is_installed(name):
        print(f"No application named '{name}' is installed.")
        return 1

    if confirm.preview_requested(args):
        confirm.print_preview(
            f"remove application '{name}'",
            [f"environment {paths.APPS_DIR / name}",
             f"its launchers in {paths.APP_SHIMS_DIR}"],
        )
        return 0

    if not confirm.confirm(args, f"Remove the application '{name}'?"):
        print("Aborted.")
        return 1

    # `uv tool uninstall` removes the environment AND the launchers it wrote,
    # which is why removal doesn't need a manifest of its own the way the
    # conda tools do.
    result = uv_tool.run(["tool", "uninstall", name],
                         env=uv_tool.app_install_env(), check=False)
    if result.returncode != 0:
        # Fall back to deleting the tree: a half-installed app that uv no
        # longer recognizes should still be removable.
        shutil.rmtree(paths.APPS_DIR / name, ignore_errors=True)
    print(colors.ok(f"Removed application '{name}'."))
    return 0
