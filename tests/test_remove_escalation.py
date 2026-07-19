"""The removal escalation ladder: delete, then identify and close only what
blocks, then the sledgehammer. The point is that destructive rungs are reached
on evidence rather than suspicion -- `seed remove-venv` used to close every
editor window on the machine before establishing anything was wrong."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from seedling import fsutil, winlocks
from seedling.commands import kill_cmd

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows-only behaviour")
posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX-only behaviour")


def _tree(tmp_path, name="tree"):
    root = tmp_path / name
    (root / "inner").mkdir(parents=True)
    (root / "inner" / "file.txt").write_text("data")
    return root


def _hold_open(path, seconds=60):
    """A child process holding a real handle on `path`.

    NB: don't assume Popen.pid is the process that ends up holding the file.
    Under `uvx`, sys.executable is a shim that spawns a real python.exe child,
    and it's the CHILD that owns the handle -- Restart Manager correctly names
    that one. Assert on behaviour, not on a guessed pid. (This is also why
    kill_cmd.terminate uses `taskkill /T` to take the whole tree.)"""
    proc = subprocess.Popen(
        [sys.executable, "-c",
         f"f=open(r'{path}'); import time; time.sleep({seconds})"])
    time.sleep(2.5)  # let it actually open the file
    return proc


# --- rung 1: the quiet path -------------------------------------------------

def test_unblocked_delete_closes_nothing(tmp_path, monkeypatch):
    """The common case must not kill anything, or even mention processes."""
    root = _tree(tmp_path)
    monkeypatch.setattr(kill_cmd, "terminate",
                        lambda pids: pytest.fail("must not terminate anything"))
    monkeypatch.setattr(kill_cmd, "kill_python_and_vscode",
                        lambda: pytest.fail("must not reach the sledgehammer"))
    messages = []
    assert fsutil.remove_tree(root, on_message=messages.append) == []
    assert not root.exists()
    assert messages == []


def test_missing_path_is_a_no_op(tmp_path):
    assert fsutil.remove_tree(tmp_path / "nope") == []


# --- rung 2: identify and close only the blocker ---------------------------

@windows_only
def test_locked_file_is_identified_and_only_that_is_closed(tmp_path, monkeypatch):
    """The whole point: a real lock, named and closed, without escalating."""
    root = _tree(tmp_path)
    locked = root / "inner" / "file.txt"
    holder = _hold_open(locked)
    monkeypatch.setattr(kill_cmd, "kill_python_and_vscode",
                        lambda: pytest.fail("should not need the sledgehammer"))
    try:
        messages = []
        survivors = fsutil.remove_tree(root, label="demo",
                                       on_message=messages.append)
        assert survivors == []
        assert not root.exists()
        assert any("holding files (demo)" in m for m in messages)
        assert any("Closing just those" in m for m in messages)
    finally:
        if holder.poll() is None:
            holder.kill()
        holder.wait(timeout=10)


@windows_only
def test_restart_manager_names_the_holding_process(tmp_path):
    target = tmp_path / "held.txt"
    target.write_text("x")
    assert winlocks.holders([str(target)]) == []
    holder = _hold_open(target)
    try:
        found = winlocks.holders([str(target)])
        assert found, "an open handle must be detected"
        assert all(pid != os.getpid() for pid, _ in found)  # never ourselves
        assert winlocks.describe(found)  # renders without raising
    finally:
        holder.kill()
        holder.wait(timeout=10)


def test_holders_never_raises_on_junk_input(tmp_path):
    """This runs on the path to a delete: it must degrade, never explode."""
    assert winlocks.holders([]) == []
    assert winlocks.holders([str(tmp_path / "does-not-exist")]) == []
    assert winlocks.holders([str(tmp_path)]) == []  # a directory, not a file


def test_describe_formats_pid_and_name():
    assert winlocks.describe([(12, "VS Code"), (34, "Python")]) == \
        "VS Code (pid 12), Python (pid 34)"


# --- rung 3: the sledgehammer, and opting out of it -------------------------

def test_escalates_to_sledgehammer_only_when_targeted_close_fails(tmp_path,
                                                                  monkeypatch):
    root = _tree(tmp_path)
    monkeypatch.setattr(fsutil, "robust_rmtree",
                        lambda p, **kw: [str(root / "inner" / "file.txt")])
    monkeypatch.setattr(winlocks, "holders", lambda paths: [(999, "Ghost")])
    monkeypatch.setattr(kill_cmd, "terminate", lambda pids: list(pids))
    used = []
    monkeypatch.setattr(kill_cmd, "kill_python_and_vscode",
                        lambda: used.append(True) or [])
    messages = []
    fsutil.remove_tree(root, on_message=messages.append)
    assert used, "should have reached the last resort"
    assert any("last resort" in m for m in messages)


def test_sledgehammer_can_be_declined(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    monkeypatch.setattr(fsutil, "robust_rmtree", lambda p, **kw: ["stuck"])
    monkeypatch.setattr(winlocks, "holders", lambda paths: [])
    monkeypatch.setattr(kill_cmd, "find_seedling_processes", lambda root=None: [])
    monkeypatch.setattr(kill_cmd, "kill_python_and_vscode",
                        lambda: pytest.fail("must not run when declined"))
    assert fsutil.remove_tree(root, allow_sledgehammer=False) == ["stuck"]


def test_cwd_blocker_falls_back_to_the_scoped_search(tmp_path, monkeypatch):
    """Restart Manager can't see a working-directory blocker, so an empty
    result there must hand off to the scoped search rather than give up."""
    root = _tree(tmp_path)
    calls = {"scoped": 0}
    monkeypatch.setattr(fsutil, "robust_rmtree", lambda p, **kw: ["stuck"])
    monkeypatch.setattr(winlocks, "holders", lambda paths: [])

    def fake_scoped(r=None):
        calls["scoped"] += 1
        return [(4321, "python")]

    monkeypatch.setattr(kill_cmd, "find_seedling_processes", fake_scoped)
    monkeypatch.setattr(kill_cmd, "terminate", lambda pids: list(pids))
    monkeypatch.setattr(kill_cmd, "kill_python_and_vscode", lambda: [])
    messages = []
    fsutil.remove_tree(root, on_message=messages.append)
    assert calls["scoped"] == 1
    assert any("4321" in m for m in messages)


# --- scoping ----------------------------------------------------------------

def test_scoped_search_ignores_unrelated_processes(tmp_path):
    """Scoping by location, not by name: this pytest run is a Python process,
    but it isn't under the (empty) tree, so it must not match."""
    found = kill_cmd.find_seedling_processes(str(tmp_path / "empty-root"))
    assert found == []


def test_scoped_search_never_returns_our_own_pid(tmp_path):
    for pid, _ in kill_cmd.find_seedling_processes(str(tmp_path)):
        assert pid != os.getpid()


@posix_only
def test_open_handles_do_not_block_deletion_on_posix(tmp_path):
    """Why the whole ladder is a Windows concern: POSIX unlink succeeds with
    handles open, so rung 1 always wins here."""
    root = _tree(tmp_path)
    with open(root / "inner" / "file.txt") as fh:
        assert fh is not None
        assert fsutil.remove_tree(root) == []
    assert not root.exists()
