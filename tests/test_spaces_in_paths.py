"""Paths containing spaces -- the common Windows case of a username like
`First Last`, plus org share paths under `C:\\Program Files`. Regression
coverage so quoting/URL-encoding can't silently break."""

from __future__ import annotations

import json
import subprocess

import pytest

import conftest
from conftest import (BASH, make_repo_copy, make_venv_dirs, needs_bash,
                      plant_stub_uv)


@pytest.fixture
def spaced_home(tmp_path, monkeypatch):
    """Like the `home` fixture, but the seedling home has a space in it."""
    h = tmp_path / "space dir" / "seedling"
    for var in conftest._ISOLATED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SEEDLING_HOME", str(h))
    monkeypatch.setenv("SEEDLING_NO_LOG", "1")
    conftest._rebind_paths(h)
    from seedling.commands import kill_cmd
    monkeypatch.setattr(kill_cmd, "kill_python_and_vscode", lambda: [])
    yield h
    conftest._restore_paths()


def _run(capsys, *argv):
    from seedling import cli
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out + out.err


def test_config_roundtrip_in_spaced_home(spaced_home, capsys):
    code, _ = _run(capsys, "config", "set", "default_venv", "dev")
    assert code == 0
    settings = spaced_home / "system" / "config" / "settings.json"
    assert json.loads(settings.read_text())["default_venv"] == "dev"


def test_commands_work_in_spaced_home(spaced_home, capsys):
    make_venv_dirs(spaced_home, "dev")
    conftest.make_base_python(spaced_home, "312", "cpython-3.12.5-windows-x86_64-none")
    code, out = _run(capsys, "summary")
    assert code == 0
    assert "312" in out and "dev" in out
    assert "space dir" in out  # the home path really does contain a space


def test_offline_uv_toml_generated_for_spaced_index(spaced_home):
    """A wheels directory under a spaced path must still produce a usable
    file:// index URL. uv accepts a literal space, but the URL must at
    least round-trip the whole path."""
    from seedling import config, uv_tool
    config.set_value("package_index", r"C:\Program Files\wheels")
    env = uv_tool._build_env(None)
    toml = open(env["UV_CONFIG_FILE"], encoding="utf-8").read()
    assert "Program Files/wheels" in toml
    assert "default = true" in toml


def test_deferred_delete_bat_quotes_spaced_path(spaced_home, monkeypatch):
    from seedling import fsutil
    launched = {}
    monkeypatch.setattr(fsutil.subprocess, "Popen",
                        lambda cmd, **kw: launched.setdefault("cmd", cmd))
    if fsutil.os.name != "nt":
        pytest.skip("Windows deferred-delete uses a .bat")
    fsutil.schedule_deferred_delete(spaced_home)
    bat = launched["cmd"][-1]
    content = open(bat, encoding="utf-8").read()
    # rmdir target must be wrapped in quotes so the space doesn't split it
    assert f'rmdir /s /q "{spaced_home}"' in content


@needs_bash
def test_installer_into_spaced_home(tmp_path):
    """Full install.sh into a HOME containing a space: source copy, quoted
    hook line, uv tool install target -- all must survive."""
    copy = make_repo_copy(tmp_path / "copy")
    fake_home = tmp_path / "home dir"
    seedling_home = fake_home / "seedling"
    fake_home.mkdir()
    plant_stub_uv(seedling_home)

    result = subprocess.run(
        [BASH, "-c",
         f"cd '{copy.as_posix()}' && "
         f"HOME='{fake_home.as_posix()}' SHELL=/bin/bash SEEDLING_AUTO_SETUP=false "
         f"sh ./install.cmd"],
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (seedling_home / "system" / "src" / "src" / "pyproject.toml").exists()
    bashrc = (fake_home / ".bashrc").read_text()
    # hook line must be quoted so a spaced path sources correctly
    assert '. "' in bashrc and "seed.sh" in bashrc
    assert "space" in str(seedling_home) or "home dir" in bashrc
