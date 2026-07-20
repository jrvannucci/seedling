"""Unit tests for the offline bundle builder (installers/build_offline.py):
platform/asset mapping, parsing uv's interpreter-download line, the conf
writer, and the VS Code staging step.

No network anywhere -- the VS Code tests stub subprocess.run and time.sleep, so
the retry window and the staging-cleanup guarantees are pinned without
downloading the real ~300MB payload. The actual downloads are still only
exercised by hand on a connected machine."""

from __future__ import annotations

import importlib.util
import json
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


# --- preflight --------------------------------------------------------------
# The real check runs uv against a real bundle; these cover the logic around it
# without network. The end-to-end behaviour (a deliberately broken bundle being
# rejected) is exercised by hand -- see the build-offline notes in OFFLINE.md.


def _fake_bundle(tmp_path, versions=("3.12",), floor='">=3.12"'):
    out = tmp_path / "bundle"
    (out / "seedling" / "src").mkdir(parents=True)
    (out / "seedling" / "src" / "pyproject.toml").write_text(
        f'[project]\nname = "seedling"\nrequires-python = {floor}\n',
        encoding="utf-8")
    (out / "wheels").mkdir()
    for v in versions:
        tag = out / "python-builds" / "20260623"
        tag.mkdir(parents=True, exist_ok=True)
        (tag / f"cpython-{v}.9+20260623-x86_64-pc-windows-msvc-"
               "install_only_stripped.tar.gz").write_text("archive")
    return out


def test_discover_mirrored_versions(tmp_path):
    out = _fake_bundle(tmp_path, versions=("3.12", "3.13"))
    assert build_offline.discover_mirrored_versions(
        out / "python-builds") == ["3.12", "3.13"]


def test_discover_mirrored_versions_empty_when_no_mirror(tmp_path):
    assert build_offline.discover_mirrored_versions(tmp_path / "nope") == []


def test_offline_index_config_declares_a_flat_default_index(tmp_path):
    """Must match the shape seedling generates at runtime, or preflight stops
    testing what users actually get (see uv_tool._offline_index_config)."""
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    cfg = build_offline.write_offline_index_config(tmp_path / "uv.toml", wheels)
    text = cfg.read_text(encoding="utf-8")
    assert 'format = "flat"' in text
    assert "default = true" in text
    assert wheels.resolve().as_uri() in text


def test_preflight_env_is_isolated(tmp_path, monkeypatch):
    """A warm cache or an inherited UV_* var could make a BROKEN bundle pass."""
    monkeypatch.setenv("UV_INDEX_URL", "https://pypi.org/simple")
    monkeypatch.setenv("PIP_INDEX_URL", "https://pypi.org/simple")
    monkeypatch.setenv("SEEDLING_HOME", str(tmp_path / "real-home"))
    env = build_offline._preflight_env(
        tmp_path / "cache", tmp_path / "mirror", tmp_path / "uv.toml",
        tmp_path / "pythons")
    assert "UV_INDEX_URL" not in env
    assert "PIP_INDEX_URL" not in env
    assert "SEEDLING_HOME" not in env
    assert env["UV_CACHE_DIR"] == str(tmp_path / "cache")       # cold cache
    assert env["UV_PYTHON_INSTALL_DIR"] == str(tmp_path / "pythons")


def test_run_offline_always_passes_the_offline_flag(tmp_path, monkeypatch):
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="fine")

    monkeypatch.setattr(build_offline.subprocess, "run", fake_run)
    ok_, tail = build_offline._run_offline(Path("uv"), ["pip", "install", "x"], {})
    assert ok_ is True and tail == "fine"
    assert seen[0][-1] == "--offline"


def _stub_offline(monkeypatch, failing_prefix=None):
    """Make every uv call succeed, except ones whose args start with a prefix."""
    def fake(uv_exe, args, env):
        if failing_prefix and args[:len(failing_prefix)] == failing_prefix:
            return False, "boom"
        return True, "ok"
    monkeypatch.setattr(build_offline, "_run_offline", fake)


def test_verify_bundle_passes_a_complete_bundle(tmp_path, monkeypatch, capsys):
    out = _fake_bundle(tmp_path)
    _stub_offline(monkeypatch)
    uv = tmp_path / "uv.exe"
    uv.write_text("x")
    assert build_offline.verify_bundle(
        out, out / "seedling", uv, ["hatchling", "ipython"]) is True
    assert "Preflight passed" in capsys.readouterr().out


def test_verify_bundle_fails_when_venv_packages_are_missing(tmp_path, monkeypatch,
                                                            capsys):
    out = _fake_bundle(tmp_path)
    _stub_offline(monkeypatch, failing_prefix=["pip", "install"])
    uv = tmp_path / "uv.exe"
    uv.write_text("x")
    assert build_offline.verify_bundle(
        out, out / "seedling", uv, ["hatchling", "ipython"]) is False
    out_text = capsys.readouterr().out
    assert "Preflight FAILED" in out_text
    assert "seed venv --python 3.12" in out_text


def test_verify_bundle_fails_when_the_interpreter_wont_install(tmp_path, monkeypatch,
                                                               capsys):
    out = _fake_bundle(tmp_path)
    _stub_offline(monkeypatch, failing_prefix=["python", "install"])
    uv = tmp_path / "uv.exe"
    uv.write_text("x")
    assert build_offline.verify_bundle(
        out, out / "seedling", uv, ["hatchling"]) is False
    assert "won't install from the mirror" in capsys.readouterr().out


def test_verify_bundle_needs_an_interpreter_meeting_the_floor(tmp_path, monkeypatch,
                                                              capsys):
    """Mirroring only 3.9 against a >=3.12 floor can't build seed-cli."""
    out = _fake_bundle(tmp_path, versions=("3.9",))
    _stub_offline(monkeypatch)
    uv = tmp_path / "uv.exe"
    uv.write_text("x")
    assert build_offline.verify_bundle(
        out, out / "seedling", uv, ["hatchling"]) is False
    assert "requires-python" in capsys.readouterr().out


def test_verify_bundle_reports_a_missing_uv(tmp_path, capsys):
    out = _fake_bundle(tmp_path)
    assert build_offline.verify_bundle(
        out, out / "seedling", tmp_path / "absent-uv", ["hatchling"]) is False
    assert "nothing to verify with" in capsys.readouterr().out


def test_verify_only_rejects_a_missing_bundle(tmp_path, capsys):
    code = build_offline.main(["--verify-only", "-o", str(tmp_path / "nope")])
    assert code == 2
    assert "No bundle found" in capsys.readouterr().out


def test_verify_only_runs_the_check_and_returns_its_verdict(tmp_path, monkeypatch,
                                                            capsys):
    out = _fake_bundle(tmp_path)
    (out / "seedling" / "vendor" / "uv").mkdir(parents=True)
    monkeypatch.setattr(build_offline, "verify_bundle",
                        lambda *a, **kw: False)
    assert build_offline.main(["--verify-only", "-o", str(out)]) == 1
    monkeypatch.setattr(build_offline, "verify_bundle", lambda *a, **kw: True)
    assert build_offline.main(["--verify-only", "-o", str(out)]) == 0


def test_build_skips_preflight_with_no_verify(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_offline, "build_uv", lambda *a: None)
    monkeypatch.setattr(build_offline, "verify_bundle",
                        lambda *a, **kw: pytest.fail("must not verify"))
    build_offline.main(["--yes", "--no-vscode", "--no-verify",
                        "-o", str(tmp_path / "b")])
    assert "Skipped (--no-verify)" in capsys.readouterr().out


def test_summary_warns_when_the_bundle_was_never_verified(tmp_path, monkeypatch,
                                                          capsys):
    """An unverified bundle must not read as a confirmed one."""
    monkeypatch.setattr(build_offline, "build_uv", lambda *a: None)
    build_offline.main(["--yes", "--no-vscode", "--no-verify",
                        "-o", str(tmp_path / "b")])
    out = capsys.readouterr().out
    assert "nothing has confirmed this bundle installs" in out
    assert "--verify-only" in out


# --- wheel index ------------------------------------------------------------
# The wheelhouse is flat and holds every tag, so multiple interpreters just
# means multiple `pip download` passes into the same folder.


def _capture_pip_downloads(monkeypatch, fail_for=()):
    """Record each `pip download` invocation instead of running it."""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        version = cmd[cmd.index("--python-version") + 1] \
            if "--python-version" in cmd else None
        if version in fail_for:
            raise build_offline.subprocess.CalledProcessError(1, cmd)
        return _completed(0)

    monkeypatch.setattr(build_offline.subprocess, "run", fake_run)
    return calls


def _pinned_versions(calls):
    return [c[c.index("--python-version") + 1] for c in calls
            if "--python-version" in c]


def test_build_wheels_runs_a_pass_per_interpreter(tmp_path, monkeypatch):
    """The bug this fixes: only the FIRST mirrored interpreter got wheels, so
    compiled deps (pyzmq, tornado, debugpy...) were missing for the others."""
    calls = _capture_pip_downloads(monkeypatch)
    assert build_offline.build_wheels(
        Path("uv"), ["hatchling"], tmp_path / "w", ["3.12", "3.9"], None) is True
    assert _pinned_versions(calls) == ["3.12", "3.9"]
    # every pass lands in the same flat wheelhouse
    dests = {c[c.index("--dest") + 1] for c in calls}
    assert len(dests) == 1


def test_build_wheels_dedupes_interpreters(tmp_path, monkeypatch):
    calls = _capture_pip_downloads(monkeypatch)
    build_offline.build_wheels(
        Path("uv"), ["hatchling"], tmp_path / "w", ["3.12", "3.12"], None)
    assert _pinned_versions(calls) == ["3.12"]


def test_build_wheels_without_versions_does_one_unpinned_pass(tmp_path, monkeypatch):
    calls = _capture_pip_downloads(monkeypatch)
    assert build_offline.build_wheels(
        Path("uv"), ["hatchling"], tmp_path / "w", [], None) is True
    assert len(calls) == 1
    assert "--python-version" not in calls[0]


def test_build_wheels_reports_failure_naming_the_interpreter(tmp_path, monkeypatch,
                                                             capsys):
    """A partial failure must not read as success -- the bundle is unusable for
    that interpreter even though real wheels landed."""
    calls = _capture_pip_downloads(monkeypatch, fail_for=("3.9",))
    assert build_offline.build_wheels(
        Path("uv"), ["hatchling"], tmp_path / "w", ["3.12", "3.9"], None) is False
    out = capsys.readouterr().out
    assert "3.9" in out
    # the 3.12 pass still ran; one bad interpreter doesn't abort the rest
    assert _pinned_versions(calls) == ["3.12", "3.9"]


def test_build_wheels_pins_only_binary_alongside_a_version(tmp_path, monkeypatch):
    """pip can't build sdists for an interpreter it isn't running."""
    calls = _capture_pip_downloads(monkeypatch)
    build_offline.build_wheels(
        Path("uv"), ["hatchling"], tmp_path / "w", ["3.12"], None)
    assert "--only-binary=:all:" in calls[0]


# --- repo staging -----------------------------------------------------------


def _fake_repo(tmp_path, marker):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "marker.txt").write_text(marker)
    (root / ".git").mkdir()
    (root / ".git" / "junk").write_text("history")
    return root


def test_stage_repo_copies_and_excludes_history(tmp_path, monkeypatch):
    monkeypatch.setattr(build_offline, "REPO_ROOT", _fake_repo(tmp_path, "v1"))
    out = tmp_path / "bundle"
    copy = build_offline.stage_repo(out)
    assert (copy / "src" / "marker.txt").read_text() == "v1"
    assert not (copy / ".git").exists()


def test_stage_repo_refreshes_stale_source(tmp_path, monkeypatch):
    """Re-running the builder after editing the repo must ship the NEW source.
    Reusing the existing copy silently bundled the first build's code."""
    repo = _fake_repo(tmp_path, "v1")
    monkeypatch.setattr(build_offline, "REPO_ROOT", repo)
    out = tmp_path / "bundle"
    build_offline.stage_repo(out)

    (repo / "src" / "marker.txt").write_text("v2")
    copy = build_offline.stage_repo(out)
    assert (copy / "src" / "marker.txt").read_text() == "v2"


def test_stage_repo_refresh_keeps_vendor_payloads(tmp_path, monkeypatch):
    """vendor/ holds the expensive downloads and is gitignored, so a refresh
    must not throw them away -- that would re-download ~300MB every run."""
    repo = _fake_repo(tmp_path, "v1")
    monkeypatch.setattr(build_offline, "REPO_ROOT", repo)
    out = tmp_path / "bundle"
    copy = build_offline.stage_repo(out)
    (copy / "vendor" / "uv").mkdir(parents=True)
    (copy / "vendor" / "uv" / "uv.exe").write_text("expensive binary")

    (repo / "src" / "marker.txt").write_text("v2")
    copy = build_offline.stage_repo(out)
    assert (copy / "src" / "marker.txt").read_text() == "v2"      # refreshed
    assert (copy / "vendor" / "uv" / "uv.exe").read_text() == "expensive binary"
    assert not (out / ".vendor-stash").exists()                    # no leftovers


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


def test_builder_min_python_matches_seedling_floor():
    """The builder runs on the DEPLOYER's system Python, so its floor is a
    separate decision from seedling's -- they're just deliberately equal today.
    If you relax one, this failing is the prompt to think about the other."""
    assert build_offline.MIN_PYTHON == build_offline.seedling_python_floor()


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

    # A bundle including VS Code now also needs the third-party
    # acknowledgement -- --yes alone deliberately does not cover it.
    build_offline.main(["--yes", "--accept-third-party-terms",
                        "-o", str(tmp_path / "a")])
    assert fetched == []

    build_offline.main(["--yes", "--accept-third-party-terms", "--mingit",
                        "-o", str(tmp_path / "b")])
    assert len(fetched) == 1
    assert fetched[0].name == "git"


def test_summary_flags_a_failed_vscode_step(tmp_path, monkeypatch, capsys):
    """A failed 300MB step must not read as a clean build in the summary."""
    monkeypatch.setattr(build_offline, "build_uv", lambda *a: None)
    monkeypatch.setattr(build_offline, "build_vscode", lambda vendor, staging: False)
    assert build_offline.main(["--yes", "--accept-third-party-terms",
                               "-o", str(tmp_path / "b")]) == 0
    out = capsys.readouterr().out
    assert "redo step 6" in out


def test_summary_omits_the_vscode_row_when_not_requested(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_offline, "build_uv", lambda *a: None)
    assert build_offline.main(["--yes", "--no-vscode", "-o", str(tmp_path / "b")]) == 0
    out = capsys.readouterr().out
    assert "redo step 6" not in out
    assert "pre-seeded VS Code" not in out


# --------------------------------------------------------------------------
# Licensing posture: seedling ships nothing, gates what restricts
# redistribution, and records what it staged. See docs/LICENSING.md.
# --------------------------------------------------------------------------

def test_repo_ships_no_third_party_binaries():
    """The whole licensing posture rests on this: seedling redistributes
    nothing. If a binary is ever committed, that stops being true silently --
    so assert it rather than trusting .gitignore."""
    import subprocess as sp
    tracked = sp.run(["git", "ls-files"], cwd=str(REPO_ROOT),
                     capture_output=True, text=True, check=True).stdout.split()
    binary_suffixes = (".exe", ".dll", ".so", ".dylib", ".zip", ".gz", ".xz",
                       ".7z", ".vsix", ".deb", ".rpm", ".msi", ".pkg", ".bin")
    offenders = [f for f in tracked
                 if f.lower().endswith(binary_suffixes)
                 or f.startswith(("vendor/", "offline-bundle/"))]
    assert not offenders, f"third-party payloads must never be committed: {offenders}"


def test_permissive_only_bundle_is_not_gated(capsys):
    names = build_offline.planned_components(
        vscode=False, mingit=False, flavor="microsoft", gallery_overridden=False)
    assert build_offline.restricted_among(names) == []
    # accepted=False and no input available: a permissive bundle must still
    # proceed, or --no-vscode CI builds would hang on a prompt.
    assert build_offline.third_party_gate(names, accepted=False) is True


def test_vscodium_bundle_is_not_gated():
    names = build_offline.planned_components(
        vscode=True, mingit=False, flavor="vscodium", gallery_overridden=False)
    assert "vscodium" in names and "openvsx-extensions" in names
    assert build_offline.restricted_among(names) == []
    assert build_offline.third_party_gate(names, accepted=False) is True


def test_microsoft_vscode_bundle_is_gated():
    names = build_offline.planned_components(
        vscode=True, mingit=False, flavor="microsoft", gallery_overridden=False)
    assert build_offline.restricted_among(names) == ["vscode", "vscode-extensions"]


def test_gallery_override_swaps_the_extension_source():
    """A Microsoft build pointed elsewhere pulls extensions from there, so the
    Marketplace terms no longer apply to them."""
    names = build_offline.planned_components(
        vscode=True, mingit=False, flavor="microsoft", gallery_overridden=True)
    assert "openvsx-extensions" in names
    assert "vscode-extensions" not in names
    assert build_offline.restricted_among(names) == ["vscode"]  # the binary still is


def test_mingit_is_recorded_as_copyleft_but_does_not_gate():
    names = build_offline.planned_components(
        vscode=False, mingit=True, flavor="microsoft", gallery_overridden=False)
    assert build_offline.COMPONENTS["mingit"]["redistribution"] == "copyleft"
    assert build_offline.restricted_among(names) == []
    assert build_offline.third_party_gate(names, accepted=False) is True


def test_gate_refuses_without_acknowledgement(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *a: "no")
    names = build_offline.planned_components(
        vscode=True, mingit=False, flavor="microsoft", gallery_overridden=False)
    assert build_offline.third_party_gate(names, accepted=False) is False
    assert "NOT staged" in capsys.readouterr().out


def test_gate_accepts_explicit_yes(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "YES")
    names = build_offline.planned_components(
        vscode=True, mingit=False, flavor="microsoft", gallery_overridden=False)
    assert build_offline.third_party_gate(names, accepted=False) is True


def test_gate_is_not_satisfied_by_a_bare_enter(monkeypatch):
    """Acknowledging someone else's licence terms must be deliberate; the
    default must never be 'accepted'."""
    monkeypatch.setattr("builtins.input", lambda *a: "")
    names = build_offline.planned_components(
        vscode=True, mingit=False, flavor="microsoft", gallery_overridden=False)
    assert build_offline.third_party_gate(names, accepted=False) is False


def test_gate_flag_bypasses_the_prompt(monkeypatch):
    def boom(*a):
        raise AssertionError("prompted despite --accept-third-party-terms")
    monkeypatch.setattr("builtins.input", boom)
    names = build_offline.planned_components(
        vscode=True, mingit=False, flavor="microsoft", gallery_overridden=False)
    assert build_offline.third_party_gate(names, accepted=True) is True


def test_manifest_records_components_and_staging(tmp_path):
    names = build_offline.planned_components(
        vscode=True, mingit=False, flavor="microsoft", gallery_overridden=False)
    path = build_offline.write_manifest(
        tmp_path, names, staged={"uv": True, "vscode": False})
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "MANIFEST.json"
    assert doc["schema"] == 1
    by_name = {c["component"]: c for c in doc["components"]}
    assert by_name["uv"]["staged"] is True
    assert by_name["uv"]["license"] == "Apache-2.0 OR MIT"
    # A partial build must be recorded honestly, not as intended.
    assert by_name["vscode"]["staged"] is False
    assert by_name["vscode"]["redistribution"] == "restricted"
    assert "seedling ships no third-party software" in doc["notice"]


def test_profile_packages_are_added_to_the_wheel_set(tmp_path, capsys):
    """The wheel set must be DERIVED from the profile, not maintained
    alongside it -- drift between the two only surfaces as a failed install
    in the air-gapped room, after the bundle has been carried there."""
    prof = tmp_path / "p.toml"
    prof.write_text('[[venv]]\nname = "a"\npackages = ["pandas", "numpy"]\n',
                    encoding="utf-8")
    build_offline.main(["--dry-run", "--no-vscode", "--profile", str(prof),
                        "-o", str(tmp_path / "b")])
    out = capsys.readouterr().out
    wheels = [ln for ln in out.splitlines() if "Wheels" in ln][0]
    assert "pandas" in wheels and "numpy" in wheels
    for required in build_offline.REQUIRED_PACKAGES:
        assert required in wheels, "the required set must survive"


def test_profile_and_packages_flag_are_deduplicated(tmp_path, capsys):
    prof = tmp_path / "p.toml"
    prof.write_text('[[venv]]\nname = "a"\npackages = ["pandas"]\n',
                    encoding="utf-8")
    build_offline.main(["--dry-run", "--no-vscode", "--profile", str(prof),
                        "--packages", "pandas", "-o", str(tmp_path / "b")])
    wheels = [ln for ln in capsys.readouterr().out.splitlines()
              if "Wheels" in ln][0]
    assert wheels.count("pandas") == 1


def test_an_invalid_profile_stops_the_build(tmp_path, capsys):
    prof = tmp_path / "p.toml"
    prof.write_text('[[venv]]\nname = ""\n', encoding="utf-8")
    rc = build_offline.main(["--dry-run", "--no-vscode", "--profile", str(prof),
                            "-o", str(tmp_path / "b")])
    assert rc == 2
    assert "non-empty name" in capsys.readouterr().out


def test_empty_profile_flag_ignores_a_present_profile(tmp_path, capsys):
    """--profile= is the escape hatch for building a bundle that
    deliberately doesn't match the repo's profile."""
    build_offline.main(["--dry-run", "--no-vscode", "--profile", "",
                        "-o", str(tmp_path / "b")])
    assert "Profile     :" not in capsys.readouterr().out


def test_every_component_declares_a_redistribution_category():
    valid = {"permissive", "copyleft", "restricted"}
    for name, meta in build_offline.COMPONENTS.items():
        assert meta["redistribution"] in valid, name
        assert meta["license"] and meta["source"], name


def test_yes_alone_will_not_stage_restricted_components(tmp_path, monkeypatch, capsys):
    """--yes is for routine confirmations. Acknowledging someone else's
    licence terms is not routine, so an unattended build that would stage
    VS Code stops rather than proceeding silently."""
    monkeypatch.setattr(build_offline, "build_uv", lambda *a: None)
    def boom(*a):
        raise AssertionError("built despite no acknowledgement")
    monkeypatch.setattr(build_offline, "build_vscode", boom)
    monkeypatch.setattr("builtins.input", lambda *a: "")
    rc = build_offline.main(["--yes", "-o", str(tmp_path / "b")])
    assert rc == 2
    assert "NOT staged" in capsys.readouterr().out


def test_no_vscode_still_builds_unattended_with_just_yes(tmp_path, monkeypatch):
    """The permissive-only path must not have gained any new friction."""
    monkeypatch.setattr(build_offline, "build_uv", lambda *a: None)
    assert build_offline.main(["--yes", "--no-vscode", "--no-verify",
                               "-o", str(tmp_path / "b")]) == 0
