"""config.py (settings, defaults, TLS runtime env) and paths.py."""

from __future__ import annotations

import json
import os

from seedling import config, paths


def test_defaults_when_no_settings_file(home):
    data = config.load()
    assert data["default_base"] is None
    assert data["default_venv"] is None
    assert data["update_source"] is None
    assert data["venv_default_packages"] == ["ipython", "ruff", "ipykernel"]
    assert data["native_tls"] is None
    assert data["ca_cert"] is None
    assert data["auto_activate"] is True


def test_load_tolerates_utf8_bom_from_powershell_installer(home):
    # install.ps1 seeds settings.json via `Set-Content -Encoding UTF8`, which
    # on WinPowerShell 5.1 writes a UTF-8 BOM. Reading it must still work --
    # otherwise every conf-seeded setting is silently dropped on Windows.
    paths.ensure_layout()
    payload = {"update_source": "https://example.com/seedling.git",
               "shared_root": r"C:\seedling"}
    paths.CONFIG_FILE.write_text(json.dumps(payload), encoding="utf-8-sig")  # BOM
    assert paths.CONFIG_FILE.read_bytes()[:3] == b"\xef\xbb\xbf"  # sanity: BOM present
    assert config.get("update_source") == "https://example.com/seedling.git"
    assert config.is_multi_user() is True


def test_every_known_key_has_a_default(home):
    for key in config.KNOWN_KEYS:
        assert key in config._DEFAULTS, f"KNOWN_KEYS entry {key!r} missing a default"


def test_set_get_unset_roundtrip(home):
    config.set_value("default_venv", "dev")
    assert config.get("default_venv") == "dev"
    assert json.loads(paths.CONFIG_FILE.read_text())["default_venv"] == "dev"
    config.unset("default_venv")
    assert config.get("default_venv") is None


def test_corrupt_settings_file_falls_back_to_defaults(home):
    paths.ensure_layout()
    paths.CONFIG_FILE.write_text("{not json")
    assert config.get("venv_default_packages") == ["ipython", "ruff", "ipykernel"]


def test_unknown_keys_survive_saves(home):
    paths.ensure_layout()
    paths.CONFIG_FILE.write_text(json.dumps({"mystery": 42}))
    config.set_value("default_venv", "dev")
    data = json.loads(paths.CONFIG_FILE.read_text())
    assert data["mystery"] == 42 and data["default_venv"] == "dev"


def test_apply_runtime_env_sets_tls_vars(home):
    paths.ensure_layout()
    bundle = home / "system" / "certs" / "ca-bundle.pem"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("CERT")
    config.set_value("ca_cert", str(bundle))
    config.set_value("native_tls", True)
    config.apply_runtime_env()
    assert os.environ["SSL_CERT_FILE"] == str(bundle)
    assert os.environ["GIT_SSL_CAINFO"] == str(bundle)
    assert os.environ["UV_NATIVE_TLS"] == "1"


def test_apply_runtime_env_respects_existing_env(home, monkeypatch):
    paths.ensure_layout()
    bundle = home / "b.pem"
    bundle.write_text("CERT")
    config.set_value("ca_cert", str(bundle))
    monkeypatch.setenv("SSL_CERT_FILE", "user-choice.pem")
    config.apply_runtime_env()
    assert os.environ["SSL_CERT_FILE"] == "user-choice.pem"


def test_apply_runtime_env_skips_missing_bundle(home):
    config.set_value("ca_cert", str(home / "missing.pem"))
    config.apply_runtime_env()
    assert "SSL_CERT_FILE" not in os.environ


def test_seedling_home_env_override(home):
    assert paths.HOME == home
    assert str(paths.CONFIG_FILE).startswith(str(home))


def test_ensure_layout_creates_all_dirs(home):
    paths.ensure_layout()
    for d in paths.ALL_DIRS:
        assert d.is_dir(), d


def test_alias_and_venv_path_helpers(home):
    assert paths.base_alias_file("312").name == "312.alias.json"
    assert paths.venv_dir("dev") == home / "python" / "venvs" / "dev"
    assert paths.repo_dir("x") == home / "repo" / "x"
