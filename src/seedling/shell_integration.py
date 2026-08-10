"""
Rendering the `seed` shell functions from their templates.

The installers render `shell/seed.ps1.template` / `seed.sh.template` into
`system/shell/seed.{ps1,sh}` once, replacing a home-directory placeholder,
and hook that rendered file into the user's `$PROFILE` / rc file. The hook
dot-sources the rendered file by a stable path, so refreshing the shell
integration after an update is just a matter of re-rendering that file in
place -- the next shell picks up the new content automatically.

`seed update-commands` calls `refresh()` for exactly that: without it, edits
to the templates (new subcommand routing, an `activate` fix, ...) only ever
reached users on a full reinstall, never on an update.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import paths

_PLACEHOLDER = "__SEEDLING_HOME_PLACEHOLDER__"

# Rendered filename in system/shell/ -> the template it comes from.
_SHELL_FILES: dict[str, str] = {
    "seed.ps1": "seed.ps1.template",
    "seed.sh": "seed.sh.template",
}

# The home-assignment line each installer renders the placeholder into.
# Whatever string the installer baked in is what the user's profile hook and
# the rest of the rendered file agree on (install.sh under git-bash on
# Windows, for instance, bakes a POSIX-style path that str(paths.HOME) would
# NOT reproduce) -- so a refresh re-uses that exact string.
_HOME_LINE_RE = {
    "seed.ps1": re.compile(r'^\$script:SeedlingHome\s*=\s*"(.+)"\s*$', re.MULTILINE),
    "seed.sh": re.compile(r'^__SEEDLING_HOME="(.+)"\s*$', re.MULTILINE),
}


def _templates_dir() -> Path:
    """Where the templates live inside the installed source copy. The
    installers copy the whole repo into system/src, so the tree there mirrors
    the repo: system/src/src/seedling/shell/. `seed update-commands` swaps a
    fresh copy in before calling refresh(), so this is the UPDATED template."""
    return paths.SRC_DIR / "src" / "seedling" / "shell"


def _os_default_file() -> str:
    """The rendered file the current platform's installer places."""
    return "seed.ps1" if os.name == "nt" else "seed.sh"


def _existing_home(rendered: Path, out_name: str) -> str | None:
    """The home string the installer originally rendered into this file."""
    try:
        match = _HOME_LINE_RE[out_name].search(rendered.read_text(encoding="utf-8"))
    except OSError:
        return None
    return match.group(1) if match else None


def render(template_path: Path, home: str) -> str:
    return template_path.read_text(encoding="utf-8").replace(_PLACEHOLDER, home)


def _broadcast_environment_change() -> None:
    """Tell already-open processes (Explorer, other terminals) PATH changed --
    the same broadcast [Environment]::SetEnvironmentVariable sends when
    install.ps1 adds this entry. Best-effort: a missed broadcast still
    leaves the registry correctly updated, just picked up on the next new
    process/session instead of immediately."""
    import ctypes
    try:
        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
            SMTO_ABORTIFHUNG, 5000, None)
    except OSError:
        pass


def ensure_bin_on_windows_path() -> bool:
    """Windows counterpart to refresh(): install.ps1's persistent-PATH step
    (system\\bin on the registry user PATH, so `seed-cli` is reachable
    without a profile -- see installers/install.ps1) only ever ran once, at
    install time. An install from before that step existed, or one where
    the entry was removed by hand, would otherwise never pick it up short
    of a full reinstall. `seed update-commands` calls this every time for
    exactly that reason -- the same "template changes must reach an update,
    not just a reinstall" rule this module exists for, applied to a
    registry entry instead of a rendered file.

    POSIX needs no counterpart: the same PATH addition lives INSIDE
    seed.sh itself (see seed.sh.template), so refresh() above already
    re-applies it on every update along with the rest of the template.

    SEEDLING_SKIP_PATH_REGISTER is the same test-only escape hatch
    install.ps1 honors (see tests/conftest.py) -- there is no fake HKCU to
    redirect this into, so tests opt out entirely.

    Returns True if the entry was added (it was missing); False if it was
    already present, this isn't Windows, or the registry couldn't be read
    or written (never fatal -- a stale PATH entry is not worth failing
    `update-commands` over)."""
    if os.name != "nt" or os.environ.get("SEEDLING_SKIP_PATH_REGISTER"):
        return False
    import winreg

    bin_dir = str(paths.BIN_DIR)
    target = bin_dir.rstrip("\\").lower()
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                              winreg.KEY_READ | winreg.KEY_WRITE)
    except OSError:
        return False
    try:
        try:
            current, value_type = winreg.QueryValueEx(key, "PATH")
        except FileNotFoundError:
            current, value_type = "", winreg.REG_SZ
        entries = current.split(";") if current else []
        if any(e.rstrip("\\").lower() == target for e in entries):
            return False
        new_value = f"{current};{bin_dir}" if current else bin_dir
        winreg.SetValueEx(key, "PATH", 0, value_type, new_value)
    except OSError:
        return False
    finally:
        winreg.CloseKey(key)

    _broadcast_environment_change()
    return True


def refresh() -> list[Path]:
    """Re-render the shell integration script(s) from the templates in the
    installed source copy, overwriting the ones in system/shell/.

    Refreshes whichever files the installer already placed -- so we never
    scatter an unused seed.sh onto a Windows install (or vice versa) -- plus
    the current platform's file, so it's restored even if it went missing.
    Missing templates are skipped rather than raising: a stubbed/partial
    source tree (e.g. under test) simply refreshes nothing.

    Returns the paths actually rewritten."""
    templates_dir = _templates_dir()
    paths.SHELL_DIR.mkdir(parents=True, exist_ok=True)

    targets = {name for name in _SHELL_FILES if (paths.SHELL_DIR / name).exists()}
    targets.add(_os_default_file())

    written: list[Path] = []
    for out_name in sorted(targets):
        template_path = templates_dir / _SHELL_FILES[out_name]
        if not template_path.exists():
            continue
        out_path = paths.SHELL_DIR / out_name
        home = _existing_home(out_path, out_name) or (
            str(paths.HOME) if out_name == "seed.ps1" else paths.HOME.as_posix())
        out_path.write_text(render(template_path, home), encoding="utf-8")
        written.append(out_path)
    return written
