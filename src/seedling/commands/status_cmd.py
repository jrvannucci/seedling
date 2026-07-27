"""
`seed health-check` -- verifies every moving part seedling depends on and
reports one line per check: a STATUS (OK / WARN / FAIL), an AREA (what the
check is about, e.g. uv, venv, updates), and the detail. Exit code 0 when
nothing FAILed (warnings are informational), 1 otherwise.

WARN vs FAIL: FAIL means a core seedling operation would not work right now
(missing uv, broken venv, unreadable config). WARN means something is off
but degradable (no git yet, no shell hook found in the usual profiles).

`collect()` runs the checks and returns plain data; the renderers turn that
into either the aligned text report or JSON (`--json`). The checks
themselves never print -- they append a record -- so a new check shows up in
both outputs automatically, the same split `seed summary` uses.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from .. import colors, config, git_tool, paths, uv_tool

# Bump when a field changes meaning or goes away, matching `summary --json`.
SCHEMA_VERSION = 1

_checks: list[dict] = []

# The STATUS and AREA columns are padded to these widths (longest label in
# each + a little slack) so the following column lines up. _STATUS_WIDTH is 6
# so the "STATUS" header itself fits flush in the column. Padding is applied
# to the plain text BEFORE coloring -- color escape codes are zero-width, so
# ljust on a colored string would misalign.
_STATUS_WIDTH = 6
_AREA_WIDTH = 9

# Visible width of everything before the CHECK column: 2 leading spaces +
# STATUS + a space + AREA + a space. Wrapped detail lines hang-indent to here
# so they stay under the CHECK column instead of falling back to column 0.
_CHECK_INDENT = 2 + _STATUS_WIDTH + 1 + _AREA_WIDTH + 1


def _wrap_check(msg: str) -> list[str]:
    """Split `msg` into lines that fit the CHECK column on the current
    terminal. Only wraps for a real terminal -- when output is piped or
    redirected there's no meaningful width, so the message stays on one line
    (which also keeps captured/test output stable). Command names and their
    `--flags` are kept intact (break_on_hyphens=False)."""
    if not sys.stdout.isatty():
        return [msg]
    width = shutil.get_terminal_size().columns
    avail = width - _CHECK_INDENT
    if avail < 20:  # too narrow to wrap usefully; let the terminal do its thing
        return [msg]
    return textwrap.wrap(msg, width=avail, break_on_hyphens=False) or [msg]


def _line(status: str, color, area: str, msg: str) -> None:
    """One report row: 'STATUS  AREA  detail', STATUS in `color` and AREA in
    cyan. `status` is the plain label (OK/WARN/FAIL), padded then colored so
    the columns stay aligned regardless of whether color is on. A detail that
    is too long for the terminal wraps with a hang indent under CHECK."""
    prefix = (f"  {color(status.ljust(_STATUS_WIDTH))} "
              f"{colors.cyan(area.ljust(_AREA_WIDTH))} ")
    lines = _wrap_check(msg)
    print(prefix + lines[0])
    for cont in lines[1:]:
        print(" " * _CHECK_INDENT + cont)


def _record(status: str, area: str, msg: str) -> None:
    _checks.append({"status": status, "area": area, "detail": msg})


def _ok(area: str, msg: str) -> None:
    _record("OK", area, msg)


def _warn(area: str, msg: str) -> None:
    _record("WARN", area, msg)


def _fail(area: str, msg: str) -> None:
    _record("FAIL", area, msg)


def _check_uv() -> None:
    try:
        uv = uv_tool.find_uv()
    except uv_tool.UvNotFound:
        _fail("uv", "uv not found in ~/seedling/system/bin or on PATH -- re-run the installer")
        return
    result = subprocess.run([str(uv), "--version"], capture_output=True, text=True, check=False)
    if result.returncode == 0:
        _ok("uv", f"uv runs ({result.stdout.strip()}) at {uv}")
    else:
        _fail("uv", f"uv exists at {uv} but won't run (exit {result.returncode})")


def _check_git() -> None:
    git = git_tool.find_git()
    if git:
        _ok("git", f"git available at {git}")
    else:
        _warn("git", "git not found (Windows: auto-downloaded on first `seed repo-clone`; "
              "macOS/Linux: install it with your package manager)")


def _check_config() -> None:
    if not paths.CONFIG_FILE.exists():
        _ok("config", "config not written yet (defaults in effect)")
        return
    try:
        # utf-8-sig so a BOM-prefixed settings.json (install.ps1 seeds it via
        # PowerShell's `Set-Content -Encoding UTF8`) reads as OK, matching how
        # config.load() reads it -- otherwise status falsely flags it corrupt.
        json.loads(paths.CONFIG_FILE.read_text(encoding="utf-8-sig"))
        _ok("config", f"config parses ({paths.CONFIG_FILE})")
    except (json.JSONDecodeError, OSError) as e:
        _fail("config", f"config file is unreadable/corrupt: {e} -- fix or delete {paths.CONFIG_FILE}")


def _check_base_pythons() -> None:
    alias_files = sorted(paths.BASE_DIR.glob("*.alias.json")) if paths.BASE_DIR.exists() else []
    if not alias_files:
        _warn("python", "no base Pythons installed yet (run `seed python <version>`)")
        return
    for alias in alias_files:
        tag = alias.name[: -len(".alias.json")]
        try:
            target = json.loads(alias.read_text())["target"]
        except (json.JSONDecodeError, KeyError, OSError):
            _fail("python", f"base '{tag}': alias file is corrupt -- re-run `seed python {tag}`")
            continue
        base_dir = paths.BASE_DIR / target
        if not base_dir.exists():
            _fail("python", f"base '{tag}': points at {target}, which is missing -- "
                  f"re-run `seed python {tag}`")
            continue
        exe = (base_dir / "python.exe") if os.name == "nt" else (base_dir / "bin" / "python3")
        if exe.exists():
            _ok("python", f"base Python '{tag}' -> {target}")
        else:
            _fail("python", f"base '{tag}': directory exists but no interpreter found inside {base_dir}")


def _check_venvs() -> None:
    venvs = (sorted(d for d in paths.VENVS_DIR.iterdir() if d.is_dir())
             if paths.VENVS_DIR.exists() else [])
    if not venvs:
        _warn("venv", "no venvs created yet (run `seed venv <name>`)")
        return
    for v in venvs:
        exe = (v / "Scripts" / "python.exe") if os.name == "nt" else (v / "bin" / "python")
        if not exe.exists():
            _fail("venv", f"venv '{v.name}': no interpreter at {exe} -- recreate it")
            continue
        # A venv silently breaks if the base Python it links to is deleted.
        cfg = v / "pyvenv.cfg"
        home_line = None
        try:
            for line in cfg.read_text().splitlines():
                if line.strip().lower().startswith("home"):
                    home_line = line.split("=", 1)[1].strip()
                    break
        except OSError:
            pass
        if home_line and not Path(home_line).exists():
            _fail("venv", f"venv '{v.name}': its base Python ({home_line}) is gone -- recreate the venv")
        else:
            _ok("venv", f"venv '{v.name}'")


def _check_update_source(source_str: str) -> None:
    """Verify update_source for real instead of assuming. A git URL gets a
    bounded `git ls-remote` reachability probe (prompt-proofed so it can
    never hang on credentials); a directory path gets existence + shape
    checks -- an unmounted share must say so, not pass as an "assumed git
    URL". Everything here WARNs rather than FAILs: `seed update-commands`
    deliberately falls back to reinstalling the current copy when its source
    is unavailable, so a bad source degrades updates without breaking
    seedling itself."""
    is_url = "://" in source_str or source_str.startswith("git@")
    if not is_url:
        source = Path(source_str).expanduser()
        if source.is_dir() and (source / "src" / "pyproject.toml").exists():
            _ok("updates", f"update_source directory {source} looks usable")
        elif source.is_dir():
            _warn("updates", f"update_source directory {source} has no src/pyproject.toml -- "
                  "`seed update-commands` will refuse it")
        else:
            _warn("updates", f"update_source directory {source_str} doesn't exist right now "
                  "(unmounted share? moved?) -- `seed update-commands` can only "
                  "reinstall the existing copy until it's reachable again")
        return

    git = git_tool.find_git()
    if not git:
        _warn("updates", f"update_source is {source_str}, but git isn't available to "
              "verify it -- `seed update-commands` needs git for URL sources")
        return
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")               # no credential prompt hangs
    env.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes")  # no ssh prompt hangs
    try:
        result = subprocess.run(
            [git, "ls-remote", "--heads", source_str],
            capture_output=True, text=True, env=env, timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        _warn("updates", f"update_source {source_str} didn't respond within 10s -- "
              "`seed update-commands` will fall back to reinstalling the "
              "current copy")
        return
    if result.returncode == 0:
        _ok("updates", f"update_source git URL is reachable ({source_str})")
    else:
        detail = (result.stderr or "").strip().splitlines()
        suffix = f" ({detail[-1].strip()})" if detail else ""
        _warn("updates", f"update_source {source_str} is not reachable{suffix} -- "
              "`seed update-commands` will fall back to reinstalling the "
              "current copy")


def _check_defaults() -> None:
    default_base = config.get_default_base()
    if default_base and not paths.base_alias_file(default_base).exists():
        _fail("defaults", f"config default_base '{default_base}' isn't installed -- "
              f"`seed python {default_base}` or `seed config set default_base <tag>`")
    elif default_base:
        _ok("defaults", f"default_base '{default_base}' is installed")

    default_venv = config.get("default_venv")
    if default_venv and not paths.venv_dir(default_venv).exists():
        _fail("defaults", f"config default_venv '{default_venv}' doesn't exist -- new shells "
              "will fail to auto-activate it")
    elif default_venv:
        _ok("defaults", f"default_venv '{default_venv}' exists")

    update_source = config.get("update_source")
    if update_source:
        _check_update_source(str(update_source))
    else:
        _warn("updates", "no update_source recorded -- `seed update-commands` can only "
              "reinstall the existing copy, not fetch newer versions; set one "
              "with `seed config set update_source <git-url-or-directory>`")

    ca_cert = config.get("ca_cert")
    if ca_cert:
        if Path(str(ca_cert)).expanduser().is_file():
            _ok("certs", f"ca_cert bundle exists ({ca_cert})")
        else:
            _fail("certs", f"config ca_cert file {ca_cert} doesn't exist -- HTTPS to "
                  "your internal hosts will fail certificate verification; "
                  "re-run the installer (which rebuilds the bundle from "
                  "vendor/certs) or `seed config unset ca_cert`")

    # Offline sources: a directory-path value that doesn't exist means the
    # next `seed python`/`seed install` fails with an obscure uv error.
    for key in ("python_mirror", "package_index"):
        value = config.get(key)
        if not value or "://" in str(value):
            continue  # unset, or a URL we can't cheaply verify
        if Path(str(value)).expanduser().is_dir():
            _ok("offline", f"{key} directory {value} exists")
        else:
            _fail("offline", f"config {key} directory {value} doesn't exist -- installs "
                  "that need it will fail; fix it or `seed config unset "
                  f"{key}`")


_HOOK_PATH_RE = re.compile(r'["\']([^"\']*seed\.(?:ps1|sh))["\']')


def _check_shell_hook() -> None:
    profiles = [
        Path.home() / ".zshrc",
        Path.home() / ".bashrc",
        Path.home() / ".bash_profile",
        Path.home() / ".profile",
        Path.home() / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
        Path.home() / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1",
    ]
    home_str = str(paths.HOME)
    found_working = False
    for profile in profiles:
        if not profile.exists():
            continue
        try:
            text = profile.read_text()
        except OSError:
            continue
        for line in text.splitlines():
            if home_str not in line:
                continue
            if "seed.ps1" not in line and "seed.sh" not in line:
                continue
            match = _HOOK_PATH_RE.search(line)
            target = Path(match.group(1)) if match else None
            if target is not None and target.exists():
                found_working = True
                _ok("shell", f"shell hook installed in {profile}")
            else:
                # A hook pointing at a deleted file (e.g. left behind by an
                # old seedling layout) makes every new shell print an error.
                _warn("shell", f"stale seedling hook in {profile}: `{line.strip()}` "
                      "points at a file that doesn't exist -- every new "
                      "shell will print an error until that line is removed "
                      "(re-running the installer cleans it up)")
    if not found_working:
        _warn("shell", "no working `seed` shell hook found in the usual shell profiles "
              "-- `seed activate` won't affect your shell; re-run the "
              "installer if so")


def _check_logs_writable() -> None:
    try:
        paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        probe = paths.LOGS_DIR / ".write-probe"
        probe.write_text("ok")
        probe.unlink()
        _ok("logs", f"log directory writable ({paths.LOGS_DIR})")
    except OSError as e:
        _warn("logs", f"log directory not writable ({e}) -- commands still work, just unlogged")


def collect() -> dict:
    """Run every check and return the results as plain data -- no printing,
    no color. `healthy` is the exit-code question: warnings are
    informational, only a FAIL makes an install unhealthy."""
    global _checks
    _checks = []

    _check_uv()
    _check_git()
    _check_config()
    _check_base_pythons()
    _check_venvs()
    _check_defaults()
    _check_shell_hook()
    _check_logs_writable()

    checks = list(_checks)
    failures = sum(1 for c in checks if c["status"] == "FAIL")
    warnings = sum(1 for c in checks if c["status"] == "WARN")
    return {
        "schema": SCHEMA_VERSION,
        "home": str(paths.HOME),
        "healthy": failures == 0,
        "failures": failures,
        "warnings": warnings,
        "checks": checks,
    }


_STATUS_COLORS = {"OK": colors.ok, "WARN": colors.warn, "FAIL": colors.danger}


def _render_text(data: dict) -> None:
    print(colors.bold("seedling health check") + f"  ({data['home']})")
    print()
    print("  " + colors.dim("STATUS".ljust(_STATUS_WIDTH)) + " " +
          colors.dim("AREA".ljust(_AREA_WIDTH)) + " " + colors.dim("CHECK"))
    for check in data["checks"]:
        _line(check["status"], _STATUS_COLORS[check["status"]],
              check["area"], check["detail"])

    print()
    failures, warnings = data["failures"], data["warnings"]
    if failures:
        print(colors.danger(f"{failures} problem(s) found") +
              (f", {warnings} warning(s)." if warnings else "."))
    elif warnings:
        print(colors.warn(f"Healthy, with {warnings} warning(s)."))
    else:
        print(colors.ok("Everything looks healthy."))


def run(args) -> int:
    data = collect()
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
    else:
        _render_text(data)
    # Same answer either way: 0 unless something FAILed.
    return 0 if data["healthy"] else 1
