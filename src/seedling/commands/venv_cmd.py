from __future__ import annotations

import os

from .. import colors, config, paths, uv_tool
from . import python_cmd


def _python_interpreter_path(base_dir):
    # uv's managed CPython layout: <base>/bin/python3 on unix, <base>/python.exe on windows
    if os.name == "nt":
        candidate = base_dir / "python.exe"
        if candidate.exists():
            return candidate
    candidate = base_dir / "bin" / "python3"
    if candidate.exists():
        return candidate
    candidate = base_dir / "bin" / "python"
    if candidate.exists():
        return candidate
    return None


def run(args) -> int:
    if not args.name:
        print("Usage: seed venv <name> [--python <tag>]")
        return 1

    paths.ensure_layout()

    tag = args.python or config.get_default_base()
    if tag is None:
        print("No base Python found. Install one first, e.g.:  seed python 312")
        return 1

    base_dir = python_cmd.resolve_base(tag)
    if base_dir is None:
        print(f"Base python '{tag}' isn't installed. Run:  seed python {tag}")
        return 1

    interpreter = _python_interpreter_path(base_dir)
    if interpreter is None:
        print(f"Could not find a python executable inside {base_dir}")
        return 1

    target = paths.venv_dir(args.name)
    if target.exists():
        print(f"A venv named '{args.name}' already exists at {target}")
        return 1

    print(f"Creating venv '{args.name}' from base '{tag}' -> {target}")
    result = uv_tool.run_captured(["venv", "--python", str(interpreter), str(target)])
    for line in (result.stdout + result.stderr).splitlines():
        # uv prints its own "Activate with: source .../activate" hint, which
        # doesn't match how `seed activate` actually works (it's a shell
        # function, not a sourced script path) -- drop just that hint line,
        # keep everything else (interpreter resolution, creation confirmation,
        # etc.). Matching the "activate with" lead-in rather than any mention
        # of "activate" avoids swallowing unrelated uv output.
        if "activate with" in line.lower():
            continue
        if line.strip():
            print(uv_tool.tag_line(line))

    default_packages = config.get("venv_default_packages") or []
    if default_packages and not getattr(args, "no_default_packages", False):
        print(f"Installing default packages: {', '.join(default_packages)} "
              "(skip with --no-default-packages)")
        venv_python = _python_interpreter_path_venv(target)
        if venv_python is None:
            print("warning: couldn't find the new venv's python executable; "
                  "skipping default packages.")
        else:
            result = uv_tool.run(
                ["pip", "install", "--python", str(venv_python), *default_packages],
                check=False,
            )
            if result.returncode != 0:
                print("warning: default package install failed; the venv "
                      "itself is fine. Install them later with `seed install "
                      f"{' '.join(default_packages)}`.")

    print("Done.")
    print(colors.ok(f"Activate it with:  seed activate {args.name}"))
    return 0


def _python_interpreter_path_venv(venv_dir):
    """A venv's own interpreter (layout differs from uv's managed CPython
    dirs, which _python_interpreter_path handles)."""
    if os.name == "nt":
        candidate = venv_dir / "Scripts" / "python.exe"
    else:
        candidate = venv_dir / "bin" / "python"
    return candidate if candidate.exists() else None
