"""config.py (settings, defaults, TLS runtime env) and paths.py."""

from __future__ import annotations

import json
import os
from pathlib import Path

from seedling import PUBLIC_REPO, config, paths


def test_defaults_when_no_settings_file(home):
    data = config.load()
    assert data["default_base"] is None
    assert data["default_venv"] is None
    assert data["update_source"] is None
    assert data["venv_default_packages"] == ["ipython", "ruff", "ipykernel"]
    assert data["native_tls"] is None
    assert data["ca_cert"] is None
    assert data["auto_activate"] is True
    assert data["conda_channel"] == "conda-forge"


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


def test_public_repo_matches_installer_defaults():
    """seedling's own origin lives in ONE place (seedling.PUBLIC_REPO), but the
    installers can't import Python -- a piped `curl ... | sh` has no checkout
    beside it -- so they carry the same URL as their baked-in default. That
    agreement used to rest on a code comment; this asserts it.

    It matters at purge time: purge_cmd compares the recorded update_source
    against PUBLIC_REPO to decide whether an install came from public GitHub,
    and prints one-liners or share instructions accordingly. If the installers
    stamped a different URL, every public install would be misidentified and
    handed the wrong reinstall advice -- on the last screen `seed` ever shows.
    """
    import re

    repo_root = Path(__file__).resolve().parents[1]
    patterns = {
        "installers/install.sh": r'DEFAULT_SEEDLING_REPO="([^"]+)"',
        "installers/install.ps1": r'\$DefaultSeedlingRepo = "([^"]+)"',
        "GET_STARTED/global.conf": r'SEEDLING_REPO_URL="([^"]+)"',
    }
    for rel, pattern in patterns.items():
        text = (repo_root / rel).read_text(encoding="utf-8")
        found = re.search(pattern, text)
        assert found, f"{rel}: no default repo URL found (pattern changed?)"
        assert found.group(1) == PUBLIC_REPO, (
            f"{rel} points at {found.group(1)!r}, but seedling.PUBLIC_REPO is "
            f"{PUBLIC_REPO!r}")


def test_every_path_constant_is_rebound_into_the_test_home(home):
    """No path constant may still point at the developer's real ~/seedling
    while a test is running.

    conftest rebinds paths.* onto a tmp_path per test. That rebinding is
    hand-written, so a constant added to paths.py but not to _rebind_paths
    keeps its import-time value -- and every failure mode is silent: tests
    read and write the developer's actual seedling install, pass, and only
    a destructive test reveals it. This asserts the invariant directly
    (everything lives under the sandbox) rather than checking the
    bookkeeping, so it also catches a constant that is mirrored but not
    rebound.
    """
    from seedling import paths as p

    stray: list[str] = []

    def check(name: str, value) -> None:
        if value == home or home in value.parents:
            return
        stray.append(f"{name} -> {value}")

    for name in dir(p):
        if not name.isupper():
            continue
        value = getattr(p, name)
        if isinstance(value, Path):
            check(name, value)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, Path):
                    check(f"{name}[{index}]", item)

    assert not stray, (
        "these paths.* constants still point outside the test sandbox "
        f"(add them to conftest._rebind_paths): {', '.join(stray)}")


def test_git_dir_is_rebound_into_the_test_home(home):
    """git_tool.GIT_DIR is derived from paths at import time, so rebinding
    paths alone doesn't move it -- conftest has to rebind it separately.
    Same silent failure mode, so same guard."""
    from seedling import git_tool

    assert home in git_tool.GIT_DIR.parents


def test_the_upload_token_is_masked_wherever_settings_are_printed(run_cli, home):
    """seedling tees command output into ~/seedling/system/logs, so an
    unmasked token would be written to disk by the act of reading it back."""
    config.set_value("package_upload_token", "s3cret-token")

    code, out = run_cli("config")
    assert code == 0
    assert "s3cret-token" not in out
    assert "********" in out and "(set)" in out

    code, out = run_cli("config", "get", "package_upload_token")
    assert code == 0
    assert "s3cret-token" not in out


def test_an_unset_secret_is_not_shown_as_masked(run_cli, home):
    code, out = run_cli("config", "get", "package_upload_token")
    assert code == 0 and out.strip() == "", "unset must stay empty for scripts"
