"""The PyPI application family (`seed app-*`) and the Spyder editor built on
top of it. Nothing here downloads: the pieces that would (uv tool install)
are stubbed, and everything else works off a faked app environment."""

from __future__ import annotations

import configparser

from seedling import paths
# vscode_cmd imported for its registration side effect: editors are
# registered at import, and this file asserts on the full family.
from seedling.commands import app_cmd, editors, spyder_cmd, vscode_cmd  # noqa: F401


def _fake_app(home, name, version="1.0", kernels=None):
    """An installed application, in the layout uv leaves behind: a venv under
    the tool root with dist-info metadata inside it."""
    site = home / "extensions" / "apps" / name / "Lib" / "site-packages"
    site.mkdir(parents=True)
    (site / f"{name}-{version}.dist-info").mkdir()
    if kernels:
        (site / f"spyder_kernels-{kernels}.dist-info").mkdir()
    return home / "extensions" / "apps" / name


def test_spec_name_strips_every_pin_form():
    for spec, expected in [
        ("spyder", "spyder"), ("spyder==6.1.5", "spyder"),
        ("spyder>=6", "spyder"), ("spyder~=6.1", "spyder"),
        ("spyder[all]", "spyder"), ("jupyterlab != 4", "jupyterlab"),
    ]:
        assert app_cmd._spec_name(spec) == expected


def test_installed_apps_reads_the_tool_root(home):
    assert app_cmd.installed_apps() == []
    _fake_app(home, "spyder", "6.1.5")
    _fake_app(home, "cowsay", "6.1")
    assert app_cmd.installed_apps() == ["cowsay", "spyder"]
    assert app_cmd.is_installed("spyder")
    assert not app_cmd.is_installed("nope")


def test_app_version_read_from_dist_info(home):
    _fake_app(home, "spyder", "6.1.5")
    assert app_cmd.app_version("spyder") == "6.1.5"
    assert app_cmd.app_version("absent") is None


def test_app_tool_root_is_separate_from_seed_cli():
    """seed-cli lives in system/tool. If apps shared that root, `uv tool
    list` would report the running CLI as an app and `uv tool upgrade --all`
    would sweep it."""
    from seedling import uv_tool

    app_env = uv_tool.app_install_env()
    cli_env = uv_tool.tool_install_env()
    assert app_env["UV_TOOL_DIR"] != cli_env["UV_TOOL_DIR"]
    assert app_env["UV_TOOL_BIN_DIR"] != cli_env["UV_TOOL_BIN_DIR"]


def test_app_shims_dir_is_outside_the_tool_root():
    """uv reads every child of UV_TOOL_DIR as a tool; a bin/ directory inside
    it gets reported as malformed."""
    assert paths.APP_SHIMS_DIR.parent != paths.APPS_DIR
    assert paths.APPS_DIR not in paths.APP_SHIMS_DIR.parents


def test_spyder_config_dir_is_outside_the_tool_root(home):
    """Same trap: Spyder's config must not look like an installed app."""
    assert paths.APPS_DIR not in paths.SPYDER_CONFIG_DIR.parents


def test_kernels_requirement_pins_the_minor_series(home):
    """The venv needs a spyder-kernels compatible with Spyder's own, and the
    compatibility unit is the minor series -- read, never hardcoded, so it
    can't drift when Spyder is upgraded."""
    _fake_app(home, "spyder", "6.1.5", kernels="3.1.5")
    assert spyder_cmd._kernels_version() == "3.1.5"
    assert spyder_cmd._kernels_requirement() == "spyder-kernels==3.1.*"


def test_kernels_requirement_absent_when_not_installed(home):
    _fake_app(home, "spyder", "6.1.5")  # no kernels dist-info
    assert spyder_cmd._kernels_requirement() is None


def test_write_config_points_spyder_at_the_interpreter(home):
    spyder_cmd._write_config(r"C:\seedling\python\venvs\dev\Scripts\python.exe")
    ini = paths.SPYDER_CONFIG_DIR / "spyder.ini"
    assert ini.exists()

    parsed = configparser.ConfigParser()
    parsed.read(ini, encoding="utf-8")
    section = parsed["main_interpreter"]
    # default=False + custom=True is what makes Spyder use the custom path
    # rather than the interpreter it is itself running on.
    assert section["default"] == "False"
    assert section["custom"] == "True"
    assert "venvs\\dev" in section["custom_interpreter"]


def test_write_config_preserves_existing_settings(home):
    """spyder.ini is Spyder's live config once it has run. Rewriting it from
    scratch on every `seed spyder` would throw away the user's settings."""
    paths.SPYDER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ini = paths.SPYDER_CONFIG_DIR / "spyder.ini"
    ini.write_text("[editor]\nwrap = True\n\n"
                   "[main_interpreter]\ncustom_interpreter = 'old'\n",
                   encoding="utf-8")

    spyder_cmd._write_config("/new/python")

    parsed = configparser.ConfigParser()
    parsed.read(ini, encoding="utf-8")
    assert parsed["editor"]["wrap"] == "True"          # untouched
    assert "new" in parsed["main_interpreter"]["custom_interpreter"]


def test_arm_is_refused_with_the_conda_fallback(home, monkeypatch, capsys):
    """PyQt5's Qt wheels are x86_64-only, so this must fail with a readable
    instruction rather than an unresolvable-dependency error from uv."""
    monkeypatch.setattr(spyder_cmd.platform, "machine", lambda: "arm64")
    def boom(*a, **k):
        raise AssertionError("attempted an install that cannot resolve")
    monkeypatch.setattr(app_cmd, "ensure_installed", boom)

    assert spyder_cmd._prepare(object()) is False
    assert "seed tool-install spyder" in capsys.readouterr().out


def test_both_editors_are_registered_in_the_family():
    keys = set(editors.REGISTRY)
    assert {"vscode", "spyder"} <= keys
    rows = {row[0] for row in editors.help_rows()}
    assert {"vscode", "repo-vscode", "spyder", "repo-spyder"} <= rows


def test_help_rows_mark_what_is_installed(home):
    _fake_app(home, "spyder", "6.1.5")
    rows = {name: desc for name, _hint, desc in editors.help_rows()}
    assert "(installed)" in rows["spyder"]
    assert "~300 MB download" in rows["vscode"]   # not installed here
