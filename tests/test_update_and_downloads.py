"""seed update-commands (all three modes, vendor/.git exclusion) and the
download/verification helpers. uv's reinstall step is stubbed so these run
offline and fast; the fetch/copy logic is what's under test."""

from __future__ import annotations

import subprocess

import pytest

from conftest import GIT, needs_git, windows_only
from seedling import config, download


@pytest.fixture
def src_installed(home, monkeypatch):
    """A sandbox with system/src populated and uv's tool-install stubbed."""
    src = home / "system" / "src" / "src"
    (src / "seedling").mkdir(parents=True)
    (src / "pyproject.toml").write_text("[project]\nname='seedling'\n")
    calls = []
    from seedling import uv_tool
    monkeypatch.setattr(uv_tool, "run", lambda args, **kw: calls.append(args))
    return home / "system" / "src", calls


def _make_source_tree(root, marker: str):
    (root / "src" / "seedling").mkdir(parents=True)
    (root / "src" / "pyproject.toml").write_text("[project]\nname='seedling'\n")
    (root / "MARKER.txt").write_text(marker)
    (root / ".git" / "objects").mkdir(parents=True)
    (root / "vendor" / "uv").mkdir(parents=True)
    (root / "vendor" / "uv" / "uv.exe").write_text("big binary")


def test_repair_mode_when_no_source_recorded(run_cli, home, src_installed):
    src, calls = src_installed
    code, out = run_cli("update-commands")
    assert code == 0
    assert "No update source is recorded" in out
    assert calls and calls[0][:2] == ["tool", "install"]
    assert calls[0][-1] == str(src / "src")


def test_directory_update_excludes_git_and_vendor(run_cli, home, src_installed, tmp_path):
    src, calls = src_installed
    upstream = tmp_path / "share"
    upstream.mkdir()
    _make_source_tree(upstream, "v2")
    config.set_value("update_source", str(upstream))
    code, out = run_cli("update-commands")
    assert code == 0
    assert (src / "MARKER.txt").read_text() == "v2"
    assert not (src / ".git").exists()
    assert not (src / "vendor").exists()


def test_directory_update_rejects_non_seedling_tree(run_cli, home, src_installed, tmp_path):
    bogus = tmp_path / "bogus"
    bogus.mkdir()
    config.set_value("update_source", str(bogus))
    code, out = run_cli("update-commands")
    assert code == 1
    assert "doesn't look like a seedling source tree" in out


@needs_git
def test_url_update_clones_and_swaps(run_cli, home, src_installed, tmp_path):
    src, calls = src_installed
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _make_source_tree(upstream, "v3")
    subprocess.run([GIT, "init", "-q", str(upstream)], check=True)
    subprocess.run([GIT, "-C", str(upstream), "add", "-A", "-f"], check=True)
    subprocess.run([GIT, "-C", str(upstream), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-qm", "v3"], check=True)
    url = "file:///" + str(upstream).replace("\\", "/")
    config.set_value("update_source", url)

    # plant a read-only .git in the OLD copy: the swap must clear it
    old_git = src / ".git" / "objects" / "ab"
    old_git.mkdir(parents=True)
    ro = old_git / "deadbeef"
    ro.write_text("x")
    import stat
    ro.chmod(stat.S_IREAD)

    code, out = run_cli("update-commands")
    assert code == 0
    assert (src / "MARKER.txt").read_text() == "v3"
    assert not (src / ".git").exists()
    assert not (src / "vendor").exists()


@needs_git
def test_url_update_falls_back_when_clone_fails(run_cli, home, src_installed, tmp_path):
    src, calls = src_installed
    (src / "KEEP.txt").write_text("still here")
    config.set_value("update_source", "file:///" + str(tmp_path / "nonexistent").replace("\\", "/"))
    code, out = run_cli("update-commands")
    assert code == 0  # never fatal: reinstalls current copy
    assert "keeping the current copy" in out or "Download failed" in out
    assert (src / "KEEP.txt").exists()
    assert calls, "reinstall should still run"


@needs_git
def test_url_update_from_branch_clones_that_branch(run_cli, home, src_installed, tmp_path):
    """--from-branch clones the named branch instead of the remote default."""
    src, calls = src_installed
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    # default branch `main` carries different content than the `feature` branch,
    # so landing feature's content proves the branch selection took effect.
    _make_source_tree(upstream, "on-main")
    subprocess.run([GIT, "init", "-q", "-b", "main", str(upstream)], check=True)
    subprocess.run([GIT, "-C", str(upstream), "add", "-A", "-f"], check=True)
    subprocess.run([GIT, "-C", str(upstream), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-qm", "main"], check=True)
    subprocess.run([GIT, "-C", str(upstream), "checkout", "-q", "-b", "feature"], check=True)
    (upstream / "MARKER.txt").write_text("on-feature")
    subprocess.run([GIT, "-C", str(upstream), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-qam", "feature"], check=True)
    subprocess.run([GIT, "-C", str(upstream), "checkout", "-q", "main"], check=True)

    config.set_value("update_source", "file:///" + str(upstream).replace("\\", "/"))

    code, out = run_cli("update-commands", "--from-branch", "feature")
    assert code == 0
    assert (src / "MARKER.txt").read_text() == "on-feature"
    assert "branch feature" in out


def test_from_branch_ignored_for_directory_source(run_cli, home, src_installed, tmp_path):
    src, calls = src_installed
    upstream = tmp_path / "share"
    upstream.mkdir()
    _make_source_tree(upstream, "v2")
    config.set_value("update_source", str(upstream))
    code, out = run_cli("update-commands", "--from-branch", "feature")
    assert code == 0
    assert "--from-branch is ignored" in out
    assert (src / "MARKER.txt").read_text() == "v2"  # still updated from the dir


def test_from_branch_ignored_when_no_source(run_cli, home, src_installed):
    src, calls = src_installed
    code, out = run_cli("update-commands", "--from-branch", "feature")
    assert code == 0
    assert "--from-branch is ignored" in out
    assert "No update source is recorded" in out


# --- self-update: rename-aside so a running seed-cli can be replaced ---------
# On Windows, `uv tool install --force --reinstall` must delete the tool venv
# whose python.exe IS the running seed-cli -- deletion of a running exe fails
# (and uv gets partway, bricking the install). update-commands renames the
# live copies aside first; these tests pin that behavior.


def _plant_live_cli(home):
    tool = home / "system" / "tool" / "seedling" / "Scripts"
    tool.mkdir(parents=True, exist_ok=True)
    (tool / "python.exe").write_text("live interpreter")
    shim = home / "system" / "bin" / "seed-cli.exe"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text("live shim")
    return tool.parent, shim


@windows_only
def test_self_update_renames_live_copies_aside(run_cli, home, src_installed):
    tooldir, shim = _plant_live_cli(home)
    code, out = run_cli("update-commands")
    assert code == 0
    # the live copies were moved aside (uv is stubbed, so nothing recreated them)
    assert not tooldir.exists() and not shim.exists()
    assert list(tooldir.parent.glob("seedling.old-*")), "tool venv not set aside"
    assert list(shim.parent.glob("seed-cli.exe.old-*")), "shim not set aside"


@windows_only
def test_self_update_rolls_back_when_reinstall_fails(run_cli, home, src_installed, monkeypatch):
    from seedling import uv_tool
    tooldir, shim = _plant_live_cli(home)

    def boom(args, **kw):
        raise subprocess.CalledProcessError(2, ["uv", *args])
    monkeypatch.setattr(uv_tool, "run", boom)

    code, out = run_cli("update-commands")
    assert code == 1
    assert "previous seed CLI was restored" in out
    # the live copies are back where they were, contents intact
    assert (tooldir / "Scripts" / "python.exe").read_text() == "live interpreter"
    assert shim.read_text() == "live shim"
    assert not list(tooldir.parent.glob("seedling.old-*"))


def test_self_update_sweeps_leftovers_from_previous_run(run_cli, home, src_installed):
    leftover = home / "system" / "tool" / "seedling.old-99999"
    leftover.mkdir(parents=True)
    (leftover / "python.exe").write_text("stale")
    code, out = run_cli("update-commands")
    assert code == 0
    assert not leftover.exists()


# --- shell integration refresh ----------------------------------------------
# update-commands must re-render system/shell/seed.{ps1,sh} from the (just
# refreshed) templates -- template changes would otherwise only reach users
# on a full reinstall, never on an update.

def _add_templates(tree_root, marker: str):
    shell = tree_root / "src" / "seedling" / "shell"
    shell.mkdir(parents=True, exist_ok=True)
    (shell / "seed.ps1.template").write_text(
        '$script:SeedlingHome = "__SEEDLING_HOME_PLACEHOLDER__"\n'
        f"# shell {marker}\n")
    (shell / "seed.sh.template").write_text(
        '__SEEDLING_HOME="__SEEDLING_HOME_PLACEHOLDER__"\n'
        f"# shell {marker}\n")


def test_update_refreshes_rendered_shell_files(run_cli, home, src_installed, tmp_path):
    src, calls = src_installed
    upstream = tmp_path / "share"
    upstream.mkdir()
    _make_source_tree(upstream, "v2")
    _add_templates(upstream, "v2")
    config.set_value("update_source", str(upstream))

    # A stale render from install time, with the home the installer baked in.
    shell_dir = home / "system" / "shell"
    shell_dir.mkdir(parents=True, exist_ok=True)
    (shell_dir / "seed.ps1").write_text(
        f'$script:SeedlingHome = "{home}"\n# shell v1\n')

    code, out = run_cli("update-commands")
    assert code == 0
    assert "Refreshing shell integration" in out
    rendered = (shell_dir / "seed.ps1").read_text()
    assert "# shell v2" in rendered
    assert "__SEEDLING_HOME_PLACEHOLDER__" not in rendered
    assert f'"{home}"' in rendered  # baked-in home survives the refresh


def test_refresh_preserves_posix_home_in_sh_render(run_cli, home, src_installed, tmp_path):
    """install.sh under git-bash bakes a POSIX-style home into seed.sh that
    str(Path) would not reproduce on Windows; the refresh must keep it."""
    src, calls = src_installed
    upstream = tmp_path / "share"
    upstream.mkdir()
    _make_source_tree(upstream, "v2")
    _add_templates(upstream, "v2")
    config.set_value("update_source", str(upstream))

    posix_home = home.as_posix()
    shell_dir = home / "system" / "shell"
    shell_dir.mkdir(parents=True, exist_ok=True)
    (shell_dir / "seed.sh").write_text(
        f'__SEEDLING_HOME="{posix_home}"\n# shell v1\n')

    code, out = run_cli("update-commands")
    assert code == 0
    rendered = (shell_dir / "seed.sh").read_text()
    assert "# shell v2" in rendered
    assert f'__SEEDLING_HOME="{posix_home}"' in rendered


def test_refresh_restores_missing_platform_file(run_cli, home, src_installed, tmp_path):
    """No rendered file at all (e.g. deleted by hand): the current platform's
    one is re-created from the template with this install's home."""
    src, calls = src_installed
    upstream = tmp_path / "share"
    upstream.mkdir()
    _make_source_tree(upstream, "v2")
    _add_templates(upstream, "v2")
    config.set_value("update_source", str(upstream))

    code, out = run_cli("update-commands")
    assert code == 0
    import os
    name = "seed.ps1" if os.name == "nt" else "seed.sh"
    rendered = (home / "system" / "shell" / name).read_text()
    assert "# shell v2" in rendered
    assert "__SEEDLING_HOME_PLACEHOLDER__" not in rendered


def test_update_without_templates_skips_shell_refresh(run_cli, home, src_installed):
    """A source tree with no templates (this fixture's stub) refreshes
    nothing and says nothing -- and must not error."""
    src, calls = src_installed
    code, out = run_cli("update-commands")
    assert code == 0
    assert "Refreshing shell integration" not in out


# --- download.py -------------------------------------------------------------

def test_sha256_and_fetch_roundtrip(home, tmp_path, capsys):
    src_file = tmp_path / "payload.bin"
    src_file.write_bytes(b"hello seedling")
    url = "file:///" + str(src_file).replace("\\", "/")
    digest = download.sha256_of(src_file)

    dest = tmp_path / "out.bin"
    download.fetch(url, dest, expected_sha256=digest, label="payload")
    assert dest.read_bytes() == b"hello seedling"
    assert "Verified SHA-256" in capsys.readouterr().out

    # github-style "sha256:<hex>" prefix accepted
    download.fetch(url, dest, expected_sha256=f"sha256:{digest}", label="payload")


def test_fetch_mismatch_deletes_and_raises(home, tmp_path):
    src_file = tmp_path / "payload.bin"
    src_file.write_bytes(b"tampered")
    url = "file:///" + str(src_file).replace("\\", "/")
    dest = tmp_path / "out.bin"
    with pytest.raises(download.ChecksumMismatch):
        download.fetch(url, dest, expected_sha256="0" * 64, label="payload")
    assert not dest.exists()


def test_fetch_without_checksum_warns_but_proceeds(home, tmp_path, capsys):
    src_file = tmp_path / "payload.bin"
    src_file.write_bytes(b"data")
    url = "file:///" + str(src_file).replace("\\", "/")
    dest = tmp_path / "out.bin"
    download.fetch(url, dest, expected_sha256=None, label="payload")
    assert dest.exists()
    assert "no published checksum" in capsys.readouterr().out


# --- tar extraction ----------------------------------------------------------
# extract_tar pins the 'data' filter explicitly rather than inheriting whatever
# the running interpreter defaults to (3.14 flips that default; 3.12/3.13 warn).

def _tar_with(tmp_path, members):
    """Build a tarball from {arcname: bytes}."""
    import io
    import tarfile
    archive = tmp_path / "payload.tar.gz"
    with tarfile.open(archive, "w:gz") as t:
        for arcname, data in members.items():
            ti = tarfile.TarInfo(arcname)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    return archive


def test_extract_tar_extracts_normal_members(tmp_path):
    archive = _tar_with(tmp_path, {"uv": b"binary", "nested/uvx": b"binary"})
    dest = tmp_path / "out"
    download.extract_tar(archive, dest)
    assert (dest / "uv").read_bytes() == b"binary"
    assert (dest / "nested" / "uvx").read_bytes() == b"binary"


def test_extract_tar_creates_dest(tmp_path):
    archive = _tar_with(tmp_path, {"uv": b"x"})
    dest = tmp_path / "deep" / "not" / "there"
    download.extract_tar(archive, dest)
    assert (dest / "uv").exists()


def test_extract_tar_refuses_path_traversal(tmp_path):
    """A member escaping the destination must be refused outright, not written
    (the whole point of pinning the filter)."""
    import tarfile
    if not hasattr(tarfile, "data_filter"):
        pytest.skip("interpreter predates the tarfile filter backport")
    archive = _tar_with(tmp_path, {"../escaped.txt": b"pwned"})
    dest = tmp_path / "out"
    with pytest.raises(tarfile.OutsideDestinationError):
        download.extract_tar(archive, dest)
    assert not (tmp_path / "escaped.txt").exists()


def test_extract_tar_does_not_warn_on_modern_pythons(tmp_path, recwarn):
    """No DeprecationWarning about the coming default change, because the
    filter is now explicit."""
    archive = _tar_with(tmp_path, {"uv": b"x"})
    download.extract_tar(archive, tmp_path / "out")
    assert not [w for w in recwarn if issubclass(w.category, DeprecationWarning)]
