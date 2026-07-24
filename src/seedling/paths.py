"""
Single source of truth for seedling's folder layout.

Everything seedling touches lives under one directory so nothing gets
scattered across the filesystem:

~/seedling/
    system/               <- everything seedling needs to run itself, kept
        bin/                 out of the way of the stuff you actually use
        tool/             <- the uv-managed venv seed-cli itself runs in
        src/              <- seedling's own source (see `seed update-commands`)
        config/
            settings.json <- seedling's own config (default python version, etc.)
        logs/             <- one log file per day; every `seed` command appends
                             what ran and everything it printed
        cache/
            uv/           <- uv's package/interpreter download cache, kept
                             inside seedling instead of ~/.cache / %LOCALAPPDATA%
        shell/
            seed.sh       <- sourced by bash/zsh to define the `seed` function
            seed.ps1      <- dot-sourced by PowerShell to define the `seed` function
    python/
        base/<tag>/       <- base python installs, e.g. base/312
        venvs/<name>/     <- virtual environments built off a base python
    extensions/
        vscode/
            app/          <- the portable VS Code install itself
            data/         <- --user-data-dir (settings, keybindings, etc.)
            extensions/   <- --extensions-dir
    repo/
        <name>/           <- repos cloned with `seed repo-clone`
"""

from __future__ import annotations

import os
from pathlib import Path


def _current_username() -> str:
    """Login name, for the {user} placeholder. getpass.getuser() consults
    USER/LOGNAME/LNAME/USERNAME then the password database -- covers every
    platform seedling runs on."""
    import getpass
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "user"


def _expand_user_token(value: str) -> str:
    """`{user}` -> the current username. Lets a shared install root give
    each user their own conflict-free folder, e.g. C:\\seedling\\{user}.
    The installers normally expand this before it reaches runtime; this is
    the defensive net for a SEEDLING_HOME env var set directly."""
    if "{user}" in value:
        return value.replace("{user}", _current_username())
    return value


def seedling_home() -> Path:
    """Root of everything seedling manages. Overridable for testing via env var."""
    override = os.environ.get("SEEDLING_HOME")
    if override:
        return Path(_expand_user_token(override)).expanduser().resolve()
    return Path.home() / "seedling"


HOME = seedling_home()

# Everything seedling needs to operate itself lives under system/, so the
# top level of ~/seedling stays limited to system/, python/, extensions/,
# and repo/ -- the folders someone actually cares about browsing.
SYSTEM_DIR = HOME / "system"
BIN_DIR = SYSTEM_DIR / "bin"
TOOL_DIR = SYSTEM_DIR / "tool"
SRC_DIR = SYSTEM_DIR / "src"
CONFIG_DIR = SYSTEM_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "settings.json"
SHELL_DIR = SYSTEM_DIR / "shell"
LOGS_DIR = SYSTEM_DIR / "logs"
UV_CACHE_DIR = SYSTEM_DIR / "cache" / "uv"

# conda-forge command-line tools, managed with micromamba (`seed tool-install`).
# The per-tool environments live under system/ because they are an
# implementation detail; only the shims are user-facing. MAMBA_DIR is
# micromamba's root prefix (its package cache and envs), and TOOL_SHIMS_DIR
# holds the small launchers the shell hook puts on PATH so an installed tool
# runs as a bare command.
MAMBA_DIR = SYSTEM_DIR / "conda"
MAMBA_ENVS_DIR = MAMBA_DIR / "envs"
MAMBA_PKGS_DIR = MAMBA_DIR / "pkgs"
TOOL_SHIMS_DIR = MAMBA_DIR / "shims"
TOOL_MANIFEST_DIR = MAMBA_DIR / "tools"

PYTHON_DIR = HOME / "python"
BASE_DIR = PYTHON_DIR / "base"
VENVS_DIR = PYTHON_DIR / "venvs"

EXTENSIONS_DIR = HOME / "extensions"
VSCODE_DIR = EXTENSIONS_DIR / "vscode"
VSCODE_APP_DIR = VSCODE_DIR / "app"
VSCODE_DATA_DIR = VSCODE_DIR / "data"
VSCODE_EXTENSIONS_DIR = VSCODE_DIR / "extensions"

REPO_DIR = HOME / "repo"

ALL_DIRS = [
    HOME,
    SYSTEM_DIR,
    BIN_DIR,
    CONFIG_DIR,
    SHELL_DIR,
    LOGS_DIR,
    UV_CACHE_DIR,
    PYTHON_DIR,
    BASE_DIR,
    VENVS_DIR,
    EXTENSIONS_DIR,
    VSCODE_DIR,
    REPO_DIR,
    # TOOL_SHIMS_DIR is created unconditionally so the shell hook can safely
    # prepend it to PATH even before any conda-forge tool is installed.
    TOOL_SHIMS_DIR,
]


def ensure_layout() -> None:
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def uv_binary() -> Path:
    exe = "uv.exe" if os.name == "nt" else "uv"
    return BIN_DIR / exe


def micromamba_binary() -> Path:
    exe = "micromamba.exe" if os.name == "nt" else "micromamba"
    return BIN_DIR / exe


def tool_env_dir(name: str) -> Path:
    """The micromamba environment backing a single conda-forge tool."""
    return MAMBA_ENVS_DIR / name


def tool_manifest_file(name: str) -> Path:
    """Records which shim commands a tool created, so removal is exact."""
    return TOOL_MANIFEST_DIR / f"{name}.json"


def base_python_dir(tag: str) -> Path:
    """e.g. tag='312' -> ~/seedling/python/base/312"""
    return BASE_DIR / tag


def base_alias_file(tag: str) -> Path:
    """uv installs python into a versioned dir name (e.g. cpython-3.12.4-...).
    We keep a tiny alias file so `312` always resolves to whatever that real
    dir is, without relying on symlink permissions (which Windows restricts)."""
    return BASE_DIR / f"{tag}.alias.json"


def venv_dir(name: str) -> Path:
    return VENVS_DIR / name


def repo_dir(name: str) -> Path:
    return REPO_DIR / name
