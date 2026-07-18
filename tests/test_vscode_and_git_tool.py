"""vscode_cmd (pre-seed short-circuit, --no-open, clean offline errors) and
git_tool (lookup order, streamed tagging)."""

from __future__ import annotations

import os
import urllib.error


from conftest import needs_git, windows_only
from seedling import git_tool, paths
from seedling.commands import vscode_cmd


def _preseed_vscode(home):
    """A fake portable VS Code whose CLI script exists, in the layout the
    current platform's detection looks for: bin/code.cmd on Windows, an
    executable bin/code on POSIX."""
    bin_dir = home / "extensions" / "vscode" / "app" / "bin"
    bin_dir.mkdir(parents=True)
    if os.name == "nt":
        (bin_dir / "code.cmd").write_text("@echo off\r\nexit /b 0\r\n")
    else:
        code = bin_dir / "code"
        code.write_text("#!/bin/sh\nexit 0\n")
        code.chmod(0o755)


def test_install_short_circuits_when_preseeded(home, monkeypatch):
    _preseed_vscode(home)
    def boom(*a, **k):
        raise AssertionError("network touched despite pre-seeded install")
    monkeypatch.setattr(vscode_cmd, "_resolve_download", boom)
    cli = vscode_cmd.install(force=False)
    assert cli is not None
    assert cli[-1].endswith("code.cmd" if os.name == "nt" else "code")


def test_install_extensions_flag_gates_extension_step(home, monkeypatch):
    """install_extensions=False (used by the offline builder) downloads/extracts
    VS Code but skips the extension install; the default still runs it."""
    _preseed_vscode(home)  # so _find_cli returns a cli after the stubbed extract
    monkeypatch.setattr(vscode_cmd, "_resolve_download",
                        lambda os_id: ("file:///x", None))
    monkeypatch.setattr(vscode_cmd.download, "fetch", lambda *a, **k: None)
    monkeypatch.setattr(vscode_cmd, "_extract", lambda *a, **k: None)
    monkeypatch.setattr(vscode_cmd, "_write_default_settings", lambda: None)
    called = []
    monkeypatch.setattr(vscode_cmd, "_install_extensions", lambda cli: called.append(cli))

    vscode_cmd.install(force=True, install_extensions=False)
    assert called == []
    vscode_cmd.install(force=True, install_extensions=True)
    assert len(called) == 1


def test_no_open_installs_without_window(run_cli, home, monkeypatch):
    _preseed_vscode(home)
    opened = []
    monkeypatch.setattr(vscode_cmd, "open_window", lambda cli, p: opened.append(p))
    code, out = run_cli("vscode", "--no-open")
    assert code == 0
    assert "installed and ready" in out
    assert opened == []


def test_vscode_opens_given_path(run_cli, home, monkeypatch, tmp_path):
    _preseed_vscode(home)
    opened = []
    monkeypatch.setattr(vscode_cmd, "open_window", lambda cli, p: opened.append(p))
    code, out = run_cli("vscode", str(tmp_path))
    assert code == 0
    assert opened == [str(tmp_path)]


def test_write_status_single_parseable_line(home):
    # The installers poll this file for their status bar: one line,
    # "<phase> <done> <total>", overwritten in place.
    vscode_cmd._write_status("downloading", 1234, 5678)
    status = (paths.VSCODE_DIR / "setup-status").read_text().strip()
    assert status == "downloading 1234 5678"
    vscode_cmd._write_status("done")
    assert (paths.VSCODE_DIR / "setup-status").read_text().strip() == "done 0 0"


def test_download_progress_reporter_throttles_by_percent(home):
    report = vscode_cmd._download_progress_reporter()
    # 1000 calls inside the same percent must not produce 1000 writes; the
    # status file only reflects whole-percent transitions.
    for done in range(0, 1001):
        report(done, 100000)  # 0..1% territory
    status = (paths.VSCODE_DIR / "setup-status").read_text().strip()
    assert status == "downloading 1000 100000"  # last whole-percent (1%) write
    report(50000, 100000)
    assert "50000" in (paths.VSCODE_DIR / "setup-status").read_text()


def test_fetch_reports_progress(home, tmp_path):
    from seedling import download
    src = tmp_path / "payload.bin"
    src.write_bytes(b"x" * 700_000)  # bigger than one 256KB chunk
    url = "file:///" + str(src).replace("\\", "/")
    calls = []
    download.fetch(url, tmp_path / "out.bin", expected_sha256=None,
                   label="p", on_progress=lambda d, t: calls.append((d, t)))
    assert len(calls) >= 2                      # chunked, not one shot
    assert calls[-1][0] == 700_000              # final done == full size
    assert all(t == 700_000 for _, t in calls)  # file:// provides a length
    assert [d for d, _ in calls] == sorted(d for d, _ in calls)


def test_offline_download_fails_cleanly(home, monkeypatch, capsys):
    """No pre-seed + no network must be a one-line error, not a traceback."""
    monkeypatch.setattr(
        vscode_cmd, "_resolve_download", lambda os_id: ("https://x/download", None))
    def refuse(url, dest, **kw):
        raise urllib.error.URLError("no route to host")
    monkeypatch.setattr(vscode_cmd.download, "fetch", refuse)
    cli = vscode_cmd.install(force=False)
    assert cli is None
    out = capsys.readouterr().out
    assert "could not be downloaded" in out


def test_resolve_download_falls_back_when_api_unreachable(home, monkeypatch):
    def refuse(*a, **k):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(vscode_cmd.urllib.request, "urlopen", refuse)
    url, sha = vscode_cmd._resolve_download("win32-x64-archive")
    assert "code.visualstudio.com" in url
    assert sha is None


# --- git_tool ----------------------------------------------------------------

@needs_git
def test_find_git_prefers_path(home):
    found = git_tool.find_git()
    assert found is not None
    # bundled dir is empty in the sandbox, so this must be the PATH git
    assert str(git_tool.GIT_DIR) not in found


@windows_only  # the bundled MinGit fallback only applies on Windows
def test_find_git_falls_back_to_bundled(home, monkeypatch):
    monkeypatch.setattr(git_tool.shutil, "which", lambda name: None)
    bundled = git_tool.GIT_DIR / "cmd"
    bundled.mkdir(parents=True)
    (bundled / "git.exe").write_text("")
    assert git_tool.find_git() == str(bundled / "git.exe")


def test_find_git_none_when_nothing_available(home, monkeypatch):
    monkeypatch.setattr(git_tool.shutil, "which", lambda name: None)
    assert git_tool.find_git() is None


@needs_git
def test_run_streamed_tags_output(home, capsys):
    rc = git_tool.run_streamed([git_tool.find_git(), "--version"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[git]" in out and "git version" in out
