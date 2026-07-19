"""
`seed summary` -- one screen showing everything seedling has installed:
tooling, base Pythons, venvs, repos, VS Code, and the current settings.
Read-only. Pass --sizes to also compute per-section disk usage (walks the
whole tree, so it can take a few seconds on big installs). Pass --json to
get the same facts as machine-readable data instead of a rendered screen.

`collect()` gathers the facts and returns plain data; the renderers below
turn that into either text or JSON. Keep new facts in `collect()` so both
outputs pick them up.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .. import colors, config, git_tool, paths, uv_tool
from .venv_cmd import _python_interpreter_path_venv

# Bump when a field changes meaning or goes away, so anything reading the
# JSON can tell. Adding a field doesn't need a bump.
SCHEMA_VERSION = 1


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _human(nbytes: int) -> str:
    size = float(nbytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def _size_of(path: Path, want_sizes: bool) -> int | None:
    if not want_sizes or not path.exists():
        return None
    return _dir_size(path)


def _size_suffix(nbytes: int | None) -> str:
    if nbytes is None:
        return ""
    return colors.dim(f"  [{_human(nbytes)}]")


def _uv_version() -> str | None:
    """None means uv isn't installed -- the renderers say so in their own way."""
    try:
        result = uv_tool.run_captured(["--version"], check=False)
        return result.stdout.strip() or "unknown"
    except uv_tool.UvNotFound:
        return None


def _venv_python_version(venv_dir: Path) -> str | None:
    cfg = venv_dir / "pyvenv.cfg"
    if not cfg.exists():
        return None
    try:
        for line in cfg.read_text().splitlines():
            if line.strip().lower().startswith("version"):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


# --- collection -------------------------------------------------------------

def _collect_tooling(want_sizes: bool) -> dict:
    git = git_tool.find_git()
    vscode_installed = (paths.VSCODE_APP_DIR.exists()
                        and any(paths.VSCODE_APP_DIR.iterdir()))
    return {
        "uv": {"version": _uv_version(), "path": str(paths.uv_binary())},
        "git": {"path": str(git) if git else None},
        "vscode": {
            "installed": vscode_installed,
            "path": str(paths.VSCODE_APP_DIR) if vscode_installed else None,
            "size_bytes": _size_of(paths.VSCODE_DIR, want_sizes),
        },
    }


def _collect_pythons(want_sizes: bool) -> list[dict]:
    if not paths.BASE_DIR.exists():
        return []
    default_tag = config.get_default_base()
    out = []
    for alias in sorted(paths.BASE_DIR.glob("*.alias.json")):
        tag = alias.name[: -len(".alias.json")]
        try:
            target = json.loads(alias.read_text())["target"]
        except (json.JSONDecodeError, KeyError, OSError):
            target = None
        resolved = paths.BASE_DIR / target if target else None
        present = bool(resolved and resolved.exists())
        out.append({
            "tag": tag,
            "target": target,
            "path": str(resolved) if resolved else None,
            "default": tag == default_tag,
            "present": present,
            "size_bytes": _size_of(resolved, want_sizes) if resolved else None,
        })
    return out


def _collect_venvs(want_sizes: bool) -> list[dict]:
    if not paths.VENVS_DIR.exists():
        return []
    active = os.environ.get("VIRTUAL_ENV")
    active_resolved = os.path.abspath(active) if active else None
    default_venv = config.get("default_venv")
    out = []
    for v in sorted(d for d in paths.VENVS_DIR.iterdir() if d.is_dir()):
        interpreter = _python_interpreter_path_venv(v)
        out.append({
            "name": v.name,
            "path": str(v),
            "python_version": _venv_python_version(v),
            "python_executable": str(interpreter) if interpreter else None,
            "active": active_resolved is not None
                      and os.path.abspath(str(v)) == active_resolved,
            "default": v.name == default_venv,
            "size_bytes": _size_of(v, want_sizes),
        })
    return out


def _collect_repos(want_sizes: bool, git: str | None) -> list[dict]:
    if not paths.REPO_DIR.exists():
        return []
    out = []
    for r in sorted(d for d in paths.REPO_DIR.iterdir() if d.is_dir()):
        remote = None
        if git and (r / ".git").exists():
            result = subprocess.run(
                [git, "-C", str(r), "remote", "get-url", "origin"],
                capture_output=True, text=True,
            )
            remote = result.stdout.strip() or None
        out.append({
            "name": r.name,
            "path": str(r),
            "remote": remote,
            "size_bytes": _size_of(r, want_sizes),
        })
    return out


def collect(want_sizes: bool = False) -> dict:
    """Everything `seed summary` knows, as plain data -- no printing, no
    color. Sizes are only walked when want_sizes is set; they're None
    otherwise, since walking the tree is the slow part."""
    home = paths.HOME
    if not home.exists():
        return {
            "schema": SCHEMA_VERSION,
            "home": str(home),
            "installed": False,
        }

    shared_root = config.get("shared_root")
    settings = config.load()
    return {
        "schema": SCHEMA_VERSION,
        "home": str(home),
        "installed": True,
        "install_type": "multi-user" if shared_root else "single-user",
        "shared_root": shared_root,
        "tooling": _collect_tooling(want_sizes),
        "pythons": _collect_pythons(want_sizes),
        "venvs": _collect_venvs(want_sizes),
        "repos": _collect_repos(want_sizes, git_tool.find_git()),
        "settings": {key: settings.get(key) for key in config.KNOWN_KEYS},
        "total_size_bytes": _size_of(home, want_sizes),
    }


# --- rendering --------------------------------------------------------------

def _section(title: str) -> None:
    print()
    print(colors.header(title))


def _render_text(data: dict, want_sizes: bool) -> int:
    print(colors.bold("seedling summary") + f"  ({data['home']})")
    if not data["installed"]:
        print("  install type: single-user")
        print("Nothing is installed yet -- run the installer first.")
        return 0

    if data["shared_root"]:
        print(f"  install type: multi-user (shared root: {data['shared_root']})")
    else:
        print("  install type: single-user")

    tooling = data["tooling"]
    _section("Tooling")
    uv_version = tooling["uv"]["version"]
    print(f"  uv:      {uv_version if uv_version else colors.warn('NOT FOUND')}")
    git = tooling["git"]["path"]
    print(f"  git:     {git if git else colors.dim('not found (auto-downloaded on Windows when needed)')}")
    vscode_str = ("installed" if tooling["vscode"]["installed"]
                  else "not installed (run `seed vscode`)")
    print(f"  VS Code: {vscode_str}{_size_suffix(tooling['vscode']['size_bytes'])}")

    _section(f"Base Pythons ({paths.BASE_DIR})")
    if not data["pythons"]:
        print("  none -- run: seed python <version>")
    for entry in data["pythons"]:
        target = entry["target"] or "?"
        marker = "  (default)" if entry["default"] else ""
        missing = "" if entry["present"] else colors.warn("  [missing!]")
        print(f"  {entry['tag']:<8} -> {target}{marker}{missing}"
              f"{_size_suffix(entry['size_bytes'])}")

    _section(f"Venvs ({paths.VENVS_DIR})")
    if not data["venvs"]:
        print("  none -- run: seed venv <name>")
    for entry in data["venvs"]:
        version = f"  [python {entry['python_version']}]" if entry["python_version"] else ""
        markers = ""
        if entry["active"]:
            markers += "  (active)"
        if entry["default"]:
            markers += "  (auto-activated in new shells)"
        print(f"  {entry['name']}{version}{markers}{_size_suffix(entry['size_bytes'])}")

    _section(f"Repos ({paths.REPO_DIR})")
    if not data["repos"]:
        print("  none -- run: seed repo-clone <git-url>")
    for entry in data["repos"]:
        suffix = colors.dim(f"  -> {entry['remote']}") if entry["remote"] else ""
        print(f"  {entry['name']}{suffix}{_size_suffix(entry['size_bytes'])}")

    _section("Settings")
    for key, value in data["settings"].items():
        if isinstance(value, list):
            shown = ", ".join(str(x) for x in value)
        elif value is None:
            shown = colors.dim("(not set)")
        else:
            shown = str(value)
        print(f"  {key} = {shown}")
    print(colors.dim("  change with: seed config set <key> <value>"))

    if want_sizes:
        _section("Total")
        print(f"  {data['home']}: {_human(data['total_size_bytes'] or 0)}")
    else:
        print()
        print(colors.dim("Tip: `seed summary --sizes` adds disk usage per item."))
    return 0


def run(args) -> int:
    want_sizes = getattr(args, "sizes", False)
    data = collect(want_sizes)
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return 0
    return _render_text(data, want_sizes)
