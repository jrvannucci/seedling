"""vscode_cmd (pre-seed short-circuit, --no-open, clean offline errors) and
git_tool (lookup order, streamed tagging)."""

from __future__ import annotations

import json
import os
import urllib.error

import pytest

from conftest import needs_git, windows_only
from seedling import config, git_tool, paths
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
                        lambda os_id, kind, name: ("file:///x", None))
    monkeypatch.setattr(vscode_cmd.download, "fetch", lambda *a, **k: None)
    monkeypatch.setattr(vscode_cmd, "_extract", lambda *a, **k: None)
    monkeypatch.setattr(vscode_cmd, "_write_default_settings", lambda: None)
    called = []
    monkeypatch.setattr(vscode_cmd, "_install_extensions",
                        lambda cli, wanted=None: called.append(cli))

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
        vscode_cmd, "_resolve_download",
        lambda os_id, kind, name: ("https://x/download", None))
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
    url, sha = vscode_cmd._resolve_download(
        "win32-x64-archive", "zip", "microsoft")
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


# --------------------------------------------------------------------------
# Editor flavor / extension gallery / extension list (seedling.conf plumbing)
# --------------------------------------------------------------------------

def test_flavor_defaults_to_microsoft(home):
    assert vscode_cmd.flavor() == "microsoft"


def test_flavor_reads_config(home):
    config.set_value("vscode_flavor", "vscodium")
    assert vscode_cmd.flavor() == "vscodium"


def test_unknown_flavor_is_fatal(home):
    """A typo must NOT silently fall back to microsoft: a deployer who meant
    "vscodium" would then stage proprietary binaries they had deliberately
    chosen to avoid. A stopped install is recoverable; an unnoticed licensing
    problem on a share is not."""
    config.set_value("vscode_flavor", "vscoduim")
    with pytest.raises(vscode_cmd.UnknownFlavor) as excinfo:
        vscode_cmd.flavor()
    assert "vscoduim" in str(excinfo.value)
    assert "microsoft, vscodium" in str(excinfo.value)


def test_no_gallery_override_leaves_the_build_alone(home):
    """Both flavors already point at the right registry, so the common case
    patches nothing."""
    assert vscode_cmd.gallery_for("microsoft") is None
    assert vscode_cmd.gallery_for("vscodium") is None


def test_gallery_derives_both_endpoints_from_a_base_url(home):
    config.set_value("extension_gallery", "https://open-vsx.org/vscode")
    assert vscode_cmd.gallery_for("microsoft") == {
        "serviceUrl": "https://open-vsx.org/vscode/gallery",
        "itemUrl": "https://open-vsx.org/vscode/item",
    }


def test_gallery_tolerates_a_trailing_slash_or_a_full_service_url(home):
    for value in ("https://openvsx.corp/vscode/",
                  "https://openvsx.corp/vscode/gallery"):
        config.set_value("extension_gallery", value)
        assert vscode_cmd.gallery_for("microsoft")["serviceUrl"] == (
            "https://openvsx.corp/vscode/gallery")


def test_default_extension_set_per_flavor(home):
    assert "ms-python.vscode-pylance" in vscode_cmd.extensions_for("microsoft")
    # Pylance is licensed to official Microsoft products only, so it is not
    # on Open VSX and must not be requested there.
    assert "ms-python.vscode-pylance" not in vscode_cmd.extensions_for("vscodium")


def test_gallery_override_drops_pylance_even_on_the_microsoft_flavor(home):
    """Pointing a Microsoft build at another registry means Pylance won't be
    there either."""
    config.set_value("extension_gallery", "https://open-vsx.org/vscode")
    assert "ms-python.vscode-pylance" not in vscode_cmd.extensions_for("microsoft")


def test_configured_extension_list_wins(home):
    config.set_value("vscode_extensions", ["a.one", "b.two"])
    assert vscode_cmd.extensions_for("microsoft") == ["a.one", "b.two"]


def test_empty_configured_list_means_install_nothing(home):
    """Distinct from unset, which means 'use the starter kit'."""
    config.set_value("vscode_extensions", [])
    assert vscode_cmd.extensions_for("microsoft") == []


def test_extension_list_accepts_a_bare_string(home):
    """PowerShell 5.1's ConvertTo-Json renders a one-element array as a bare
    string, so settings.json can legitimately hold one."""
    config.set_value("vscode_extensions", "a.one, b.two")
    assert vscode_cmd.extensions_for("microsoft") == ["a.one", "b.two"]


def test_apply_gallery_rewrites_product_json(home, tmp_path):
    app = tmp_path / "app"
    (app / "resources" / "app").mkdir(parents=True)
    product = app / "resources" / "app" / "product.json"
    product.write_text(json.dumps(
        {"nameShort": "Code", "extensionsGallery": {"serviceUrl": "https://old"}}))
    vscode_cmd._apply_gallery(app, vscode_cmd.GALLERIES["openvsx"])
    data = json.loads(product.read_text())
    assert data["extensionsGallery"] == vscode_cmd.GALLERIES["openvsx"]
    assert data["nameShort"] == "Code", "unrelated keys must survive"


def test_apply_gallery_is_a_noop_without_an_override(home, tmp_path):
    app = tmp_path / "app"
    (app / "resources" / "app").mkdir(parents=True)
    product = app / "resources" / "app" / "product.json"
    product.write_text('{"extensionsGallery": {"serviceUrl": "https://keep"}}')
    vscode_cmd._apply_gallery(app, None)
    assert json.loads(product.read_text())["extensionsGallery"]["serviceUrl"] == (
        "https://keep")


def test_apply_gallery_warns_but_survives_a_missing_product_json(home, tmp_path, capsys):
    vscode_cmd._apply_gallery(tmp_path / "nothing-here",
                              vscode_cmd.GALLERIES["openvsx"])
    assert "product.json not found" in capsys.readouterr().out


def test_vscodium_asset_matching_ignores_lookalike_assets(home, monkeypatch):
    """The release also carries REH server tarballs and .deb/.rpm packages
    whose names contain the same platform tag."""
    monkeypatch.setattr(vscode_cmd, "_vscodium_asset_id", lambda: "linux-x64")
    payload = {"assets": [
        {"name": "vscodium-reh-linux-x64-1.96.tar.gz",
         "browser_download_url": "https://x/reh", "digest": "sha256:aaa"},
        {"name": "VSCodium-linux-x64-1.96.tar.gz",
         "browser_download_url": "https://x/right", "digest": "sha256:bbb"},
        {"name": "codium_1.96_amd64.deb",
         "browser_download_url": "https://x/deb", "digest": "sha256:ccc"},
    ]}

    class _Resp:
        def read(self): return json.dumps(payload).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(vscode_cmd.urllib.request, "urlopen", lambda *a, **k: _Resp())
    url, sha = vscode_cmd._resolve_vscodium()
    assert url == "https://x/right"
    assert sha == "sha256:bbb"


def test_vscodium_archive_suffix_follows_its_own_platform_tag(home, monkeypatch):
    """The suffix must derive from VSCodium's platform tag, not from
    _os_build()'s archive kind -- those are different naming schemes and
    letting them drift asks for an asset that was never published."""
    seen = {}

    class _Resp:
        def read(self):
            return json.dumps({"assets": []}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(vscode_cmd.urllib.request, "urlopen", lambda *a, **k: _Resp())
    for tag, suffix in [("linux-x64", ".tar.gz"), ("win32-x64", ".zip"),
                        ("darwin-arm64", ".zip")]:
        monkeypatch.setattr(vscode_cmd, "_vscodium_asset_id", lambda t=tag: t)
        try:
            vscode_cmd._resolve_vscodium()
        except OSError as e:
            seen[tag] = str(e)
        assert suffix in seen[tag], f"{tag} should look for {suffix}: {seen[tag]}"
