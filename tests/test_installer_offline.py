"""End-to-end installer runs (POSIX installer under bash, dispatched
through the polyglot install.cmd) with a stub uv -- the full OFFLINE
deployment story: conf-driven sources, settings seeding, vendor/ payloads,
CA bundles, auto-setup, hook management. No network is touched anywhere.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_repo_copy, needs_bash, plant_stub_uv, run_bash
from seedling import PUBLIC_REPO

pytestmark = needs_bash

PUBLIC_URL = PUBLIC_REPO


@pytest.fixture
def install_env(tmp_path, monkeypatch):
    """A repo copy + fake HOME with a stub uv pre-planted. Returns a runner
    that executes `sh ./install.cmd` (the polyglot entry point) and paths
    for assertions. The environment is scrubbed of SEEDLING_*/UV_*/SSL_*
    so a stray or leaked var (e.g. UV_NATIVE_TLS set by another test's
    config.apply_runtime_env) can't pollute the installer subprocess."""
    import conftest
    for var in conftest._ISOLATED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    copy = make_repo_copy(tmp_path / "copy")
    fake_home = tmp_path / "home"
    seedling_home = fake_home / "seedling"
    fake_home.mkdir()
    plant_stub_uv(seedling_home)

    def run_install(env_extra: str = ""):
        script = (
            f"cd '{copy.as_posix()}' && "
            f"HOME='{fake_home.as_posix()}' SHELL=/bin/bash {env_extra} "
            f"sh ./install.cmd"
        )
        return run_bash(script)

    return copy, fake_home, seedling_home, run_install


def _calls(seedling_home):
    log = seedling_home / "system" / "bin" / "calls.log"
    return log.read_text() if log.exists() else ""


def _settings(seedling_home):
    f = seedling_home / "system" / "config" / "settings.json"
    return json.loads(f.read_text()) if f.exists() else None


def _write_conf(copy, **overrides):
    """Rewrite global.conf values in the repo copy."""
    conf = copy / "global.conf"
    text = conf.read_text()
    for key, value in overrides.items():
        import re
        text = re.sub(rf'^{key}="[^"]*"', f'{key}="{value}"', text, flags=re.M)
    conf.write_text(text)


class TestDefaultInstall:
    def test_install_writes_a_captured_block_format_log(self, install_env):
        copy, fake_home, home, run_install = install_env
        result = run_install("SEEDLING_AUTO_SETUP=false")
        assert result.returncode == 0, result.stdout + result.stderr
        logs = list((home / "system" / "logs").glob("install-*.log"))
        assert len(logs) == 1, "install.sh should write exactly one install log"
        text = logs[0].read_text()
        assert text.startswith("=== [")             # block start marker
        assert "installer (bootstrap)" in text
        assert "=== " in text and "exit code 0" in text   # block exit marker
        assert "seedling is installed" in text       # captured live output
        # Plain text end to end: logs may be shipped to a server, so ANSI is
        # stripped at the source (info() always emits codes, so absence here
        # proves the strip ran).
        assert "\x1b[" not in text

    def test_pristine_conf_records_local_checkout_dir(self, install_env):
        copy, fake_home, home, run_install = install_env
        result = run_install("SEEDLING_AUTO_SETUP=false")
        assert result.returncode == 0, result.stdout + result.stderr
        # source copied, minus .git and vendor
        assert (home / "system" / "src" / "src" / "pyproject.toml").exists()
        assert not (home / "system" / "src" / ".git").exists()
        # only update_source is seeded; every other pristine value is a no-op
        settings = _settings(home)
        assert set(settings) == {"update_source"}
        # Installed from a local checkout with no override -> update_source is
        # the checkout DIRECTORY, not the public URL, so `seed update-commands`
        # re-copies from that working tree (the developer-iteration path).
        # (bash `pwd` may render it MSYS-style /c/... on Windows -- compare by
        # trailing dir name, which survives that.)
        assert settings["update_source"] != PUBLIC_URL
        assert settings["update_source"].replace("\\", "/").rstrip("/").endswith("/copy")
        # hook written and registered
        assert "seedling" in (fake_home / ".bashrc").read_text()
        assert (home / "system" / "shell" / "seed.sh").exists()

    def test_auto_setup_runs_expected_cli_sequence(self, install_env):
        copy, fake_home, home, run_install = install_env
        result = run_install()
        assert result.returncode == 0
        calls = _calls(home)
        assert "seed-cli python" in calls
        assert "seed-cli venv dev" in calls
        assert "seed-cli config set default_venv dev" in calls
        assert "seed-cli vscode --no-open" in calls

    def test_auto_setup_skips(self, install_env):
        copy, fake_home, home, run_install = install_env
        run_install("SEEDLING_AUTO_SETUP=false")
        assert "seed-cli python" not in _calls(home)
        (home / "system" / "bin" / "calls.log").unlink(missing_ok=True)
        run_install("SEEDLING_AUTO_VSCODE=false")
        calls = _calls(home)
        assert "seed-cli venv dev" in calls
        assert "vscode --no-open" not in calls

    def test_reinstall_never_stacks_hooks(self, install_env):
        copy, fake_home, home, run_install = install_env
        run_install("SEEDLING_AUTO_SETUP=false")
        run_install("SEEDLING_AUTO_SETUP=false")
        bashrc = (fake_home / ".bashrc").read_text()
        assert bashrc.count("seed.sh") == 1


class TestOrgConf:
    def test_offline_conf_seeds_settings_and_uv_env(self, install_env):
        copy, fake_home, home, run_install = install_env
        _write_conf(
            copy,
            SEEDLING_REPO_URL=r"S:\\share\\seedling",
            SEEDLING_PYTHON_MIRROR=r"S:\\share\\python-builds",
            SEEDLING_PACKAGE_INDEX=r"S:\\share\\wheels",
            SEEDLING_VENV_DEFAULT_PACKAGES="ipython,ruff,pandas",
            SEEDLING_AUTO_SETUP="false",
        )
        result = run_install()
        assert result.returncode == 0, result.stdout + result.stderr
        settings = _settings(home)
        assert settings["update_source"] == r"S:\share\seedling"
        assert settings["python_mirror"] == r"S:\share\python-builds"
        assert settings["package_index"] == r"S:\share\wheels"
        assert settings["venv_default_packages"] == ["ipython", "ruff", "pandas"]
        # the installer's own uv call saw the offline env
        uv_env = (home / "system" / "bin" / "uv-env.log").read_text()
        assert "UV_PYTHON_INSTALL_MIRROR=file:///S:/share/python-builds" in uv_env
        assert "UV_CONFIG_FILE=" in uv_env
        # and the generated uv.toml pins the wheels dir as sole flat index
        toml = (home / "system" / "config" / "uv.toml").read_text()
        assert 'url = "file:///S:/share/wheels"' in toml
        assert "default = true" in toml

    def test_native_tls_conf(self, install_env):
        copy, fake_home, home, run_install = install_env
        _write_conf(copy, SEEDLING_NATIVE_TLS="true", SEEDLING_AUTO_SETUP="false")
        run_install()
        assert _settings(home)["native_tls"] is True
        assert "UV_NATIVE_TLS=1" in (home / "system" / "bin" / "uv-env.log").read_text()

    def test_native_tls_false_is_off(self, install_env):
        copy, fake_home, home, run_install = install_env
        _write_conf(copy, SEEDLING_NATIVE_TLS="false", SEEDLING_AUTO_SETUP="false")
        run_install()
        s = _settings(home) or {}
        assert "native_tls" not in s
        env_log = home / "system" / "bin" / "uv-env.log"
        assert "UV_NATIVE_TLS" not in (env_log.read_text() if env_log.exists() else "")


class TestCustomCommandsAndStartup:
    """SEEDLING_CUSTOM_COMMANDS and SEEDLING_STARTUP_COMMANDS, wired the
    same way as SEEDLING_PROFILE (conf-sourced paths resolve against the
    copied source tree; a plain comma list becomes a JSON array, same as
    SEEDLING_VENV_DEFAULT_PACKAGES)."""

    def test_custom_commands_file_is_recorded(self, install_env):
        copy, fake_home, home, run_install = install_env
        (copy / "custom-commands.toml").write_text(
            '[[command]]\nname = "lint"\nrun = ["x"]\n', encoding="utf-8")
        _write_conf(
            copy,
            SEEDLING_CUSTOM_COMMANDS="custom-commands.toml",
            SEEDLING_AUTO_SETUP="false",
        )
        result = run_install()
        assert result.returncode == 0, result.stdout + result.stderr
        settings = _settings(home)
        assert settings["custom_commands"].endswith("custom-commands.toml")
        # Recorded against the copy inside ~/seedling, like `profile` -- so
        # it keeps working after the install share goes away.
        assert "system" in settings["custom_commands"].replace("\\", "/")

    def test_conf_sourced_script_sibling_survives_the_copy(self, install_env):
        """A `script = "..."` entry is resolved relative to wherever
        custom-commands.toml itself ends up -- proving that matters: the
        conf-sourced path lives inside the whole-repo copy install.sh
        already makes, so a sibling script file rides along for free, with
        no separate directory setting to keep in sync."""
        copy, fake_home, home, run_install = install_env
        (copy / "custom-commands.toml").write_text(
            '[[command]]\nname = "greet"\nscript = "scripts/greet.py"\n',
            encoding="utf-8")
        (copy / "scripts").mkdir()
        (copy / "scripts" / "greet.py").write_text("print('hi')\n")
        _write_conf(
            copy,
            SEEDLING_CUSTOM_COMMANDS="custom-commands.toml",
            SEEDLING_AUTO_SETUP="false",
        )
        result = run_install()
        assert result.returncode == 0, result.stdout + result.stderr
        recorded = _settings(home)["custom_commands"]
        script = Path(recorded).parent / "scripts" / "greet.py"
        assert script.is_file(), f"expected the sibling script at {script}"

    def test_env_var_sourced_script_sibling_survives_the_copy(
            self, install_env, tmp_path):
        """The env-var override (the piped one-liner path) copies the TOML
        file's WHOLE containing directory, not just the file, so a relative
        `script` entry's sibling survives here too."""
        copy, fake_home, home, run_install = install_env
        mine_dir = tmp_path / "my-commands"
        mine_dir.mkdir()
        (mine_dir / "custom-commands.toml").write_text(
            '[[command]]\nname = "greet"\nscript = "scripts/greet.py"\n',
            encoding="utf-8")
        (mine_dir / "scripts").mkdir()
        (mine_dir / "scripts" / "greet.py").write_text("print('hi')\n")
        toml_path = (mine_dir / "custom-commands.toml").as_posix()
        result = run_install(f"SEEDLING_CUSTOM_COMMANDS='{toml_path}'")
        assert result.returncode == 0, result.stdout + result.stderr
        recorded = _settings(home)["custom_commands"]
        script = Path(recorded).parent / "scripts" / "greet.py"
        assert script.is_file(), f"expected the sibling script at {script}"

    def test_startup_commands_recorded_as_a_list(self, install_env):
        copy, fake_home, home, run_install = install_env
        _write_conf(
            copy,
            SEEDLING_STARTUP_COMMANDS="check-mirror, motd",
            SEEDLING_AUTO_SETUP="false",
        )
        result = run_install()
        assert result.returncode == 0, result.stdout + result.stderr
        assert _settings(home)["startup_commands"] == ["check-mirror", "motd"]

    def test_startup_commands_absent_when_unset(self, install_env):
        copy, fake_home, home, run_install = install_env
        run_install("SEEDLING_AUTO_SETUP=false")
        assert "startup_commands" not in (_settings(home) or {})


class TestVscodeConfigDir:
    """SEEDLING_VSCODE_CONFIG_DIR, wired like SEEDLING_CUSTOM_COMMANDS_DIR
    used to be (before it was folded away): the env var names a directory
    directly, so both the env-var and conf-sourced branches copy/reference
    the whole thing, not just one file."""

    def test_conf_sourced_dir_is_recorded(self, install_env):
        copy, fake_home, home, run_install = install_env
        config_dir = copy / "vscode-config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text('{"editor.fontSize": 14}\n')
        _write_conf(
            copy,
            SEEDLING_VSCODE_CONFIG_DIR="vscode-config",
            SEEDLING_AUTO_SETUP="false",
        )
        result = run_install()
        assert result.returncode == 0, result.stdout + result.stderr
        recorded = _settings(home)["vscode_config_dir"]
        # Recorded against the copy inside ~/seedling, like `custom_commands`
        # -- so it keeps working after the install share goes away.
        assert "system" in recorded.replace("\\", "/")
        assert (Path(recorded) / "settings.json").is_file()

    def test_env_var_sourced_dir_is_copied_whole(self, install_env, tmp_path):
        """Both settings.json AND keybindings.json survive the copy -- the
        env var names the directory itself, so there's no "sibling file"
        ambiguity the way there is for SEEDLING_CUSTOM_COMMANDS (which names
        a file and infers its parent)."""
        copy, fake_home, home, run_install = install_env
        mine_dir = tmp_path / "my-vscode-config"
        mine_dir.mkdir()
        (mine_dir / "settings.json").write_text('{"editor.fontSize": 14}\n')
        (mine_dir / "keybindings.json").write_text("[]\n")
        result = run_install(f"SEEDLING_VSCODE_CONFIG_DIR='{mine_dir.as_posix()}'")
        assert result.returncode == 0, result.stdout + result.stderr
        recorded = Path(_settings(home)["vscode_config_dir"])
        assert (recorded / "settings.json").is_file()
        assert (recorded / "keybindings.json").is_file()

    def test_absent_when_unset(self, install_env):
        copy, fake_home, home, run_install = install_env
        run_install("SEEDLING_AUTO_SETUP=false")
        assert "vscode_config_dir" not in (_settings(home) or {})


class TestProfile:
    """SEEDLING_PROFILE makes the installer apply a deployment profile
    instead of the built-in single-'dev'-venv setup."""

    def _profile(self, copy, body: str):
        (copy / "profile.toml").write_text(body, encoding="utf-8")

    def test_profile_is_recorded_and_applied(self, install_env):
        copy, fake_home, home, run_install = install_env
        self._profile(copy, '[[venv]]\nname = "team"\ndefault = true\n')
        _write_conf(copy, SEEDLING_PROFILE="profile.toml")
        result = run_install()
        assert result.returncode == 0, result.stdout + result.stderr
        # Recorded against the COPY inside ~/seedling, so `seed apply` keeps
        # working after the install share goes away.
        recorded = _settings(home)["profile"]
        assert recorded.endswith("profile.toml")
        assert "system" in recorded.replace("\\", "/")
        assert "seed-cli apply" in _calls(home)

    def test_profile_replaces_the_default_dev_venv_setup(self, install_env):
        """Otherwise every machine carries a 'dev' venv the admin never
        asked for, alongside the ones the profile declares."""
        copy, fake_home, home, run_install = install_env
        self._profile(copy, '[[venv]]\nname = "team"\n')
        _write_conf(copy, SEEDLING_PROFILE="profile.toml")
        run_install()
        calls = _calls(home)
        assert "seed-cli apply" in calls
        assert "seed-cli venv dev" not in calls

    def test_a_missing_profile_falls_back_instead_of_failing(self, install_env):
        """A conf naming a profile that wasn't distributed must not brick the
        install -- it warns and does the normal setup."""
        copy, fake_home, home, run_install = install_env
        _write_conf(copy, SEEDLING_PROFILE="nope.toml")
        result = run_install()
        assert result.returncode == 0, result.stdout + result.stderr
        assert "falling back to the default setup" in result.stdout
        assert "profile" not in (_settings(home) or {})
        assert "seed-cli venv dev" in _calls(home)

    def test_no_profile_key_when_unset(self, install_env):
        copy, fake_home, home, run_install = install_env
        _write_conf(copy, SEEDLING_AUTO_SETUP="false")
        run_install()
        assert "profile" not in (_settings(home) or {})

    def test_env_var_lets_a_user_supply_their_own_profile(self, install_env, tmp_path):
        """The piped one-liner has no local conf to edit, so SEEDLING_PROFILE
        as an ENV VAR is the only way a user can point at their own file."""
        copy, fake_home, home, run_install = install_env
        mine = tmp_path / "mine.toml"
        mine.write_text('[[venv]]\nname = "mine"\ndefault = true\n', encoding="utf-8")
        result = run_install(f"SEEDLING_PROFILE='{mine.as_posix()}'")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "seed-cli apply" in _calls(home)
        assert "seed-cli venv dev" not in _calls(home)

    def test_a_user_profile_is_copied_into_the_seedling_home(self, install_env, tmp_path):
        """The original may be a temp file or a mounted share; `seed apply`
        has to keep working after that goes away."""
        copy, fake_home, home, run_install = install_env
        mine = tmp_path / "mine.toml"
        mine.write_text('[[venv]]\nname = "mine"\n', encoding="utf-8")
        run_install(f"SEEDLING_PROFILE='{mine.as_posix()}'")
        copied = home / "system" / "config" / "profile.toml"
        assert copied.is_file()
        assert "mine" in copied.read_text(encoding="utf-8")
        assert _settings(home)["profile"] == str(copied).replace("\\", "/") \
            or _settings(home)["profile"].endswith("profile.toml")

    def test_env_var_beats_the_conf(self, install_env, tmp_path):
        copy, fake_home, home, run_install = install_env
        (copy / "profile.toml").write_text(
            '[[venv]]\nname = "fromconf"\n', encoding="utf-8")
        _write_conf(copy, SEEDLING_PROFILE="profile.toml")
        mine = tmp_path / "mine.toml"
        mine.write_text('[[venv]]\nname = "fromenv"\n', encoding="utf-8")
        run_install(f"SEEDLING_PROFILE='{mine.as_posix()}'")
        copied = (home / "system" / "config" / "profile.toml").read_text(encoding="utf-8")
        assert "fromenv" in copied and "fromconf" not in copied

    def test_a_missing_user_profile_is_fatal(self, install_env, tmp_path):
        """Deliberately unlike the conf case, which falls back. Someone who
        explicitly named a profile and silently got the DEFAULT environment
        wouldn't find out until something they expected was missing."""
        copy, fake_home, home, run_install = install_env
        result = run_install(f"SEEDLING_PROFILE='{(tmp_path / 'ghost.toml').as_posix()}'")
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "no file exists at" in combined
        assert "falling back" not in combined


class TestEditorConf:
    """SEEDLING_VSCODE_FLAVOR / _EXTENSION_GALLERY / _VSCODE_EXTENSIONS reach
    settings.json intact, and a pristine conf seeds none of them."""

    def test_pristine_editor_conf_seeds_nothing(self, install_env):
        copy, fake_home, home, run_install = install_env
        _write_conf(copy, SEEDLING_AUTO_SETUP="false")
        run_install()
        s = _settings(home) or {}
        # The conf ships "microsoft" written out for discoverability; that is
        # the built-in default, so it must not be recorded as an override.
        assert "vscode_flavor" not in s
        assert "extension_gallery" not in s
        assert "vscode_extensions" not in s

    def test_vscodium_flavor_is_recorded(self, install_env):
        copy, fake_home, home, run_install = install_env
        _write_conf(copy, SEEDLING_VSCODE_FLAVOR="vscodium",
                    SEEDLING_AUTO_SETUP="false")
        run_install()
        assert _settings(home)["vscode_flavor"] == "vscodium"

    def test_flavor_is_normalized_to_lowercase(self, install_env):
        copy, fake_home, home, run_install = install_env
        _write_conf(copy, SEEDLING_VSCODE_FLAVOR="VSCodium",
                    SEEDLING_AUTO_SETUP="false")
        run_install()
        assert _settings(home)["vscode_flavor"] == "vscodium"

    def test_gallery_url_survives_verbatim(self, install_env):
        copy, fake_home, home, run_install = install_env
        _write_conf(copy, SEEDLING_EXTENSION_GALLERY="https://openvsx.corp/vscode",
                    SEEDLING_AUTO_SETUP="false")
        run_install()
        assert _settings(home)["extension_gallery"] == "https://openvsx.corp/vscode"

    def test_extension_list_becomes_a_json_array(self, install_env):
        copy, fake_home, home, run_install = install_env
        _write_conf(copy,
                    SEEDLING_VSCODE_EXTENSIONS="ms-python.python, charliermarsh.ruff",
                    SEEDLING_AUTO_SETUP="false")
        run_install()
        assert _settings(home)["vscode_extensions"] == [
            "ms-python.python", "charliermarsh.ruff"]

    def test_extensions_none_means_an_empty_list_not_an_unset(self, install_env):
        """"none" is a deliberate 'install nothing', which must survive as []
        -- an absent key would silently restore the starter kit instead."""
        copy, fake_home, home, run_install = install_env
        _write_conf(copy, SEEDLING_VSCODE_EXTENSIONS="none",
                    SEEDLING_AUTO_SETUP="false")
        run_install()
        assert _settings(home)["vscode_extensions"] == []


class TestBoolSettings:
    """The AUTO_* toggles are booleans: true runs, false skips. No yes/no."""

    def test_auto_setup_true_via_conf_runs(self, install_env):
        copy, fake_home, home, run_install = install_env
        _write_conf(copy, SEEDLING_AUTO_SETUP="true", SEEDLING_AUTO_VSCODE="false")
        run_install()
        assert "seed-cli python" in _calls(home)

    def test_auto_setup_false_via_conf_skips(self, install_env):
        copy, fake_home, home, run_install = install_env
        _write_conf(copy, SEEDLING_AUTO_SETUP="false")
        run_install()
        assert "seed-cli python" not in _calls(home)

    def test_bool_is_case_insensitive(self, install_env):
        copy, fake_home, home, run_install = install_env
        _write_conf(copy, SEEDLING_AUTO_SETUP="FALSE")
        run_install()
        assert "seed-cli python" not in _calls(home)


class TestVendorPayloads:
    def _plant_vendor(self, copy):
        # the vendored uv IS the stub -- proving the installer actually
        # executes the vendored binary rather than downloading
        from conftest import STUB_UV
        (copy / "vendor" / "uv").mkdir(parents=True)
        vendored_uv = copy / "vendor" / "uv" / "uv"
        vendored_uv.write_text(STUB_UV)
        vendored_uv.chmod(0o755)
        (copy / "vendor" / "uv" / "uvx").write_text("fake-uvx")
        (copy / "vendor" / "git" / "cmd").mkdir(parents=True)
        (copy / "vendor" / "git" / "cmd" / "git.exe").write_text("fake-git")
        (copy / "vendor" / "vscode" / "app" / "bin").mkdir(parents=True)
        (copy / "vendor" / "vscode" / "app" / "bin" / "code.cmd").write_text("fake")
        (copy / "vendor" / "certs").mkdir(parents=True)
        (copy / "vendor" / "certs" / "root.pem").write_text(
            "-----BEGIN CERTIFICATE-----\nROOT\n-----END CERTIFICATE-----\n")
        (copy / "vendor" / "certs" / "inter.crt").write_text(
            "-----BEGIN CERTIFICATE-----\nINTER\n-----END CERTIFICATE-----\n")

    def test_vendor_placed_and_excluded_from_src(self, install_env):
        copy, fake_home, home, run_install = install_env
        self._plant_vendor(copy)
        # no pre-planted uv this time: the vendored one must be used
        import shutil
        shutil.rmtree(home / "system" / "bin")
        result = run_install("SEEDLING_AUTO_SETUP=false")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Using vendored uv" in result.stdout
        assert (home / "system" / "bin" / "calls.log").exists(), \
            "the vendored uv stub never executed"
        assert (home / "system" / "bin" / "uvx").exists()
        assert (home / "extensions" / "git" / "cmd" / "git.exe").exists()
        assert (home / "extensions" / "vscode" / "app" / "bin" / "code.cmd").exists()
        bundle = (home / "system" / "certs" / "ca-bundle.pem").read_text()
        assert bundle.count("BEGIN CERTIFICATE") == 2
        assert _settings(home)["ca_cert"].endswith("ca-bundle.pem")
        assert not (home / "system" / "src" / "vendor").exists()
        uv_env = (home / "system" / "bin" / "uv-env.log").read_text()
        assert "SSL_CERT_FILE=" in uv_env and "GIT_SSL_CAINFO=" in uv_env

    def test_reinstall_keeps_existing_binaries_but_rebuilds_certs(self, install_env):
        copy, fake_home, home, run_install = install_env
        self._plant_vendor(copy)
        run_install("SEEDLING_AUTO_SETUP=false")
        marker = home / "extensions" / "git" / "cmd" / "git.exe"
        marker.write_text("user-modified")
        bundle = home / "system" / "certs" / "ca-bundle.pem"
        bundle.write_text("stale")
        run_install("SEEDLING_AUTO_SETUP=false")
        assert marker.read_text() == "user-modified", "binaries must not be clobbered"
        assert "BEGIN CERTIFICATE" in bundle.read_text(), "certs must rotate on reinstall"
