"""
`seed tool-install / tool-list / tool-remove` -- command-line tools from
conda-forge (ripgrep, pandoc, ffmpeg, gh, compilers, ...), the things that
aren't Python packages and so aren't `seed install`-able.

Each tool gets its own isolated micromamba environment; seedling then writes a
small launcher for every command the tool provides into a shims directory that
the shell hook puts on PATH, so the tool runs as a bare command. Removal is
exact: the manifest records which shims were created.

conda-forge only -- see conda_tool for why that keeps seedling clear of
Anaconda's commercial terms.
"""

from __future__ import annotations

import json
import os
import re

from .. import colors, conda_tool, confirm, paths

# Environment/runtime commands that live in every conda env but are not the
# tool the user asked for -- never exposed as shims.
_NOT_TOOLS = {
    "python", "python3", "pythonw", "pip", "pip3", "conda", "mamba",
    "micromamba", "activate", "deactivate", "wheel", "pydoc", "pydoc3",
    "2to3", "idle", "idle3", "f2py", "python-config", "easy_install",
}

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _spec_name(spec: str) -> str:
    """'ripgrep=14.1' -> 'ripgrep'. The env (and default command) name."""
    for sep in ("=", "<", ">", " ", "[", "!", "~"):
        spec = spec.split(sep)[0]
    return spec.strip()


def _executables(env_dir) -> list[str]:
    """Command names a conda env exposes, minus the Python/conda runtime.

    Looks where conda actually puts executables on each platform (POSIX:
    bin/; Windows: the env root, Library\\bin, and Scripts)."""
    if os.name == "nt":
        # conda-forge splits executables across several dirs on Windows: the
        # env root (python.exe), Scripts (console entry points), Library\bin
        # (msys2/Library-layout tools), and bin (native binaries like
        # ripgrep's rg.exe). Search all of them.
        search = [env_dir, env_dir / "Scripts",
                  env_dir / "Library" / "bin", env_dir / "bin"]
        exts = {".exe", ".bat", ".cmd"}
    else:
        search = [env_dir / "bin"]
        exts = None

    names: dict[str, None] = {}
    for d in search:
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir()):
            if not entry.is_file():
                continue
            if exts is not None:
                if entry.suffix.lower() not in exts:
                    continue
                stem = entry.stem
            else:
                if not os.access(entry, os.X_OK):
                    continue
                stem = entry.name
            if stem.lower() in _NOT_TOOLS:
                continue
            names.setdefault(stem, None)   # first location wins, stable order
    return list(names)


def _write_shims(mm, name: str, commands: list[str]) -> None:
    """A launcher per command that runs it inside the tool's env via
    `micromamba run`, so the env's own libraries are on the path."""
    paths.TOOL_SHIMS_DIR.mkdir(parents=True, exist_ok=True)
    root = paths.MAMBA_DIR
    for cmd in commands:
        if os.name == "nt":
            shim = paths.TOOL_SHIMS_DIR / f"{cmd}.cmd"
            shim.write_text(
                f'@"{mm}" run -r "{root}" -n "{name}" "{cmd}" %*\r\n',
                encoding="utf-8")
        else:
            shim = paths.TOOL_SHIMS_DIR / cmd
            shim.write_text(
                f'#!/bin/sh\nexec "{mm}" run -r "{root}" -n "{name}" '
                f'"{cmd}" "$@"\n')
            shim.chmod(0o755)


def _remove_shims(commands: list[str]) -> None:
    for cmd in commands:
        for candidate in (paths.TOOL_SHIMS_DIR / cmd,
                          paths.TOOL_SHIMS_DIR / f"{cmd}.cmd"):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass


def _command_index() -> dict[str, str]:
    """{command name -> the tool/env that provides it} across every installed
    tool, so `seed tool <cmd>` can find and run it."""
    index: dict[str, str] = {}
    if not paths.TOOL_MANIFEST_DIR.is_dir():
        return index
    for m in sorted(paths.TOOL_MANIFEST_DIR.glob("*.json")):
        try:
            data = json.loads(m.read_text())
        except (OSError, ValueError):
            continue
        for cmd in data.get("commands", []):
            index.setdefault(cmd, m.stem)   # first tool to claim a name wins
    return index


def run_tool(args) -> int:
    """`seed tool <command> [args...]` -- run an installed conda-forge tool
    without needing it on PATH or a fresh terminal. The convenient, always-
    works counterpart to the PATH shims."""
    command = getattr(args, "name", None)
    toolargs = getattr(args, "toolargs", None) or []
    index = _command_index()

    if not command:
        print("Usage: seed tool <command> [args...]   "
              "(e.g. seed tool gh pr create)")
        if index:
            print("Available commands: " + ", ".join(sorted(index)))
        else:
            print("No conda-forge tools installed yet "
                  "(seed tool-install <name>).")
        return 1

    env_name = index.get(command)
    if env_name is None:
        print(f"No installed conda-forge tool provides the command "
              f"'{command}'.")
        if index:
            print("Available commands: " + ", ".join(sorted(index)))
        print("Install one with:  seed tool-install <name>")
        return 1

    try:
        conda_tool.find_micromamba()
    except conda_tool.MicromambaNotFound as e:
        print(f"error: {e}")
        return 1
    return conda_tool.exec_tool(env_name, command, toolargs)


def install(args) -> int:
    spec = getattr(args, "spec", None)
    if not spec:
        print("Usage: seed tool-install <name>[=version]   "
              "(e.g. seed tool-install ripgrep)")
        return 1

    name = _spec_name(spec)
    if not _NAME_RE.match(name):
        print(f"error: '{name}' is not a valid tool name.")
        return 1

    paths.ensure_layout()
    if paths.tool_env_dir(name).exists() or paths.tool_manifest_file(name).exists():
        print(f"A tool named '{name}' is already installed.")
        print(f"Remove it first with:  seed tool-remove {name}")
        return 1

    try:
        mm = conda_tool.ensure_micromamba()
    except conda_tool.MicromambaNotFound as e:
        print(f"error: {e}")
        return 1

    ch = conda_tool.channel()
    print(f"Installing '{spec}' from {ch} ...")
    result = conda_tool.run(
        ["create", "-y", "-n", name, "--override-channels", "-c", ch, spec],
        check=False)
    if result.returncode != 0:
        print(colors.warn(f"Could not install '{spec}'. Nothing was changed."))
        # Clean up a half-created env so a retry sees a clean slate.
        _cleanup_env(name)
        return 1

    commands = _executables(paths.tool_env_dir(name))
    if not commands:
        print(colors.warn(
            f"'{name}' installed, but it exposed no command-line programs "
            "(is it a library rather than a tool?)."))
        print("Removing it again; nothing was added to PATH. "
              "If this is wrong, report it.")
        _cleanup_env(name)
        return 1

    _write_shims(mm, name, commands)
    paths.TOOL_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    paths.tool_manifest_file(name).write_text(json.dumps(
        {"spec": spec, "channel": ch, "commands": commands}, indent=2))

    print(colors.ok(f"Installed '{name}'. Command(s): {', '.join(commands)}"))
    print("Open a new terminal (or add the shims dir to PATH) to use them.")
    return 0


def _cleanup_env(name: str) -> None:
    conda_tool.run(["env", "remove", "-y", "-n", name], check=False)
    import shutil
    shutil.rmtree(paths.tool_env_dir(name), ignore_errors=True)


def list_tools(args) -> int:
    manifests = (sorted(paths.TOOL_MANIFEST_DIR.glob("*.json"))
                 if paths.TOOL_MANIFEST_DIR.is_dir() else [])
    if not manifests:
        print("No conda-forge tools installed.")
        print("Install one with:  seed tool-install <name>   "
              "(e.g. ripgrep, pandoc, ffmpeg)")
        return 0

    print("conda-forge tools:")
    for m in manifests:
        try:
            data = json.loads(m.read_text())
        except (OSError, ValueError):
            continue
        cmds = ", ".join(data.get("commands", [])) or "(none)"
        print(f"  {colors.bold(m.stem)}  ->  {cmds}"
              f"   {colors.dim('(' + data.get('spec', m.stem) + ')')}")
    return 0


def remove(args) -> int:
    name = getattr(args, "name", None)
    if not name:
        print("Usage: seed tool-remove <name>")
        return 1

    manifest = paths.tool_manifest_file(name)
    env_dir = paths.tool_env_dir(name)
    if not manifest.exists() and not env_dir.exists():
        print(f"No conda-forge tool named '{name}' is installed.")
        return 1

    commands = []
    if manifest.exists():
        try:
            commands = json.loads(manifest.read_text()).get("commands", [])
        except (OSError, ValueError):
            commands = []

    if confirm.preview_requested(args):
        confirm.print_preview(
            f"remove conda-forge tool '{name}'",
            [f"environment {env_dir}"]
            + [f"command '{c}'" for c in commands],
        )
        return 0

    _remove_shims(commands)
    _cleanup_env(name)
    try:
        manifest.unlink()
    except FileNotFoundError:
        pass
    print(colors.ok(f"Removed conda-forge tool '{name}'."))
    return 0
