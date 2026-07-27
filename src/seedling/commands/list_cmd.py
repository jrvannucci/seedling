"""
The listing commands: `seed venv-list`, `seed python-list`, and
`seed package-list`.

Each takes `--json`. The venv and python payloads are built by
summary_cmd's collectors rather than assembled here, so a venv looks the
same to a consumer whether it arrived via `seed venv-list --json` or
`seed summary --json` -- two shapes for one thing would be a bug waiting to
happen. `package-list` is different: it forwards to `uv pip list`, which
already speaks JSON, so `--json` becomes uv's own `--format json` and the
output is uv's, unwrapped.

Under `--json`, stdout carries the document and nothing else -- the "no venv
looks active" note that helps a person at a terminal would break every
parser, so it moves to stderr.
"""

from __future__ import annotations

import json
import os
import sys

from .. import config, paths, uv_tool
from . import summary_cmd

# Bump when a field changes meaning or goes away, matching `summary --json`.
SCHEMA_VERSION = 1

_NO_VENV_NOTE = ("Note: no venv looks active (VIRTUAL_ENV isn't set). "
                 "Run `seed activate <name>` first, or uv will fall back to "
                 "whatever it can find (e.g. a .venv in the current directory).")


def _warn_no_active_venv(want_json: bool) -> None:
    if os.environ.get("VIRTUAL_ENV"):
        return
    # stderr under --json so the document on stdout stays parseable; stdout
    # otherwise, which is where it has always gone for a human reader.
    print(_NO_VENV_NOTE, file=sys.stderr if want_json else sys.stdout)


def list_packages(args) -> int:
    """seed package-list -- passthrough to `uv pip list` for the active venv."""
    extra = list(getattr(args, "extra", None) or [])
    # `--json` is seedling's spelling across every read command; uv spells the
    # same thing `--format json`. Translate rather than make callers remember
    # which layer they're talking to. An explicit --format is left alone.
    want_json = "--json" in extra
    if want_json:
        extra = [a for a in extra if a != "--json"]
        if not any(a == "--format" or a.startswith("--format=") for a in extra):
            extra += ["--format", "json"]
    _warn_no_active_venv(want_json)
    uv_tool.run(["pip", "list", *extra])
    return 0


def _read_venv_python_version(venv_dir) -> str | None:
    """Best-effort read of the Python version a venv was created with,
    straight out of its pyvenv.cfg."""
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


def list_python(args) -> int:
    if getattr(args, "json", False):
        print(json.dumps({
            "schema": SCHEMA_VERSION,
            "base_dir": str(paths.BASE_DIR),
            "pythons": summary_cmd.collect_pythons(),
        }, indent=2))
        return 0

    if not paths.BASE_DIR.exists():
        print("No base Python interpreters installed yet. Run: seed python <version>")
        return 0

    alias_files = sorted(paths.BASE_DIR.glob("*.alias.json"))
    if not alias_files:
        print("No base Python interpreters installed yet. Run: seed python <version>")
        return 0

    default_tag = config.get_default_base()

    print(f"Base Python interpreters in {paths.BASE_DIR}:")
    for alias in alias_files:
        tag = alias.name[: -len(".alias.json")]
        try:
            target = json.loads(alias.read_text())["target"]
        except (json.JSONDecodeError, KeyError, OSError):
            target = "?"

        resolved = paths.BASE_DIR / target
        marker = "  (default for `seed venv`)" if tag == default_tag else ""
        missing = "" if resolved.exists() else f"  [missing! re-run: seed python {tag}]"
        print(f"  {tag:<8} -> {target}{marker}{missing}")

    return 0


def list_venvs(args) -> int:
    if getattr(args, "json", False):
        print(json.dumps({
            "schema": SCHEMA_VERSION,
            "venvs_dir": str(paths.VENVS_DIR),
            "venvs": summary_cmd.collect_venvs(),
        }, indent=2))
        return 0

    if not paths.VENVS_DIR.exists():
        print("No venvs created yet. Run: seed venv <name>")
        return 0

    venvs = sorted(d for d in paths.VENVS_DIR.iterdir() if d.is_dir())
    if not venvs:
        print("No venvs created yet. Run: seed venv <name>")
        return 0

    active = os.environ.get("VIRTUAL_ENV")
    active_resolved = os.path.abspath(active) if active else None
    default_venv = config.get("default_venv")

    print(f"Venvs in {paths.VENVS_DIR}:")
    for v in venvs:
        version = _read_venv_python_version(v)
        version_str = f"  [python {version}]" if version else ""
        marker = "  (active)" if active_resolved and os.path.abspath(str(v)) == active_resolved else ""
        if v.name == default_venv:
            marker += "  (auto-activated in new shells)"
        print(f"  {v.name}{version_str}{marker}")

    return 0
