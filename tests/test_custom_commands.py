"""custom-commands.toml: parsing/validation (seedling/custom_commands.py).

Mirrors test_profile.py's style -- validation is where most of the value is,
since a typo here is discovered by users one command at a time. Every
command is exactly one of `run` (a fixed argv) or `script` (a .py/.sh/.ps1
file, resolved relative to the TOML file's own directory) -- there is no
second, directory-scanned source anymore.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from seedling import custom_commands as cc


# --- parsing -----------------------------------------------------------

def test_minimal_file():
    assert cc.parse("") == []


def test_full_round_trips():
    commands = cc.parse('''
        [[command]]
        name = "lint"
        run = ["ruff", "check", "."]
        description = "Lint the current project"
        venv = "dev"

        [[command]]
        name = "hello"
        run = ["echo", "hi"]
        toplevel = true

        [[command]]
        name = "quote"
        script = "scripts/quote.py"
        description = "Print a random quote"
    ''')
    assert [c.name for c in commands] == ["lint", "hello", "quote"]
    lint, hello, quote = commands
    assert lint.run == ["ruff", "check", "."]
    assert lint.script is None
    assert lint.description == "Lint the current project"
    assert lint.venv == "dev"
    assert lint.toplevel is False
    assert hello.toplevel is True
    assert hello.venv is None
    assert hello.description == ""
    assert quote.run is None
    assert quote.script == Path("scripts/quote.py")
    assert quote.description == "Print a random quote"


def test_whitespace_is_stripped():
    commands = cc.parse('[[command]]\nname = "  lint  "\nrun = ["x"]\n'
                         'venv = " dev "')
    assert commands[0].name == "lint"
    assert commands[0].venv == "dev"


# --- script path resolution ---------------------------------------------

def test_script_resolves_relative_to_the_toml_files_own_directory():
    toml_path = Path("/org/deploy/custom-commands.toml")
    commands = cc.parse(
        '[[command]]\nname = "quote"\nscript = "scripts/quote.py"\n',
        path=toml_path)
    assert commands[0].script == Path("/org/deploy/scripts/quote.py")


def test_absolute_script_path_is_left_alone():
    toml_path = Path("/org/deploy/custom-commands.toml")
    commands = cc.parse(
        '[[command]]\nname = "quote"\nscript = "/elsewhere/quote.py"\n',
        path=toml_path)
    assert commands[0].script == Path("/elsewhere/quote.py")


def test_script_stays_relative_when_no_path_given():
    """parse()ing a raw string with no `path` (e.g. a unit test that never
    dispatches the command) leaves a relative script path as-is rather than
    raising -- there's nothing to resolve it against."""
    commands = cc.parse('[[command]]\nname = "quote"\nscript = "quote.py"\n')
    assert commands[0].script == Path("quote.py")


@pytest.mark.parametrize("text,fragment", [
    ("this is not toml {{{", "not valid TOML"),
    ("command = 'nope'", "must be a list of tables"),
    ('[[command]]\nrun = ["x"]', "non-empty name"),
    ('[[command]]\nname = ""\nrun = ["x"]', "non-empty name"),
    ('[[command]]\nname = "bad name!"\nrun = ["x"]', "letters, digits"),
    ('[[command]]\nname="a"\nrun=["x"]\n[[command]]\nname="a"\nrun=["y"]',
     "duplicate command name"),
    ('[[command]]\nname = "a"', "needs either run or script"),
    ('[[command]]\nname = "a"\nrun = ["x"]\nscript = "x.py"',
     "mutually exclusive"),
    ('[[command]]\nname = "a"\nrun = []', "non-empty list of strings"),
    ('[[command]]\nname = "a"\nrun = "x"', "non-empty list of strings"),
    ('[[command]]\nname = "a"\nrun = [""]', "non-empty string"),
    ('[[command]]\nname = "a"\nrun = ["x"]\ndescription = 3',
     "description must be a string"),
    ('[[command]]\nname = "a"\nrun = ["x"]\nvenv = ""',
     "venv must be a non-empty string"),
    ('[[command]]\nname = "a"\nrun = ["x"]\ntoplevel = "yes"',
     "must be true or false"),
    ('[[command]]\nname = "a"\nscript = ""', "non-empty string"),
    ('[[command]]\nname = "a"\nscript = "helper.exe"',
     "must end with .py/.sh/.ps1"),
    ('[[command]]\nname = "a"\nscript = "quote.py"\nvenv = "dev"',
     "venv only applies to run"),
])
def test_invalid_files_are_rejected(text, fragment):
    with pytest.raises(cc.CustomCommandsError) as e:
        cc.parse(text)
    assert fragment in str(e.value)


# --- resolve_path / load ------------------------------------------------

def test_resolve_path_none_when_unset(home):
    assert cc.resolve_path() is None
    assert cc.load() == []


def test_load_reads_configured_file(home, tmp_path):
    from seedling import config
    toml = tmp_path / "commands.toml"
    toml.write_text('[[command]]\nname = "lint"\nrun = ["ruff"]\n')
    config.set_value("custom_commands", str(toml))
    commands = cc.load()
    assert [c.name for c in commands] == ["lint"]


def test_load_resolves_script_relative_to_the_configured_file(home, tmp_path):
    from seedling import config
    toml = tmp_path / "commands.toml"
    toml.write_text('[[command]]\nname = "quote"\nscript = "quote.py"\n')
    config.set_value("custom_commands", str(toml))
    commands = cc.load()
    assert commands[0].script == tmp_path / "quote.py"


def test_load_returns_none_on_bad_file(home, tmp_path):
    from seedling import config
    toml = tmp_path / "commands.toml"
    toml.write_text("not toml {{{")
    config.set_value("custom_commands", str(toml))
    assert cc.load() is None
    with pytest.raises(cc.CustomCommandsError):
        cc.load_or_raise()


def test_load_returns_none_on_missing_file(home, tmp_path):
    from seedling import config
    config.set_value("custom_commands", str(tmp_path / "nope.toml"))
    assert cc.load() is None
