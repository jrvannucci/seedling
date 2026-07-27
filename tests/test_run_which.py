"""`seed run` and `seed which`: venv resolution precedence, the
stdout-is-only-the-path contract, exit-code passthrough, and the child
environment."""

from __future__ import annotations

import json
import os
import sys

import pytest
from conftest import make_venv_dirs

from seedling import config, paths, venv_target
from seedling.commands import run_cmd


# --- resolution precedence --------------------------------------------------

def test_explicit_name_wins(home, monkeypatch):
    make_venv_dirs(home, "dev", "other")
    monkeypatch.setenv("VIRTUAL_ENV", str(paths.venv_dir("other")))
    config.set_value("default_venv", "other")
    target, error = venv_target.resolve("dev")
    assert error is None
    assert target.name == "dev"
    assert target.source == venv_target.SOURCE_ARGUMENT


def test_active_venv_beats_default(home, monkeypatch):
    make_venv_dirs(home, "dev", "other")
    monkeypatch.setenv("VIRTUAL_ENV", str(paths.venv_dir("other")))
    config.set_value("default_venv", "dev")
    target, error = venv_target.resolve()
    assert error is None
    assert target.name == "other"
    assert target.source == venv_target.SOURCE_VIRTUAL_ENV


def test_falls_back_to_default_venv(home):
    make_venv_dirs(home, "dev")
    config.set_value("default_venv", "dev")
    target, error = venv_target.resolve()
    assert error is None
    assert target.source == venv_target.SOURCE_DEFAULT_VENV


def test_explicit_miss_never_falls_back(home):
    """An explicit request that can't be honored is an error -- silently
    using a DIFFERENT environment than the one named is the worst possible
    outcome here."""
    make_venv_dirs(home, "dev")
    config.set_value("default_venv", "dev")
    target, error = venv_target.resolve("ghost")
    assert target is None
    assert error.reason == venv_target.REASON_NOT_FOUND
    assert "no venv named 'ghost'" in error.message


def test_nothing_to_resolve(home):
    target, error = venv_target.resolve()
    assert target is None
    assert error.reason == venv_target.REASON_NONE_CONFIGURED
    assert "no venv to use" in error.message


def test_active_venv_outside_seedling_is_honored(home, monkeypatch, tmp_path):
    """`seed install` installs into whatever is active, seedling-managed or
    not; `run` and `which` must not disagree about what "current" means."""
    outside = tmp_path / "elsewhere"
    bindir = outside / ("Scripts" if os.name == "nt" else "bin")
    bindir.mkdir(parents=True)
    (bindir / ("python.exe" if os.name == "nt" else "python")).write_text("")
    monkeypatch.setenv("VIRTUAL_ENV", str(outside))

    target, error = venv_target.resolve()
    assert error is None
    assert target.name == "elsewhere"


def test_strict_mode_stops_on_a_broken_active_venv(home, monkeypatch, tmp_path):
    """`seed run` must never quietly act on a DIFFERENT environment than the
    one the caller is pointing at -- so a dangling VIRTUAL_ENV is an error,
    not a silent fall-through to default_venv."""
    make_venv_dirs(home, "dev")
    config.set_value("default_venv", "dev")
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "gone"))

    target, error = venv_target.resolve()
    assert target is None
    assert error.reason == venv_target.REASON_BROKEN
    assert error.source == venv_target.SOURCE_VIRTUAL_ENV


def test_lenient_mode_falls_through_instead(home, monkeypatch, tmp_path):
    """The same state, resolved leniently, walks on down the precedence.
    This is what `seed spyder` asks for; see spyder_cmd.resolve_venv."""
    make_venv_dirs(home, "dev")
    config.set_value("default_venv", "dev")
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "gone"))

    target, error = venv_target.resolve(lenient=True)
    assert error is None
    assert target.name == "dev"


def test_lenient_mode_is_still_strict_about_an_explicit_name(home):
    """Substituting a different venv for one asked for BY NAME is never the
    helpful move, however lenient the caller asked to be."""
    make_venv_dirs(home, "dev")
    config.set_value("default_venv", "dev")
    target, error = venv_target.resolve("ghost", lenient=True)
    assert target is None
    assert error.source == venv_target.SOURCE_ARGUMENT


# --- seed which -------------------------------------------------------------

def test_which_prints_only_the_path(home, capsys):
    """The whole point of the command: `$(seed which dev)` must be usable,
    so not one byte of prose may land on stdout."""
    make_venv_dirs(home, "dev")
    from seedling import cli
    assert cli.main(["which", "dev"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == str(paths.venv_python("dev"))
    assert captured.err == ""


def test_which_sends_errors_to_stderr(home, capsys):
    from seedling import cli
    assert cli.main(["which", "ghost"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""          # nothing where a path would go
    assert "no venv named 'ghost'" in captured.err


def test_which_json(home, capsys):
    make_venv_dirs(home, "dev")
    from seedling import cli
    assert cli.main(["which", "dev", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["found"] is True
    assert doc["name"] == "dev"
    assert doc["source"] == "argument"
    assert doc["python_executable"] == str(paths.venv_python("dev"))
    assert os.path.isdir(doc["bin_dir"])


def test_which_json_reports_failure_as_json(home, capsys):
    """A consumer that always parses stdout shouldn't have to special-case
    the failure path."""
    from seedling import cli
    assert cli.main(["which", "ghost", "--json"]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["found"] is False
    assert "ghost" in doc["error"]


# --- seed run ---------------------------------------------------------------

def test_run_without_a_command_is_usage(run_cli, home):
    code, out = run_cli("run")
    assert code == 1
    assert "Usage: seed run" in out


def test_run_passes_the_exit_code_through(home, monkeypatch):
    """`seed run -- pytest` is worthless in CI if this doesn't hold."""
    make_venv_dirs(home, "dev")
    from seedling import cli
    code = cli.main(["run", "-n", "dev", "--",
                     sys.executable, "-c", "import sys; sys.exit(7)"])
    assert code == 7


def test_run_sets_up_the_venv_environment(home, capfd):
    make_venv_dirs(home, "dev")
    from seedling import cli
    code = cli.main([
        "run", "-n", "dev", "--", sys.executable, "-c",
        "import json, os; print(json.dumps({"
        "'venv': os.environ.get('VIRTUAL_ENV'),"
        "'first_path': os.environ['PATH'].split(os.pathsep)[0],"
        "'home': os.environ.get('PYTHONHOME')}))",
    ])
    assert code == 0
    # capfd, not capsys: the child writes to the real file descriptors.
    reported = json.loads(capfd.readouterr().out)
    assert reported["venv"] == str(paths.venv_dir("dev"))
    assert reported["first_path"] == str(paths.venv_bin_dir("dev"))
    assert reported["home"] is None


def _fake_executable(directory, name: str, marker: str):
    """A runnable stub in `directory` that prints `marker`, in whatever form
    the platform can actually execute."""
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        script = directory / f"{name}.bat"
        script.write_text(f"@echo {marker}\n")
    else:
        script = directory / name
        script.write_text(f"#!/bin/sh\necho {marker}\n")
        script.chmod(0o755)
    return script


def test_run_resolves_the_command_inside_the_venv(home, capfd, monkeypatch, tmp_path):
    """The bug this guards is silent and exactly backwards: on Windows,
    CreateProcess resolves argv[0] against the PARENT's PATH, so handing a
    bare name to subprocess sets the venv up correctly and then runs the
    system copy inside it. `seed run -- python` must run the VENV's python.
    """
    make_venv_dirs(home, "dev")
    _fake_executable(paths.venv_bin_dir("dev"), "seedprobe", "FROM_THE_VENV")

    # A same-named executable earlier on the parent's PATH: whichever one
    # runs tells us which PATH was actually consulted.
    outside = tmp_path / "outside"
    _fake_executable(outside, "seedprobe", "FROM_OUTSIDE")
    monkeypatch.setenv("PATH", str(outside) + os.pathsep + os.environ["PATH"])

    from seedling import cli
    assert cli.main(["run", "-n", "dev", "--", "seedprobe"]) == 0
    assert "FROM_THE_VENV" in capfd.readouterr().out


def test_resolve_command_uses_the_child_path(home, tmp_path):
    make_venv_dirs(home, "dev")
    _fake_executable(paths.venv_bin_dir("dev"), "seedprobe", "x")
    target, _ = venv_target.resolve("dev")
    env = run_cmd.child_env(target)
    resolved = run_cmd.resolve_command("seedprobe", env)
    assert resolved is not None
    assert str(paths.venv_bin_dir("dev")) in resolved


def test_resolve_command_leaves_a_path_alone(home):
    """Nothing to search for -- and searching would break a relative path."""
    assert run_cmd.resolve_command("./script.py", {"PATH": ""}) == "./script.py"


def test_run_reports_a_missing_command_as_127(home, capsys):
    make_venv_dirs(home, "dev")
    from seedling import cli
    assert cli.main(["run", "-n", "dev", "--", "no-such-binary-xyz"]) == 127
    assert "command not found in venv 'dev'" in capsys.readouterr().err


def test_run_refuses_an_unknown_venv(home, capsys):
    from seedling import cli
    assert cli.main(["run", "-n", "ghost", "--", sys.executable, "-V"]) == 1
    assert "no venv named 'ghost'" in capsys.readouterr().err


@pytest.mark.parametrize("given,expected", [
    (["--", "pytest", "-q"], ["pytest", "-q"]),
    (["pytest", "-q"], ["pytest", "-q"]),
    # Only the FIRST separator is ours; the second belongs to the child.
    (["--", "pytest", "--", "-k", "foo"], ["pytest", "--", "-k", "foo"]),
    ([], []),
])
def test_strip_separator(given, expected):
    assert run_cmd.strip_separator(given) == expected


def test_child_env_leaves_the_parent_alone(home, monkeypatch):
    make_venv_dirs(home, "dev")
    monkeypatch.setenv("PYTHONHOME", "/somewhere/stale")
    target, _ = venv_target.resolve("dev")
    env = run_cmd.child_env(target)
    assert "PYTHONHOME" not in env
    assert os.environ["PYTHONHOME"] == "/somewhere/stale"
