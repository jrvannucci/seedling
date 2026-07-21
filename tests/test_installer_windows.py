"""End-to-end runs of the PowerShell installer (installers/install.ps1),
executed -- not merely syntax-checked -- with a compiled stub uv.exe so no
network or real build is needed.

The POSIX installer is covered by test_installer_offline.py; this is the
Windows counterpart, focused on the branches whose logic lives only in
install.ps1: settings seeding, the deployment-profile handling (conf vs the
SEEDLING_PROFILE env var, and its fatal-vs-fallback split), and the $PROFILE
hook write.

Every run targets a throwaway SEEDLING_HOME and a FAKE $PROFILE, so nothing
touches the real user profile. Skipped off Windows or where the stub uv.exe
can't be compiled.
"""

from __future__ import annotations

import json

import pytest

from conftest import (
    make_repo_copy,
    needs_ps_installer,
    plant_stub_uv_windows,
    run_powershell_install,
)

pytestmark = needs_ps_installer


@pytest.fixture
def ps_install_env(tmp_path):
    """A repo copy + throwaway home with the stub uv.exe planted, plus a fake
    $PROFILE under tmp. Returns a runner and the paths to assert on."""
    copy = make_repo_copy(tmp_path / "copy")
    home = tmp_path / "home" / "seedling"
    plant_stub_uv_windows(home)
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    fake_profile = profile_dir / "Microsoft.PowerShell_profile.ps1"

    def run(env_extra: dict | None = None):
        return run_powershell_install(copy, home, fake_profile, env_extra)

    return copy, home, fake_profile, run


def _calls(home):
    log = home / "system" / "bin" / "calls.log"
    return log.read_text() if log.exists() else ""


def _settings(home):
    f = home / "system" / "config" / "settings.json"
    return json.loads(f.read_text(encoding="utf-8-sig")) if f.exists() else None


def _write_conf(copy, **overrides):
    conf = copy / "seedling.conf"
    text = conf.read_text(encoding="utf-8")
    import re
    for key, value in overrides.items():
        # A function replacement, so backslashes in a Windows path value
        # (S:\share -> \s) aren't parsed as regex-replacement escapes.
        text = re.sub(rf'^{key}="[^"]*"', lambda m, v=value: f'{key}="{v}"',
                      text, flags=re.M)
    conf.write_text(text, encoding="utf-8")


# --- the harness itself works (smoke) --------------------------------------

def test_installer_runs_and_writes_the_hook_to_the_fake_profile(ps_install_env):
    """Proves the whole apparatus: install.ps1 executes to completion, and
    the $PROFILE override redirects the hook write away from the real user
    profile."""
    copy, home, fake_profile, run = ps_install_env
    result = run({"SEEDLING_AUTO_SETUP": "false"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / "system" / "shell" / "seed.ps1").is_file()
    assert fake_profile.is_file(), "the fake profile should have been written"
    assert "seed.ps1" in fake_profile.read_text(encoding="utf-8")


def test_reinstall_does_not_stack_hook_lines(ps_install_env):
    copy, home, fake_profile, run = ps_install_env
    run({"SEEDLING_AUTO_SETUP": "false"})
    run({"SEEDLING_AUTO_SETUP": "false"})
    text = fake_profile.read_text(encoding="utf-8")
    assert text.count("seed.ps1") == 1


# --- auto-setup / default environment --------------------------------------

def test_auto_setup_runs_the_expected_cli_sequence(ps_install_env):
    copy, home, fake_profile, run = ps_install_env
    result = run({"SEEDLING_AUTO_VSCODE": "false"})
    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(home)
    assert "seed-cli python" in calls
    assert "seed-cli venv dev" in calls
    assert "seed-cli config set default_venv dev" in calls


# --- settings seeding (install.ps1's own JSON writer) ----------------------

def test_offline_conf_is_seeded_into_settings(ps_install_env):
    copy, home, fake_profile, run = ps_install_env
    _write_conf(copy,
                SEEDLING_PACKAGE_INDEX=r"S:\share\wheels",
                SEEDLING_VSCODE_FLAVOR="vscodium",
                SEEDLING_AUTO_SETUP="false")
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    settings = _settings(home)
    assert settings["package_index"] == r"S:\share\wheels"
    assert settings["vscode_flavor"] == "vscodium"


# --- deployment profiles (the freshest, most intricate PS logic) -----------

def _profile(copy, body):
    (copy / "seedling-profile.toml").write_text(body, encoding="utf-8")


def test_conf_profile_is_applied_and_replaces_dev_venv(ps_install_env):
    copy, home, fake_profile, run = ps_install_env
    _profile(copy, '[[venv]]\nname = "team"\ndefault = true\n')
    _write_conf(copy, SEEDLING_PROFILE="seedling-profile.toml",
                SEEDLING_AUTO_VSCODE="false")
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(home)
    assert "seed-cli apply" in calls
    assert "seed-cli venv dev" not in calls
    assert _settings(home)["profile"].endswith("seedling-profile.toml")


def test_env_var_lets_a_user_supply_their_own_profile(ps_install_env, tmp_path):
    """The one-liner path: no conf edit, profile named by env var, copied into
    the seedling home so `seed apply` keeps working afterward."""
    copy, home, fake_profile, run = ps_install_env
    mine = tmp_path / "mine.toml"
    mine.write_text('[[venv]]\nname = "mine"\n', encoding="utf-8")
    result = run({"SEEDLING_PROFILE": str(mine), "SEEDLING_AUTO_VSCODE": "false"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "seed-cli apply" in _calls(home)
    copied = home / "system" / "config" / "profile.toml"
    assert copied.is_file() and "mine" in copied.read_text(encoding="utf-8")
    assert _settings(home)["profile"].endswith("profile.toml")


def test_env_var_beats_the_conf(ps_install_env, tmp_path):
    copy, home, fake_profile, run = ps_install_env
    (copy / "seedling-profile.toml").write_text(
        '[[venv]]\nname = "fromconf"\n', encoding="utf-8")
    _write_conf(copy, SEEDLING_PROFILE="seedling-profile.toml")
    mine = tmp_path / "mine.toml"
    mine.write_text('[[venv]]\nname = "fromenv"\n', encoding="utf-8")
    run({"SEEDLING_PROFILE": str(mine), "SEEDLING_AUTO_VSCODE": "false"})
    copied = (home / "system" / "config" / "profile.toml").read_text(encoding="utf-8")
    assert "fromenv" in copied and "fromconf" not in copied


def test_a_missing_env_profile_is_fatal(ps_install_env, tmp_path):
    """Deliberately unlike the conf case: a user who named a profile and
    silently got the default environment wouldn't notice until something was
    missing, so the install stops instead."""
    copy, home, fake_profile, run = ps_install_env
    result = run({"SEEDLING_PROFILE": str(tmp_path / "ghost.toml")})
    assert result.returncode != 0
    assert "no file exists at" in (result.stdout + result.stderr)


def test_a_missing_conf_profile_falls_back(ps_install_env):
    """A conf naming a profile that wasn't distributed must not brick the
    install -- it warns and does the normal setup."""
    copy, home, fake_profile, run = ps_install_env
    _write_conf(copy, SEEDLING_PROFILE="nope.toml", SEEDLING_AUTO_VSCODE="false")
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "falling back to the default setup" in result.stdout
    assert "profile" not in (_settings(home) or {})
    assert "seed-cli venv dev" in _calls(home)
