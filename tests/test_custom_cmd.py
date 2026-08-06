"""`seed custom` dispatch (seedling/commands/custom_cmd.py): running a `run`
entry (ambient and venv-routed), running a `script` entry, argv passthrough,
the `toplevel` short-circuit in cli.py, and collision handling with built-in
commands.

Tests that check output produced by a CHILD PROCESS use `capfd` and call
`cli.main()` directly, not the `run_cli` fixture -- a subprocess writes to
the real file descriptors, which `capsys` (what `run_cli` uses) does not
see. Same convention `test_run_which.py` already established.
"""

from __future__ import annotations

import os
import sys

from conftest import make_venv_dirs, needs_bash, needs_powershell

from seedling import cli, config, paths
from seedling.commands import custom_cmd


def _write_toml(tmp_path, text: str):
    """Writes custom-commands.toml at tmp_path -- a `script = "..."` entry
    in `text` resolves relative to tmp_path, so a companion script file
    written directly under tmp_path is what it finds."""
    p = tmp_path / "custom-commands.toml"
    p.write_text(text, encoding="utf-8")
    config.set_value("custom_commands", str(p))
    return p


def _fake_executable(directory, name: str, marker: str):
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        script = directory / f"{name}.bat"
        script.write_text(f"@echo {marker}\n")
    else:
        script = directory / name
        script.write_text(f"#!/bin/sh\necho {marker}\n")
        script.chmod(0o755)
    return script


# --- no commands configured -------------------------------------------------

def test_custom_with_nothing_configured(run_cli, home):
    code, out = run_cli("custom")
    assert code == 1
    assert "No custom commands configured" in out


def test_custom_unknown_name(run_cli, home, tmp_path):
    _write_toml(tmp_path, '[[command]]\nname = "lint"\nrun = ["x"]\n')
    code, out = run_cli("custom", "ghost")
    assert code == 1
    assert "No custom command named 'ghost'" in out
    assert "Available: lint" in out


# --- run entries ---------------------------------------------------------

def test_run_ambient_and_args_passthrough(home, tmp_path, capfd):
    _write_toml(tmp_path, '''
        [[command]]
        name = "hello"
        run = ["%s", "-c", "import sys; print(','.join(sys.argv[1:]))"]
    ''' % sys.executable.replace("\\", "\\\\"))
    code = cli.main(["custom", "hello", "a", "b"])
    assert code == 0
    assert capfd.readouterr().out.strip() == "a,b"


def test_run_exit_code_passthrough(home, tmp_path):
    _write_toml(tmp_path, '''
        [[command]]
        name = "fail"
        run = ["%s", "-c", "import sys; sys.exit(7)"]
    ''' % sys.executable.replace("\\", "\\\\"))
    assert cli.main(["custom", "fail"]) == 7


def test_run_inside_a_venv(home, tmp_path, monkeypatch, capfd):
    make_venv_dirs(home, "dev")
    _fake_executable(paths.venv_bin_dir("dev"), "seedprobe", "FROM_THE_VENV")
    outside = tmp_path / "outside"
    _fake_executable(outside, "seedprobe", "FROM_OUTSIDE")
    monkeypatch.setenv("PATH", str(outside) + os.pathsep + os.environ["PATH"])

    _write_toml(tmp_path, '''
        [[command]]
        name = "probe"
        run = ["seedprobe"]
        venv = "dev"
    ''')
    code = cli.main(["custom", "probe"])
    assert code == 0
    assert "FROM_THE_VENV" in capfd.readouterr().out


def test_run_command_not_found_in_venv_is_an_error(run_cli, home, tmp_path):
    """Distinct from an unknown venv: the venv resolves fine, but `run`'s
    program isn't installed in it -- custom_cmd.py's own copy of this
    message (run_cmd.py has an identical one for `seed run`, tested
    separately)."""
    make_venv_dirs(home, "dev")
    _write_toml(tmp_path, '''
        [[command]]
        name = "probe"
        run = ["definitely-not-a-real-executable"]
        venv = "dev"
    ''')
    code, out = run_cli("custom", "probe")
    assert code == 127
    assert "command not found in venv 'dev': definitely-not-a-real-executable" in out


def test_run_unknown_venv_is_an_error(run_cli, home, tmp_path):
    _write_toml(tmp_path, '''
        [[command]]
        name = "probe"
        run = ["x"]
        venv = "ghost"
    ''')
    code, out = run_cli("custom", "probe")
    assert code == 1
    assert "no venv named 'ghost'" in out


def test_bad_toml_degrades_gracefully(run_cli, home, tmp_path):
    """A typo in the org's file must not break unrelated commands."""
    _write_toml(tmp_path, "not valid toml {{{")
    code, _out = run_cli("venv-list")
    assert code == 0
    code, out = run_cli("custom")
    assert code == 1
    assert "custom-commands.toml" in out


# --- script entries --------------------------------------------------------

def test_script_command_runs_and_gets_args(home, tmp_path, capfd):
    (tmp_path / "greet.py").write_text(
        "import sys\nprint('hi ' + ' '.join(sys.argv[1:]))\n")
    _write_toml(tmp_path, '[[command]]\nname = "greet"\nscript = "greet.py"\n')
    code = cli.main(["custom", "greet", "Jon"])
    assert code == 0
    assert capfd.readouterr().out.strip() == "hi Jon"


def test_script_companion_data_file(home, tmp_path, capfd):
    """The case a flat `run` list can't express: a script resolving a
    sibling data file relative to itself."""
    (tmp_path / "quotes.txt").write_text("only one line here\n")
    (tmp_path / "quote.py").write_text(
        "from pathlib import Path\n"
        "print((Path(__file__).parent / 'quotes.txt').read_text().strip())\n")
    _write_toml(tmp_path, '[[command]]\nname = "quote"\nscript = "quote.py"\n')
    code = cli.main(["custom", "quote"])
    assert code == 0
    assert capfd.readouterr().out.strip() == "only one line here"


def test_script_missing_file_is_a_clear_error(run_cli, home, tmp_path):
    _write_toml(tmp_path, '[[command]]\nname = "ghost"\nscript = "ghost.py"\n')
    code, out = run_cli("custom", "ghost")
    assert code == 1
    assert "script not found" in out


@needs_bash
def test_sh_script_command_runs_and_gets_args(home, tmp_path, capfd):
    (tmp_path / "greet.sh").write_text(
        '#!/bin/sh\necho "hi $1 from sh"\n')
    _write_toml(tmp_path, '[[command]]\nname = "greet"\nscript = "greet.sh"\n')
    code = cli.main(["custom", "greet", "Jon"])
    assert code == 0
    assert capfd.readouterr().out.strip() == "hi Jon from sh"


@needs_powershell
def test_ps1_script_command_runs_and_gets_args(home, tmp_path, capfd):
    (tmp_path / "greet.ps1").write_text(
        'param([string]$name)\nWrite-Output "hi $name from ps1"\n')
    _write_toml(tmp_path, '[[command]]\nname = "greet"\nscript = "greet.ps1"\n')
    code = cli.main(["custom", "greet", "Jon"])
    assert code == 0
    assert capfd.readouterr().out.strip() == "hi Jon from ps1"


def test_toplevel_field_runs_as_bare_seed(home, tmp_path, capfd):
    (tmp_path / "greet.py").write_text("print('hi from toplevel')\n")
    _write_toml(tmp_path, '''
        [[command]]
        name = "greet"
        script = "greet.py"
        toplevel = true
    ''')

    code = cli.main(["greet"])
    assert code == 0
    assert "hi from toplevel" in capfd.readouterr().out

    # Still reachable the namespaced way too.
    code = cli.main(["custom", "greet"])
    assert code == 0
    assert "hi from toplevel" in capfd.readouterr().out


def test_builtin_always_wins_over_a_toplevel_collision(home, tmp_path, capfd):
    (tmp_path / "venv.py").write_text(
        "print('if you see this the collision guard failed')\n")
    _write_toml(tmp_path, '''
        [[command]]
        name = "venv"
        script = "venv.py"
        toplevel = true
    ''')

    code = cli.main(["venv"])
    out = capfd.readouterr().out
    # The REAL `seed venv` (no name given) prints its own usage --
    # never the custom script's output.
    assert "collision guard failed" not in out
    assert "Usage: seed venv" in out
    assert code == 1

    # The custom entry is still reachable via the namespaced form.
    code = cli.main(["custom", "venv"])
    assert code == 0
    assert "collision guard failed" in capfd.readouterr().out


# --- help_rows / toplevel_map -------------------------------------------

def test_help_rows_reflects_run_and_script_entries(home, tmp_path):
    (tmp_path / "greet.py").write_text("print('hi')\n")
    _write_toml(tmp_path, '''
        [[command]]
        name = "lint"
        run = ["x"]
        description = "Lint it"

        [[command]]
        name = "greet"
        script = "greet.py"
        description = "Say hi"
        toplevel = true
    ''')

    rows = {name: (hint, desc) for name, hint, desc in custom_cmd.help_rows()}
    assert rows["custom lint"] == ("[args...]", "Lint it")
    assert "(also: seed greet)" in rows["custom greet"][1]


def test_help_group_omitted_when_nothing_configured(run_cli, home):
    _code, out = run_cli("help")
    assert "Custom commands" not in out


def test_help_group_shown_when_configured(run_cli, home, tmp_path):
    _write_toml(tmp_path, '[[command]]\nname = "lint"\nrun = ["x"]\n')
    _code, out = run_cli("help")
    assert "Custom commands -- defined by your organization" in out
    assert "custom lint" in out


# --- known_names (used by `seed config set startup_commands`) ----------

def test_known_names(home, tmp_path):
    assert custom_cmd.known_names() == set()
    (tmp_path / "greet.py").write_text("print('hi')\n")
    _write_toml(tmp_path, '''
        [[command]]
        name = "lint"
        run = ["x"]

        [[command]]
        name = "greet"
        script = "greet.py"
    ''')
    assert custom_cmd.known_names() == {"lint", "greet"}


def test_known_names_never_raises_on_bad_toml(home, tmp_path):
    _write_toml(tmp_path, "not valid toml [[[")
    assert custom_cmd.known_names() == set()


# --- run_startup (the `seed custom --startup` fast path) ----------------
# Collapses N seed-cli spawns (one per configured startup_commands name)
# into one process that loops internally -- see custom_cmd.run_startup().

def test_run_startup_runs_every_configured_name_in_order(home, tmp_path, capfd):
    (tmp_path / "one.py").write_text("print('one')\n")
    (tmp_path / "two.py").write_text("print('two')\n")
    _write_toml(tmp_path, '''
        [[command]]
        name = "one"
        script = "one.py"

        [[command]]
        name = "two"
        script = "two.py"
    ''')
    config.set_value("startup_commands", ["one", "two"])
    code = custom_cmd.run_startup()
    assert code == 0
    assert capfd.readouterr().out.splitlines() == ["one", "two"]


def test_run_startup_is_a_noop_when_unconfigured(home):
    assert config.get("startup_commands") == []
    assert custom_cmd.run_startup() == 0


def test_run_startup_warns_and_continues_past_a_failure(home, tmp_path, capfd):
    (tmp_path / "boom.py").write_text("import sys; sys.exit(7)\n")
    (tmp_path / "after.py").write_text("print('still ran')\n")
    _write_toml(tmp_path, '''
        [[command]]
        name = "boom"
        script = "boom.py"

        [[command]]
        name = "after"
        script = "after.py"
    ''')
    config.set_value("startup_commands", ["boom", "after"])
    code = custom_cmd.run_startup()
    assert code == 0  # a startup routine must never block the shell
    out = capfd.readouterr().out
    assert "startup command 'boom' failed (exit 7)" in out
    assert "still ran" in out


def test_run_startup_warns_and_continues_past_an_unknown_name(home, tmp_path, capfd):
    (tmp_path / "after.py").write_text("print('still ran')\n")
    _write_toml(tmp_path, '[[command]]\nname = "after"\nscript = "after.py"\n')
    config.set_value("startup_commands", ["ghost", "after"])
    code = custom_cmd.run_startup()
    assert code == 0
    out = capfd.readouterr().out
    assert "startup command 'ghost' not found" in out
    assert "still ran" in out


def test_custom_dash_dash_startup_flag_dispatches_through_the_cli(
        home, tmp_path, capfd):
    """The end-to-end path the shell hook actually invokes:
    `seed custom --startup`."""
    (tmp_path / "one.py").write_text("print('from cli')\n")
    _write_toml(tmp_path, '[[command]]\nname = "one"\nscript = "one.py"\n')
    config.set_value("startup_commands", ["one"])
    code = cli.main(["custom", "--startup"])
    assert code == 0
    assert capfd.readouterr().out.strip() == "from cli"
