"""fsutil: defensive deletion, self-lock classification, deferred delete."""

from __future__ import annotations

import stat
import subprocess
import sys
import time


from conftest import windows_only
from seedling import fsutil


def test_rmtree_clears_read_only_files(home):
    """git marks .git/objects read-only; deletion must handle whole trees
    of them (the historical seed purge failure)."""
    tree = home / "system" / "src" / ".git" / "objects" / "ab"
    tree.mkdir(parents=True)
    for i in range(5):
        f = tree / f"obj{i}"
        f.write_text("x")
        f.chmod(stat.S_IREAD)
    failures = fsutil.robust_rmtree(home / "system" / "src")
    assert failures == []
    assert not (home / "system" / "src").exists()


def test_rmtree_missing_path_is_noop(home):
    assert fsutil.robust_rmtree(home / "nope") == []


def test_rmtree_escapes_own_cwd(home, monkeypatch):
    target = home / "python" / "venvs" / "dev"
    target.mkdir(parents=True)
    monkeypatch.chdir(target)
    failures = fsutil.robust_rmtree(target)
    assert failures == []
    assert not target.exists()


def test_classifier_accepts_only_cli_paths(home):
    bin_exe = home / "system" / "bin" / "seed-cli.exe"
    tool_py = home / "system" / "tool" / "seedling" / "Scripts" / "python.exe"
    a_dir = home / "system"
    for p in (bin_exe, tool_py):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    assert fsutil.failures_are_only_running_cli(
        [str(bin_exe), str(tool_py), str(a_dir)], home)


def test_classifier_rejects_other_files(home):
    stray = home / "repo" / "held-open.txt"
    stray.parent.mkdir(parents=True)
    stray.write_text("")
    assert not fsutil.failures_are_only_running_cli([str(stray)], home)


def test_classifier_rejects_paths_outside_home(home, tmp_path):
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("")
    assert not fsutil.failures_are_only_running_cli([str(outside)], home)


@windows_only
def test_deferred_delete_finishes_after_locker_exits(home):
    """End-to-end self-deletion: a child process holds a file open (like the
    running seed-cli), robust_rmtree can't remove it, the deferred helper
    wipes everything shortly after the child exits -- invisibly."""
    tooldir = home / "system" / "tool" / "seedling" / "Scripts"
    tooldir.mkdir(parents=True)
    (home / "system" / "bin").mkdir(parents=True)
    (home / "system" / "bin" / "seed-cli.exe").write_text("shim")
    lockfile = tooldir / "python.exe"

    child = subprocess.Popen(
        [sys.executable, "-c",
         f"f = open(r'{lockfile}', 'w'); import time; time.sleep(4)"])
    try:
        time.sleep(1.5)
        failures = fsutil.robust_rmtree(home, retries=1, delay=0.1)
        assert failures, "expected the locked file to survive rmtree"
        assert fsutil.failures_are_only_running_cli(failures, home)
        fsutil.schedule_deferred_delete(home)
    finally:
        child.wait()
    deadline = time.time() + 15
    while home.exists() and time.time() < deadline:
        time.sleep(0.5)
    assert not home.exists(), "deferred helper never finished the deletion"
