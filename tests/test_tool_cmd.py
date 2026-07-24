"""
`seed tool-install / tool-list / tool-remove` -- conda-forge tools via
micromamba.

micromamba itself is never run here: conda_tool.run is stubbed to fabricate the
environment a real `micromamba create` would produce (an executable in the
env's bin), so the parts that are seedling's own logic -- command discovery,
shim generation, the manifest, list, and exact removal -- are exercised
deterministically with no network and no binary.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from seedling import conda_tool, config, paths
from seedling.commands import tool_cmd


@pytest.fixture
def fake_micromamba(monkeypatch, home):
    """Make conda_tool a no-network stub. `create` lays down a realistic env
    (a tool binary plus a python runtime that must NOT be exposed); `env
    remove` deletes it. Records every invocation for assertions."""
    calls = []

    def fake_ensure():
        mm = paths.micromamba_binary()
        mm.parent.mkdir(parents=True, exist_ok=True)
        mm.write_text("stub")
        return mm

    def fake_run(args, *, env=None, check=True):
        calls.append(args)
        if args[:1] == ["create"]:
            name = args[args.index("-n") + 1]
            env_dir = paths.tool_env_dir(name)
            if os.name == "nt":
                # Mirror ripgrep's real conda-forge win-64 layout: the tool
                # binary in <env>\bin, the python runtime at the env root.
                bindir = env_dir / "bin"
                bindir.mkdir(parents=True, exist_ok=True)
                (bindir / f"{name}.exe").write_text("x")
                (env_dir / "python.exe").write_text("x")   # must be filtered
            else:
                bindir = env_dir / "bin"
                bindir.mkdir(parents=True, exist_ok=True)
                tool = bindir / name
                tool.write_text("#!/bin/sh\n")
                tool.chmod(0o755)
                py = bindir / "python"
                py.write_text("#!/bin/sh\n")
                py.chmod(0o755)                            # must be filtered
        elif args[:2] == ["env", "remove"]:
            import shutil
            name = args[args.index("-n") + 1]
            shutil.rmtree(paths.tool_env_dir(name), ignore_errors=True)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(conda_tool, "ensure_micromamba", fake_ensure)
    monkeypatch.setattr(conda_tool, "run", fake_run)
    monkeypatch.setattr(tool_cmd.conda_tool, "ensure_micromamba", fake_ensure)
    monkeypatch.setattr(tool_cmd.conda_tool, "run", fake_run)
    return calls


def _shim(name):
    return (paths.TOOL_SHIMS_DIR / (f"{name}.cmd" if os.name == "nt" else name))


def test_install_creates_env_shim_and_manifest(fake_micromamba, home, capsys):
    rc = tool_cmd.install(_ns(spec="ripgrep"))
    assert rc == 0

    # conda-forge only: never `defaults`.
    create = next(c for c in fake_micromamba if c[:1] == ["create"])
    assert "--override-channels" in create
    assert create[create.index("-c") + 1] == "conda-forge"
    assert "defaults" not in create

    assert _shim("ripgrep").exists()
    manifest = json.loads(paths.tool_manifest_file("ripgrep").read_text())
    assert manifest["commands"] == ["ripgrep"]
    assert manifest["spec"] == "ripgrep"


def test_install_does_not_expose_python_runtime(fake_micromamba, home):
    tool_cmd.install(_ns(spec="ripgrep"))
    # the env also contains a python executable; it must not become a shim
    assert not _shim("python").exists()
    manifest = json.loads(paths.tool_manifest_file("ripgrep").read_text())
    assert "python" not in manifest["commands"]


def test_install_rejects_duplicate(fake_micromamba, home, capsys):
    tool_cmd.install(_ns(spec="ripgrep"))
    rc = tool_cmd.install(_ns(spec="ripgrep"))
    assert rc == 1
    assert "already installed" in capsys.readouterr().out


def test_version_pin_names_the_env_after_the_package(fake_micromamba, home):
    tool_cmd.install(_ns(spec="ripgrep=14.1.0"))
    assert paths.tool_env_dir("ripgrep").exists()
    assert _shim("ripgrep").exists()


def test_channel_override_is_honoured(fake_micromamba, home):
    config.set_value("conda_channel", "S:/mirror/conda-forge")
    tool_cmd.install(_ns(spec="ripgrep"))
    create = next(c for c in fake_micromamba if c[:1] == ["create"])
    assert create[create.index("-c") + 1] == "S:/mirror/conda-forge"


def test_list_shows_installed_tools(fake_micromamba, home, capsys):
    tool_cmd.install(_ns(spec="ripgrep"))
    capsys.readouterr()
    rc = tool_cmd.list_tools(_ns())
    out = capsys.readouterr().out
    assert rc == 0 and "ripgrep" in out


def test_list_empty(home, capsys):
    rc = tool_cmd.list_tools(_ns())
    assert rc == 0
    assert "No conda-forge tools installed" in capsys.readouterr().out


def test_remove_deletes_env_shim_and_manifest(fake_micromamba, home):
    tool_cmd.install(_ns(spec="ripgrep"))
    assert _shim("ripgrep").exists()
    rc = tool_cmd.remove(_ns(name="ripgrep", preview=False))
    assert rc == 0
    assert not _shim("ripgrep").exists()
    assert not paths.tool_manifest_file("ripgrep").exists()
    assert not paths.tool_env_dir("ripgrep").exists()


def test_remove_preview_changes_nothing(fake_micromamba, home, capsys):
    tool_cmd.install(_ns(spec="ripgrep"))
    rc = tool_cmd.remove(_ns(name="ripgrep", preview=True))
    assert rc == 0
    assert _shim("ripgrep").exists()                       # untouched
    assert paths.tool_manifest_file("ripgrep").exists()
    assert "Preview" in capsys.readouterr().out


def test_remove_unknown(home, capsys):
    rc = tool_cmd.remove(_ns(name="ghost", preview=False))
    assert rc == 1
    assert "No conda-forge tool named 'ghost'" in capsys.readouterr().out


def test_run_tool_dispatches_to_the_right_env(fake_micromamba, home, monkeypatch):
    """`seed tool <cmd> args` finds which env provides <cmd> and execs it
    there, passing arguments straight through."""
    tool_cmd.install(_ns(spec="ripgrep"))    # stub exposes command 'ripgrep'
    execed = {}

    def fake_exec(env_name, command, toolargs):
        execed.update(env=env_name, command=command, args=toolargs)
        return 0
    monkeypatch.setattr(tool_cmd.conda_tool, "exec_tool", fake_exec)
    monkeypatch.setattr(tool_cmd.conda_tool, "find_micromamba",
                        lambda: paths.micromamba_binary())

    rc = tool_cmd.run_tool(_ns(name="ripgrep", toolargs=["foo", "--bar"]))
    assert rc == 0
    assert execed == {"env": "ripgrep", "command": "ripgrep",
                      "args": ["foo", "--bar"]}


def test_run_tool_propagates_exit_code(fake_micromamba, home, monkeypatch):
    tool_cmd.install(_ns(spec="ripgrep"))
    monkeypatch.setattr(tool_cmd.conda_tool, "exec_tool", lambda *a: 2)
    monkeypatch.setattr(tool_cmd.conda_tool, "find_micromamba",
                        lambda: paths.micromamba_binary())
    assert tool_cmd.run_tool(_ns(name="ripgrep", toolargs=[])) == 2


def test_run_tool_unknown_command(fake_micromamba, home, capsys):
    tool_cmd.install(_ns(spec="ripgrep"))
    capsys.readouterr()
    rc = tool_cmd.run_tool(_ns(name="nope", toolargs=[]))
    assert rc == 1
    out = capsys.readouterr().out
    assert "No installed conda-forge tool provides" in out
    assert "ripgrep" in out                # lists what IS available


def test_run_tool_no_command_lists_available(fake_micromamba, home, capsys):
    tool_cmd.install(_ns(spec="ripgrep"))
    capsys.readouterr()
    rc = tool_cmd.run_tool(_ns(name=None, toolargs=[]))
    assert rc == 1
    assert "ripgrep" in capsys.readouterr().out


class _ns:
    """Lightweight argparse.Namespace substitute."""
    def __init__(self, **kw):
        self.__dict__.update(kw)
