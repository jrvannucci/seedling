"""End-to-end installer runs (POSIX installer under bash, dispatched
through the polyglot install.cmd) with a stub uv -- the full OFFLINE
deployment story: conf-driven sources, settings seeding, vendor/ payloads,
CA bundles, auto-setup, hook management. No network is touched anywhere.
"""

from __future__ import annotations

import json

import pytest

from conftest import make_repo_copy, needs_bash, plant_stub_uv, run_bash

pytestmark = needs_bash

PUBLIC_URL = "https://github.com/cryocliff/seedling.git"


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
    """Rewrite seedling.conf values in the repo copy."""
    conf = copy / "seedling.conf"
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
