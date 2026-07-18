"""seed health-check: OK/WARN/FAIL matrix, the cyan AREA column, exit codes,
stale-hook and offline source validation."""

from __future__ import annotations

import json

from conftest import make_venv_dirs
from seedling import config, paths


def test_fresh_sandbox_is_healthy_with_warnings(run_cli, home):
    code, out = run_cli("health-check")
    assert code == 0
    assert "FAIL" not in out
    assert "no base Pythons installed yet" in out
    assert "no update_source recorded" in out


def test_report_has_area_column_in_cyan(run_cli, home):
    # Each line carries an AREA label (uv, git, config, ...) rendered cyan.
    from seedling import colors
    colors._enabled = True  # force color on (isatty() is False under capture)
    try:
        code, out = run_cli("health-check")
    finally:
        colors._enabled = None
    assert "AREA" in out              # column header
    assert "\x1b[36muv" in out        # uv area label wrapped in cyan (\x1b[36m)
    assert "\x1b[36mlogs" in out      # and another area label


def test_area_labels_present_without_color(run_cli, home):
    # The AREA column is data, not decoration -- labels show even with color off.
    from seedling import colors
    colors._enabled = False  # force color off
    try:
        code, out = run_cli("health-check")
    finally:
        colors._enabled = None
    for area in ("uv", "git", "config", "shell", "logs", "updates"):
        assert area in out


def test_broken_default_venv_fails(run_cli, home):
    config.set_value("default_venv", "ghost")
    code, out = run_cli("health-check")
    assert code == 1
    assert "default_venv 'ghost'" in out


def test_corrupt_alias_fails(run_cli, home):
    paths.ensure_layout()
    (paths.BASE_DIR / "312.alias.json").write_text("{broken")
    code, out = run_cli("health-check")
    assert code == 1
    assert "alias file is corrupt" in out


def test_missing_base_target_fails(run_cli, home):
    paths.ensure_layout()
    (paths.BASE_DIR / "312.alias.json").write_text(
        json.dumps({"target": "cpython-gone"}))
    code, out = run_cli("health-check")
    assert code == 1 and "missing" in out


def test_venv_with_deleted_base_fails(run_cli, home):
    make_venv_dirs(home, "dev")
    (home / "python" / "venvs" / "dev" / "pyvenv.cfg").write_text(
        f"home = {home / 'python' / 'base' / 'gone'}\nversion = 3.12.0\n")
    code, out = run_cli("health-check")
    assert code == 1 and "its base Python" in out


class TestUpdateSourceVerification:
    """update_source is verified for real: URLs get a git ls-remote probe,
    directory paths get existence checks -- never 'assumed git URL'."""

    def _fake_git_run(self, monkeypatch, ls_remote_rc, ls_remote_stderr=""):
        """Patch subprocess.run inside status_cmd: ls-remote gets the scripted
        result; anything else (uv --version) succeeds generically."""
        from seedling.commands import status_cmd

        class R:
            def __init__(self, rc, out="", err=""):
                self.returncode, self.stdout, self.stderr = rc, out, err

        def fake_run(cmd, **kw):
            if "ls-remote" in cmd:
                fake_run.probed.append(cmd)
                return R(ls_remote_rc, err=ls_remote_stderr)
            return R(0, out="uv 0.0 (fake)")
        fake_run.probed = []
        monkeypatch.setattr(status_cmd.subprocess, "run", fake_run)
        return fake_run

    def test_reachable_url_is_verified_not_assumed(self, run_cli, home, monkeypatch):
        config.set_value("update_source", "https://github.com/x/seedling.git")
        fake = self._fake_git_run(monkeypatch, ls_remote_rc=0)
        code, out = run_cli("health-check")
        assert fake.probed, "status never probed the URL"
        assert "update_source git URL is reachable" in out
        assert "assumed" not in out

    def test_unreachable_url_warns_but_does_not_fail(self, run_cli, home, monkeypatch):
        config.set_value("update_source", "https://git.dead.internal/x.git")
        self._fake_git_run(monkeypatch, ls_remote_rc=128,
                           ls_remote_stderr="fatal: unable to access")
        code, out = run_cli("health-check")
        assert code == 0  # WARN, not FAIL: update-commands falls back
        assert "is not reachable" in out and "fatal: unable to access" in out

    def test_missing_directory_source_is_not_called_a_url(self, run_cli, home, tmp_path):
        config.set_value("update_source", str(tmp_path / "unmounted-share"))
        code, out = run_cli("health-check")
        assert code == 0
        assert "doesn't exist right now" in out
        assert "git URL" not in out and "assumed" not in out

    def test_url_without_git_warns(self, run_cli, home, monkeypatch):
        from seedling import git_tool
        config.set_value("update_source", "https://github.com/x/seedling.git")
        monkeypatch.setattr(git_tool, "find_git", lambda: None)
        code, out = run_cli("health-check")
        assert code == 0
        assert "git isn't available to verify" in out


def test_missing_offline_dirs_fail(run_cli, home):
    config.set_value("package_index", str(home / "no-wheels"))
    config.set_value("python_mirror", str(home / "no-mirror"))
    code, out = run_cli("health-check")
    assert code == 1
    assert "package_index directory" in out and "python_mirror directory" in out


def test_url_offline_sources_pass_without_network(run_cli, home):
    config.set_value("package_index", "https://pypi.internal/simple")
    config.set_value("python_mirror", "https://mirror.internal/pbs")
    code, out = run_cli("health-check")
    assert "package_index directory" not in out  # URLs aren't dir-checked


def test_missing_ca_cert_fails(run_cli, home):
    config.set_value("ca_cert", str(home / "gone.pem"))
    code, out = run_cli("health-check")
    assert code == 1 and "ca_cert" in out


def test_stale_hook_detection(run_cli, home, monkeypatch, tmp_path):
    """A profile hook line pointing at a deleted seed script must WARN, and a
    present target reads as OK. Uses the current platform's profile + script
    name (and native path separators) so the target actually resolves."""
    import os
    fake_userhome = tmp_path / "userhome"
    if os.name == "nt":
        profile = (fake_userhome / "Documents" / "WindowsPowerShell"
                   / "Microsoft.PowerShell_profile.ps1")
        seed_script = home / "system" / "shell" / "seed.ps1"
    else:
        profile = fake_userhome / ".bashrc"
        seed_script = home / "system" / "shell" / "seed.sh"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(f'. "{seed_script}"\n')
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: fake_userhome))
    code, out = run_cli("health-check")
    assert "stale seedling hook" in out
    # now make the hook target real -> OK
    seed_script.parent.mkdir(parents=True, exist_ok=True)
    seed_script.write_text("")
    code, out = run_cli("health-check")
    assert "shell hook installed" in out
