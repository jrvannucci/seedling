"""The standalone uninstaller (installers/uninstall.sh) resolves the install
location the same way the installer did -- {user}/custom SEEDLING_HOME_DIR
and SEEDLING_HOME env override -- so it targets the right folder instead of
a hardcoded ~/seedling. This is the fallback for when seed-cli is broken;
the normal path is `seed purge`."""

from __future__ import annotations

import shutil
import subprocess


from conftest import BASH, REPO_ROOT, needs_bash

pytestmark = needs_bash

UNINSTALL_SH = REPO_ROOT / "installers" / "uninstall.sh"


def _mini_repo(tmp_path, home_dir_value):
    """A minimal repo copy: installers/uninstall.sh + a seedling.conf whose
    SEEDLING_HOME_DIR is `home_dir_value`."""
    copy = tmp_path / "copy"
    (copy / "installers").mkdir(parents=True)
    shutil.copy(UNINSTALL_SH, copy / "installers" / "uninstall.sh")
    (copy / "seedling.conf").write_text(f'SEEDLING_HOME_DIR="{home_dir_value}"\n')
    return copy


def _run(copy, fake_home, extra_env=""):
    return subprocess.run(
        [BASH, "-c",
         f"cd '{(copy / 'installers').as_posix()}' && "
         f"HOME='{fake_home.as_posix()}' {extra_env} sh ./uninstall.sh"],
        capture_output=True, text=True, timeout=60)


def test_removes_current_user_in_shared_root_layout(tmp_path):
    root = tmp_path / "shared"
    for name in ("alice", "bob"):
        (root / name / "system" / "shell").mkdir(parents=True)
        (root / name / "system" / "shell" / "seed.sh").write_text("x")
    copy = _mini_repo(tmp_path, f"{root.as_posix()}/{{user}}")

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".bashrc").write_text(
        "export PATH=x\n"
        "# seedling\n"
        f'. "{(root / "alice" / "system" / "shell" / "seed.sh").as_posix()}"\n'
        "alias ll='ls -la'\n")

    r = _run(copy, fake_home, extra_env="USER=alice")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (root / "alice").exists(), "alice's install should be removed"
    assert (root / "bob").exists(), "bob's install must be untouched"
    bashrc = (fake_home / ".bashrc").read_text()
    assert "seed.sh" not in bashrc          # hook stripped
    assert "alias ll" in bashrc             # unrelated lines kept


def test_env_override_targets_that_home(tmp_path):
    copy = _mini_repo(tmp_path, "~/seedling")   # conf says default...
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    custom = tmp_path / "elsewhere" / "seedling"
    (custom / "system").mkdir(parents=True)
    (fake_home / "seedling").mkdir()            # the default location exists too

    # ...but SEEDLING_HOME env override wins
    r = _run(copy, fake_home, extra_env=f"SEEDLING_HOME='{custom.as_posix()}'")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not custom.exists(), "env-override home should be removed"
    assert (fake_home / "seedling").exists(), "default home must be left alone"


def test_default_layout_removes_home_seedling(tmp_path):
    copy = _mini_repo(tmp_path, "~/seedling")
    fake_home = tmp_path / "home"
    (fake_home / "seedling" / "system").mkdir(parents=True)
    (fake_home / ".bashrc").write_text(
        "# seedling\n"
        f'. "{(fake_home / "seedling" / "system" / "shell" / "seed.sh").as_posix()}"\n')
    r = _run(copy, fake_home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (fake_home / "seedling").exists()
    assert "seed.sh" not in (fake_home / ".bashrc").read_text()


def test_piped_from_github_defaults_to_home_seedling(tmp_path):
    """`curl .../uninstall.sh | sh`: no repo/conf reachable, $0 isn't a real
    path -- must not error and must default to ~/seedling."""
    fake_home = tmp_path / "home"
    (fake_home / "seedling" / "system").mkdir(parents=True)
    (fake_home / ".bashrc").write_text(
        "# seedling\n"
        f'. "{(fake_home / "seedling" / "system" / "shell" / "seed.sh").as_posix()}"\n'
        "keepme=1\n")
    script = UNINSTALL_SH.read_text()
    # pipe the script body into a fresh sh from an unrelated cwd (like curl | sh)
    r = subprocess.run(
        [BASH, "-c",
         f"cd '{tmp_path.as_posix()}' && HOME='{fake_home.as_posix()}' sh -s"],
        input=script, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (fake_home / "seedling").exists()
    bashrc = (fake_home / ".bashrc").read_text()
    assert "seed.sh" not in bashrc and "keepme" in bashrc
