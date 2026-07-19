"""Unit tests for the offline bundle builder (installers/build_offline.py):
platform/asset mapping, parsing uv's interpreter-download line, the conf
writer, and the VS Code staging step.

No network anywhere -- the VS Code tests stub subprocess.run and time.sleep, so
the retry window and the staging-cleanup guarantees are pinned without
downloading the real ~300MB payload. The actual downloads are still only
exercised by hand on a connected machine."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# build_offline.py lives in installers/ and isn't a package; load it directly.
_spec = importlib.util.spec_from_file_location(
    "build_offline", REPO_ROOT / "installers" / "build_offline.py")
build_offline = importlib.util.module_from_spec(_spec)
sys.modules["build_offline"] = build_offline
_spec.loader.exec_module(build_offline)


@pytest.mark.parametrize("machine,expected", [
    ("AMD64", "x86_64"), ("x86_64", "x86_64"), ("x64", "x86_64"),
    ("arm64", "aarch64"), ("aarch64", "aarch64"),
])
def test_normalized_arch(machine, expected):
    assert build_offline.normalized_arch(machine) == expected


@pytest.mark.parametrize("system,arch,expected", [
    ("Windows", "x86_64", "uv-x86_64-pc-windows-msvc.zip"),
    ("Windows", "aarch64", "uv-aarch64-pc-windows-msvc.zip"),
    ("Linux", "x86_64", "uv-x86_64-unknown-linux-gnu.tar.gz"),
    ("Darwin", "aarch64", "uv-aarch64-apple-darwin.tar.gz"),
])
def test_uv_asset_name(system, arch, expected):
    assert build_offline.uv_asset_name(system, arch) == expected


def test_uv_asset_name_rejects_unknown_os():
    with pytest.raises(ValueError):
        build_offline.uv_asset_name("Plan9", "x86_64")


def test_parse_pbs_target_windows_stripped():
    # The exact shape uv prints with -v (note the URL-encoded '+').
    line = ("DEBUG Downloading file:///C:/m/20241016/"
            "cpython-3.12.7%2B20241016-x86_64-pc-windows-msvc-"
            "install_only_stripped.tar.gz")
    tag, filename = build_offline.parse_pbs_target(line)
    assert tag == "20241016"
    # '%2B' decoded back to '+', which is the real on-disk asset name uv expects.
    assert filename == ("cpython-3.12.7+20241016-x86_64-pc-windows-msvc-"
                        "install_only_stripped.tar.gz")


def test_parse_pbs_target_linux_zst():
    line = ("Downloading file:///m/20250101/"
            "cpython-3.11.9%2B20250101-x86_64-unknown-linux-gnu-"
            "install_only.tar.zst")
    tag, filename = build_offline.parse_pbs_target(line)
    assert tag == "20250101"
    assert filename.endswith("install_only.tar.zst")


def test_parse_pbs_target_none_when_absent():
    assert build_offline.parse_pbs_target("nothing to see here") is None


@pytest.mark.parametrize("filename,expected", [
    ("cpython-3.12.13+20260623-x86_64-pc-windows-msvc-install_only_stripped.tar.gz", "3.12"),
    ("cpython-3.9.20+20240814-x86_64-unknown-linux-gnu-install_only.tar.gz", "3.9"),
    ("not-a-cpython-archive.tar.gz", None),
])
def test_minor_version(filename, expected):
    assert build_offline._minor_version(filename) == expected


def test_write_conf_replaces_in_place(tmp_path):
    conf = tmp_path / "seedling.conf"
    conf.write_text('SEEDLING_REPO_URL="https://old"\nOTHER="keep"\n',
                    encoding="utf-8")
    build_offline.write_conf(conf, {"SEEDLING_REPO_URL": "https://new"})
    text = conf.read_text(encoding="utf-8")
    assert 'SEEDLING_REPO_URL="https://new"' in text
    assert text.count("SEEDLING_REPO_URL=") == 1   # replaced, not duplicated
    assert 'OTHER="keep"' in text                  # untouched line preserved


def test_write_conf_appends_missing_key(tmp_path):
    conf = tmp_path / "seedling.conf"
    conf.write_text('OTHER="keep"\n', encoding="utf-8")
    build_offline.write_conf(conf, {"SEEDLING_PACKAGE_INDEX": "S:/wheels"})
    assert 'SEEDLING_PACKAGE_INDEX="S:/wheels"' in conf.read_text(encoding="utf-8")


def test_write_conf_handles_windows_backslash_value(tmp_path):
    """A Windows path value must not be interpreted as a regex-replacement
    escape (the \\U-in-C:\\Users bug)."""
    conf = tmp_path / "seedling.conf"
    conf.write_text('SEEDLING_PYTHON_MIRROR="x"\n', encoding="utf-8")
    win = r"C:\Users\dev\bundle\python-builds"
    build_offline.write_conf(conf, {"SEEDLING_PYTHON_MIRROR": win})
    assert f'SEEDLING_PYTHON_MIRROR="{win}"' in conf.read_text(encoding="utf-8")


def test_dry_run_returns_zero(tmp_path):
    code = build_offline.main(["--dry-run", "--output", str(tmp_path / "b")])
    assert code == 0


# --- requires-python floor --------------------------------------------------
# The mirrored interpreters serve two purposes: the one uv installs seed-cli
# with (must satisfy the floor) and base Pythons for users' own venvs (any
# version). So the rule is "at least one satisfies", not "all satisfy".


@pytest.mark.parametrize("text,expected", [
    ("3.12", (3, 12)), ("3.12.7", (3, 12, 7)), (" 3.9 ", (3, 9)),
    ("newest", None), ("", None), ("3.x", None),
])
def test_parse_version(text, expected):
    assert build_offline.parse_version(text) == expected


def test_seedling_python_floor_reads_the_real_pyproject():
    """Reads the actual src/pyproject.toml, so raising requires-python without
    touching the builder still moves the check."""
    assert build_offline.seedling_python_floor() == (3, 12)


def test_seedling_python_floor_parses_variants(tmp_path):
    for line, expected in [
        ('requires-python = ">=3.12"', (3, 12)),
        ('requires-python = ">= 3.13"', (3, 13)),
        ('requires-python = ">=3.12.1"', (3, 12, 1)),
    ]:
        p = tmp_path / "pyproject.toml"
        p.write_text(f'[project]\nname = "x"\n{line}\n', encoding="utf-8")
        assert build_offline.seedling_python_floor(p) == expected


def test_seedling_python_floor_is_none_when_unreadable(tmp_path):
    """An unreadable pyproject must not stop a bundle build."""
    assert build_offline.seedling_python_floor(tmp_path / "nope.toml") is None
    bad = tmp_path / "pyproject.toml"
    bad.write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert build_offline.seedling_python_floor(bad) is None


def test_check_python_versions_accepts_newest_and_supported():
    floor = (3, 12)
    assert build_offline.check_python_versions([""], floor) is None
    assert build_offline.check_python_versions(["3.12"], floor) is None
    assert build_offline.check_python_versions(["3.13", "3.14"], floor) is None


def test_check_python_versions_allows_old_alongside_supported():
    """--python 3.12,3.9 is legitimate: 3.9 is for users' venvs."""
    assert build_offline.check_python_versions(["3.12", "3.9"], (3, 12)) is None


def test_check_python_versions_rejects_all_below_floor():
    """The footgun: a bundle that builds here and fails air-gapped."""
    err = build_offline.check_python_versions(["3.9", "3.11"], (3, 12))
    assert err is not None
    assert "3.9, 3.11" in err
    assert ">=3.12" in err
    assert "air-gapped" in err


def test_check_python_versions_skips_when_floor_unknown():
    assert build_offline.check_python_versions(["3.9"], None) is None


def test_build_aborts_before_downloading_when_no_version_is_supported(tmp_path,
                                                                      monkeypatch,
                                                                      capsys):
    """Exit non-zero from main() with nothing staged -- the check has to land
    before the repo copy and the first download, not after."""
    def explode(*a, **kw):
        raise AssertionError("must not download or stage anything")

    monkeypatch.setattr(build_offline, "stage_repo", explode)
    monkeypatch.setattr(build_offline, "build_uv", explode)
    out_dir = tmp_path / "b"
    assert build_offline.main(["--yes", "--python", "3.9", "-o", str(out_dir)]) == 2
    assert "air-gapped" in capsys.readouterr().out
    assert not out_dir.exists()


def test_dry_run_plan_shows_the_floor(tmp_path, capsys):
    build_offline.main(["--dry-run", "-o", str(tmp_path / "a")])
    assert "seedling itself needs >=3.12" in capsys.readouterr().out


# --- VS Code staging -------------------------------------------------------
# The heavy step (~300MB). Everything below stubs the child process, so what's
# under test is the retry/cleanup logic around it, never a real download.


def _completed(returncode: int, stdout: str = ""):
    """Stand-in for subprocess.CompletedProcess."""
    return types.SimpleNamespace(returncode=returncode, stdout=stdout)


@pytest.fixture
def no_sleep(monkeypatch):
    """Collapse the ~2.5 minute retry window; records what would've been slept."""
    import time
    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    return slept


@pytest.fixture
def stub_cli(monkeypatch):
    """Pretend a VS Code CLI was found in the staged tree."""
    from seedling.commands import vscode_cmd
    monkeypatch.setattr(vscode_cmd, "_find_cli", lambda app_dir: ["code"])
    return vscode_cmd


def test_extensions_present_false_when_dir_missing(tmp_path):
    assert build_offline._extensions_present(tmp_path) is False


def test_extensions_present_false_for_bare_manifest(tmp_path):
    """VS Code seeds extensions.json even with nothing installed -- a file
    alone must not read as 'extensions are present'."""
    ext = tmp_path / "data" / "extensions"
    ext.mkdir(parents=True)
    (ext / "extensions.json").write_text("[]")
    assert build_offline._extensions_present(tmp_path) is False


def test_extensions_present_true_with_an_installed_extension(tmp_path):
    (tmp_path / "data" / "extensions" / "ms-python.python-2024.1.0").mkdir(parents=True)
    assert build_offline._extensions_present(tmp_path) is True


def test_install_extensions_batches_into_one_call(tmp_path, monkeypatch,
                                                  stub_cli, no_sleep):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _completed(0)

    monkeypatch.setattr(build_offline.subprocess, "run", fake_run)
    assert build_offline._install_extensions(tmp_path) is True
    # One invocation, carrying every extension -- not one process per extension.
    assert len(calls) == 1
    assert calls[0].count("--install-extension") == len(stub_cli.DEFAULT_EXTENSIONS)
    assert not no_sleep, "no retry should be needed on a first-try success"


def test_install_extensions_retries_until_the_tree_is_ready(tmp_path, monkeypatch,
                                                            stub_cli, no_sleep):
    """The documented failure mode: the CLI fails while the OS is still
    scanning the freshly-extracted files, then the same tree succeeds."""
    attempts = {"n": 0}

    def fake_run(cmd, **kw):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return _completed(1, "Signature verification failed with ENOENT")
        return _completed(0)

    monkeypatch.setattr(build_offline.subprocess, "run", fake_run)
    assert build_offline._install_extensions(tmp_path) is True
    assert attempts["n"] == 3
    assert no_sleep == [5, 10]  # backed off between the two failures only


def test_install_extensions_gives_up_after_the_retry_window(tmp_path, monkeypatch,
                                                            stub_cli, no_sleep):
    attempts = {"n": 0}

    def fake_run(cmd, **kw):
        attempts["n"] += 1
        return _completed(1, "some noise\nfinal error line")

    monkeypatch.setattr(build_offline.subprocess, "run", fake_run)
    assert build_offline._install_extensions(tmp_path) is False
    # 8 delays => 9 attempts, and the advertised ~2.5 minutes of waiting.
    assert attempts["n"] == 9
    assert sum(no_sleep) == 150


def test_install_extensions_without_a_cli_is_not_fatal(tmp_path, monkeypatch, no_sleep):
    from seedling.commands import vscode_cmd
    monkeypatch.setattr(vscode_cmd, "_find_cli", lambda app_dir: None)
    assert build_offline._install_extensions(tmp_path) is False


def test_build_vscode_short_circuits_when_already_staged(tmp_path, monkeypatch):
    vendor = tmp_path / "vendor" / "vscode"
    (vendor / "app").mkdir(parents=True)

    def explode(*a, **kw):
        raise AssertionError("must not re-download an already-staged VS Code")

    monkeypatch.setattr(build_offline.subprocess, "run", explode)
    assert build_offline.build_vscode(vendor, tmp_path / "vscode-staging") is True


def test_build_vscode_moves_the_tree_and_drops_staging(tmp_path, monkeypatch):
    staging = tmp_path / "vscode-staging"
    app = staging / "extensions" / "vscode" / "app"

    def fake_run(cmd, **kw):
        # Stand in for the child `vscode_cmd.install()` run.
        (app / "bin").mkdir(parents=True)
        (app / "data" / "extensions" / "charliermarsh.ruff-1.0").mkdir(parents=True)
        return _completed(0)

    monkeypatch.setattr(build_offline.subprocess, "run", fake_run)
    vendor = tmp_path / "vendor" / "vscode"
    assert build_offline.build_vscode(vendor, staging) is True
    assert (vendor / "app" / "bin").is_dir()
    assert not staging.exists()


def test_build_vscode_cleans_up_when_the_child_fails(tmp_path, monkeypatch):
    staging = tmp_path / "vscode-staging"

    def fake_run(cmd, **kw):
        staging.mkdir(parents=True, exist_ok=True)  # partial tree, no app/
        return _completed(1)

    monkeypatch.setattr(build_offline.subprocess, "run", fake_run)
    vendor = tmp_path / "vendor" / "vscode"
    assert build_offline.build_vscode(vendor, staging) is False
    assert not staging.exists()
    assert not vendor.exists()


def test_build_vscode_drops_staging_even_when_interrupted(tmp_path, monkeypatch):
    """Staging lives inside the folder deployers copy to the share, so a Ctrl-C
    partway through the extension retry must not strand ~300MB there."""
    staging = tmp_path / "vscode-staging"
    app = staging / "extensions" / "vscode" / "app"

    def fake_run(cmd, **kw):
        app.mkdir(parents=True)
        return _completed(0)

    def interrupted(app_dir):
        raise KeyboardInterrupt

    monkeypatch.setattr(build_offline.subprocess, "run", fake_run)
    monkeypatch.setattr(build_offline, "_install_extensions", interrupted)

    with pytest.raises(KeyboardInterrupt):
        build_offline.build_vscode(tmp_path / "vendor" / "vscode", staging)
    assert not staging.exists()


def test_dry_run_plan_states_the_vscode_choice(tmp_path, capsys):
    build_offline.main(["--dry-run", "-o", str(tmp_path / "a")])
    assert "yes (~300MB" in capsys.readouterr().out
    build_offline.main(["--dry-run", "--no-vscode", "-o", str(tmp_path / "b")])
    assert "skipped (--no-vscode)" in capsys.readouterr().out


@pytest.mark.skipif(sys.platform != "win32", reason="MinGit is Windows-only")
def test_mingit_is_opt_in_under_yes(tmp_path, monkeypatch, capsys):
    """--yes takes every default, and MinGit's default is off -- so an
    unattended build skips it unless --mingit flips that default."""
    monkeypatch.setattr(build_offline, "build_uv", lambda *a: None)
    monkeypatch.setattr(build_offline, "build_vscode", lambda vendor, staging: False)
    fetched = []
    monkeypatch.setattr(build_offline, "build_mingit",
                        lambda d: fetched.append(d) or True)

    build_offline.main(["--yes", "-o", str(tmp_path / "a")])
    assert fetched == []

    build_offline.main(["--yes", "--mingit", "-o", str(tmp_path / "b")])
    assert len(fetched) == 1
    assert fetched[0].name == "git"


def test_summary_flags_a_failed_vscode_step(tmp_path, monkeypatch, capsys):
    """A failed 300MB step must not read as a clean build in the summary."""
    monkeypatch.setattr(build_offline, "build_uv", lambda *a: None)
    monkeypatch.setattr(build_offline, "build_vscode", lambda vendor, staging: False)
    assert build_offline.main(["--yes", "-o", str(tmp_path / "b")]) == 0
    out = capsys.readouterr().out
    assert "redo step 6" in out


def test_summary_omits_the_vscode_row_when_not_requested(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_offline, "build_uv", lambda *a: None)
    assert build_offline.main(["--yes", "--no-vscode", "-o", str(tmp_path / "b")]) == 0
    out = capsys.readouterr().out
    assert "redo step 6" not in out
    assert "pre-seeded VS Code" not in out
