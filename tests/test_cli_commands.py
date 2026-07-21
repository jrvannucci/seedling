"""CLI-level behavior of the non-destructive commands: help layout,
dispatch completeness, list/empty states, venv-default, config, status,
summary, python-cmd helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import REPO_ROOT, make_base_python, make_venv_dirs
from seedling import config, paths
from seedling.commands import python_cmd

ALL_COMMANDS = [
    "python", "python-list", "remove-python",
    "venv", "venv-list", "remove-venv", "remove-venv-all", "venv-default",
    "auto-activate",
    "activate", "deactivate", "install", "uninstall", "package-list",
    "download-whl", "download-requirements",
    "repo-clone", "repo-list", "repo-cd", "repo-vscode", "repo-open",
    "repo-install", "remove-repo",
    "vscode", "summary", "health-check", "logs-viewer", "config", "where",
    "apply", "kill-processes", "update-commands", "remove-user", "purge",
    "purge-and-reinstall",
]

# handled specially in _dispatch_main rather than via the dispatch table
_NON_DISPATCH = {"where", "help"}

ADMIN_COMMANDS = [
    "admin-purge-all-users", "admin-remove-user", "admin-remove-venv",
    "admin-remove-venv-all", "admin-remove-python", "admin-remove-repo",
]


def test_every_command_is_dispatchable(home):
    """Guards against a rename touching the parser but not the dispatch
    table (or vice versa) -- admin family included."""
    from seedling import cli
    parser = cli.build_parser()
    subparsers = next(
        a for a in parser._actions
        if a.__class__.__name__ == "_SubParsersAction")
    parser_names = set(subparsers.choices)
    assert parser_names == set(ALL_COMMANDS) | set(ADMIN_COMMANDS) | _NON_DISPATCH


class TestPassthroughForwarding:
    """install/uninstall/package-list forward everything after the verb to uv
    verbatim -- including a LEADING option-like token (`install -e .`), which
    argparse.REMAINDER used to reject with 'unrecognized arguments: -e'."""

    @pytest.fixture
    def uv_args(self, monkeypatch):
        from seedling import uv_tool
        calls: list[list[str]] = []
        monkeypatch.setattr(uv_tool, "run", lambda a, **k: calls.append(list(a)))
        return calls

    def test_install_editable_leading_flag(self, run_cli, uv_args):
        code, out = run_cli("install", "-e", ".")
        assert code == 0
        assert uv_args == [["pip", "install", "-e", "."]]

    def test_install_mixed_flags_and_packages(self, run_cli, uv_args):
        code, out = run_cli("install", "-U", "requests", "pillow")
        assert code == 0
        assert uv_args == [["pip", "install", "-U", "requests", "pillow"]]

    def test_uninstall_forwards_flags(self, run_cli, uv_args):
        code, out = run_cli("uninstall", "-y", "requests")
        assert code == 0
        assert uv_args == [["pip", "uninstall", "-y", "requests"]]

    def test_package_list_leading_flag(self, run_cli, uv_args):
        code, out = run_cli("package-list", "--outdated")
        assert code == 0
        assert uv_args == [["pip", "list", "--outdated"]]

    def test_install_empty_still_shows_usage(self, run_cli, uv_args):
        code, out = run_cli("install")
        assert code == 1
        assert "Usage: seed install" in out
        assert not uv_args

    def test_install_help_flag_shows_argparse_help(self, run_cli, uv_args):
        code, out = run_cli("install", "-h")
        assert "usage: seed install" in out
        assert not uv_args  # -h never reaches uv


def test_bare_seed_shows_grouped_help(run_cli):
    code, out = run_cli()
    assert code == 0
    for family_member in ("python-list", "remove-venv-all", "repo-clone",
                          "repo-vscode", "venv-default", "package-list"):
        assert family_member in out


def test_help_hides_admin_note_on_single_user(run_cli, home):
    from seedling import config
    assert config.is_multi_user() is False
    code, out = run_cli("help")
    assert "multi-user" not in out  # no admin note on a plain install
    assert "admin-" not in out


def test_help_shows_admin_note_only_when_multi_user(run_cli, home):
    from seedling import config
    config.set_value("shared_root", r"C:\seedling")   # valid JSON via json.dumps
    assert config.is_multi_user() is True
    code, out = run_cli("help")
    assert "shared multi-user install" in out
    assert "seed help --admin" in out


def test_summary_shows_install_type(run_cli, home):
    from seedling import config
    code, out = run_cli("summary")
    assert "install type: single-user" in out
    config.set_value("shared_root", r"C:\seedling")
    code, out = run_cli("summary")
    assert "install type: multi-user" in out and r"C:\seedling" in out


def test_is_multi_user_ignores_corrupt_settings(home):
    from seedling import config
    paths.ensure_layout()
    paths.CONFIG_FILE.write_text("{ broken json")
    assert config.is_multi_user() is False  # never raises


def test_unknown_command_exits_nonzero(run_cli):
    code, out = run_cli("frobnicate")
    assert code == 2  # argparse usage error


def test_where(run_cli, home):
    code, out = run_cli("where")
    assert code == 0
    assert str(home) in out


# --- version reporting -------------------------------------------------------

@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_version_flag(run_cli, flag):
    """Both spellings print the running version and exit cleanly. (-V survives
    the PowerShell `seed` wrapper because it's a simple function -- no
    parameter binding -- so it can't be eaten as a -Verbose prefix.)"""
    import seedling
    code, out = run_cli(flag)
    assert code == 0
    assert out.strip() == f"seedling {seedling.__version__}"


def test_version_matches_the_packaged_metadata():
    """__init__.py is the single source of truth: pyproject must stay dynamic,
    or the two drift and `seed --version` starts lying about what's installed."""
    import re
    pyproject = (REPO_ROOT / "src" / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert '[tool.hatch.version]' in pyproject
    assert 'path = "seedling/__init__.py"' in pyproject
    # no competing hardcoded version = ... line in [project]
    assert not re.search(r'^version\s*=', pyproject, flags=re.M)


def test_grouped_help_reports_the_version(run_cli):
    import seedling
    code, out = run_cli("help")
    assert code == 0
    assert f"seedling {seedling.__version__}" in out


def test_empty_state_messages(run_cli):
    for cmd, expected in [
        ("python-list", "No base Python interpreters installed yet"),
        ("venv-list", "No venvs created yet"),
        ("repo-list", "No repos cloned yet"),
    ]:
        code, out = run_cli(cmd)
        assert code == 0
        assert expected in out


def test_python_list_shows_alias_and_default(run_cli, home):
    make_base_python(home, "312", "cpython-3.12.5-windows-x86_64-none")
    config.set_default_base("312")
    code, out = run_cli("python-list")
    assert code == 0
    assert "312" in out and "cpython-3.12.5" in out and "default" in out


def test_venv_list_marks_auto_activated(run_cli, home):
    make_venv_dirs(home, "dev", "other")
    config.set_value("default_venv", "dev")
    code, out = run_cli("venv-list")
    assert "dev" in out and "auto-activated in new shells" in out


def test_venv_default_show_set_and_missing(run_cli, home):
    code, out = run_cli("venv-default")
    assert code == 0 and "No default venv is set" in out
    code, out = run_cli("venv-default", "ghost")
    assert code == 1 and "No venv named 'ghost'" in out
    make_venv_dirs(home, "dev")
    code, out = run_cli("venv-default", "dev")
    assert code == 0
    assert config.get("default_venv") == "dev"
    code, out = run_cli("venv-default")
    assert "dev" in out


def test_config_show_get_set_unset(run_cli, home):
    code, out = run_cli("config")
    assert code == 0 and "update_source" in out and "package_index" in out
    code, out = run_cli("config", "set", "venv_default_packages", "a, b ,c")
    assert code == 0
    assert config.get("venv_default_packages") == ["a", "b", "c"]
    code, out = run_cli("config", "get", "venv_default_packages")
    assert out.strip().endswith("a,b,c")
    code, out = run_cli("config", "unset", "venv_default_packages")
    assert config.get("venv_default_packages") == ["ipython", "ruff", "ipykernel"]
    code, out = run_cli("config", "set", "bogus_key", "x")
    assert code == 1 and "Unknown key" in out


def test_auto_activate_toggles_and_shows(run_cli, home):
    # Default is on.
    assert config.get("auto_activate") is True
    code, out = run_cli("auto-activate")
    assert code == 0 and "ON" in out

    code, out = run_cli("auto-activate", "False")
    assert code == 0
    assert config.get("auto_activate") is False        # a real bool, not "False"
    code, out = run_cli("auto-activate")
    assert "OFF" in out

    code, out = run_cli("auto-activate", "true")        # case-insensitive
    assert code == 0 and config.get("auto_activate") is True


def test_auto_activate_rejects_non_boolean(run_cli, home):
    code, out = run_cli("auto-activate", "maybe")
    assert code == 1
    assert "expected True or False" in out
    # An invalid value must not change the stored setting.
    assert config.get("auto_activate") is True


def test_auto_activate_is_independent_of_default_venv(run_cli, home):
    """Turning auto-activation off leaves the default venv set -- the two are
    separate settings."""
    make_venv_dirs(home, "dev")
    run_cli("venv-default", "dev")
    run_cli("auto-activate", "False")
    assert config.get("default_venv") == "dev"
    assert config.get("auto_activate") is False


def test_config_native_tls_stores_real_bool(run_cli, home):
    run_cli("config", "set", "native_tls", "false")
    assert config.get("native_tls") is False
    run_cli("config", "set", "native_tls", "true")
    assert config.get("native_tls") is True
    run_cli("config", "set", "native_tls", "FALSE")  # case-insensitive
    assert config.get("native_tls") is False


def test_config_get_unset_prints_nothing(run_cli, home):
    code, out = run_cli("config", "get", "default_venv")
    assert code == 0 and out.strip() == ""


def test_summary_lists_sections_and_settings(run_cli, home):
    make_base_python(home, "312", "cpython-3.12.5-windows-x86_64-none")
    make_venv_dirs(home, "dev")
    code, out = run_cli("summary")
    assert code == 0
    for token in ("Tooling", "Base Pythons", "Venvs", "Repos", "Settings",
                  "312", "dev"):
        assert token in out, token


def test_summary_json_reports_paths_and_schema(run_cli, home):
    import json as _json

    make_base_python(home, "312", "cpython-3.12.5-windows-x86_64-none")
    make_venv_dirs(home, "dev")
    code, out = run_cli("summary", "--json")
    assert code == 0
    data = _json.loads(out)

    assert data["schema"] == 1
    assert data["installed"] is True
    assert data["install_type"] == "single-user"

    py = next(p for p in data["pythons"] if p["tag"] == "312")
    assert py["present"] is True
    assert py["target"] == "cpython-3.12.5-windows-x86_64-none"

    venv = next(v for v in data["venvs"] if v["name"] == "dev")
    assert venv["python_version"] == "3.12.0"
    # The whole point of the JSON: a runnable interpreter path, not a label.
    assert venv["python_executable"] and Path(venv["python_executable"]).exists()

    # Sizes are the slow part -- absent unless asked for.
    assert venv["size_bytes"] is None
    assert data["total_size_bytes"] is None


def test_summary_json_includes_sizes_when_asked(run_cli, home):
    import json as _json

    make_venv_dirs(home, "dev")
    code, out = run_cli("summary", "--json", "--sizes")
    assert code == 0
    data = _json.loads(out)
    assert data["total_size_bytes"] is not None
    assert data["venvs"][0]["size_bytes"] is not None


def test_summary_collect_when_home_absent(home):
    """Going through the CLI would create the home dir, so drive collect()
    directly to cover the not-installed-yet shape."""
    from seedling.commands import summary_cmd

    assert not home.exists()
    data = summary_cmd.collect()
    assert data["installed"] is False
    assert data["schema"] == 1
    assert "venvs" not in data


# --- python_cmd helpers -----------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("312", ("312", "3.12")),
    ("3.12", ("312", "3.12")),
    ("3.12.4", ("3124", "3.12.4")),
])
def test_normalize_tag(raw, expected):
    assert python_cmd._normalize_tag(raw) == expected


def test_newest_installed_dir_picks_highest_version(home):
    make_base_python(home, "312", "cpython-3.12.5-windows-x86_64-none")
    make_base_python(home, "313", "cpython-3.13.2-windows-x86_64-none")
    make_base_python(home, "39", "cpython-3.9.19-windows-x86_64-none")
    newest = python_cmd._newest_installed_dir()
    assert newest.name.startswith("cpython-3.13.2")


def test_resolve_base_via_alias_and_direct(home):
    target = make_base_python(home, "312", "cpython-3.12.5-windows-x86_64-none")
    assert python_cmd.resolve_base("312") == target
    assert python_cmd.resolve_base("999") is None
