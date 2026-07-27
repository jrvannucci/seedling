"""Cross-process locking: mutual exclusion, the wait announcement, the
timeout, and the deliberate decision to keep working when the lock file
itself can't be created.

Note what is NOT tested here: that a hard-killed holder's lock is reclaimed.
That is the whole reason for using OS file locks over a PID file, but it is
an OS guarantee (the kernel drops the lock when the process dies) and
testing it means spawning and SIGKILLing subprocesses on two platforms --
cost that buys coverage of someone else's code.
"""

from __future__ import annotations

import pytest
from conftest import make_venv_dirs

from seedling import lock, paths


def test_second_holder_is_excluded(home):
    with lock.file_lock("k", "the thing", timeout=30):
        with pytest.raises(lock.LockBusy):
            with lock.file_lock("k", "the thing", timeout=0.3):
                pass


def test_lock_is_released_on_the_way_out(home):
    with lock.file_lock("k", "the thing", timeout=30):
        pass
    with lock.file_lock("k", "the thing", timeout=1) as acquired:
        assert acquired is True


def test_released_even_when_the_body_raises(home):
    with pytest.raises(ValueError):
        with lock.file_lock("k", "the thing", timeout=30):
            raise ValueError("boom")
    with lock.file_lock("k", "the thing", timeout=1) as acquired:
        assert acquired is True


def test_different_keys_do_not_contend(home):
    """Installing into 'web' while 'ml' builds is normal and must not
    serialize."""
    with lock.file_lock("a", "a", timeout=30):
        with lock.file_lock("b", "b", timeout=1) as acquired:
            assert acquired is True


def test_timeout_message_names_the_resource(home):
    with lock.file_lock("k", "venv 'dev'", timeout=30):
        with pytest.raises(lock.LockBusy) as excinfo:
            with lock.file_lock("k", "venv 'dev'", timeout=0.3):
                pass
    assert "venv 'dev'" in str(excinfo.value)


def test_waiting_is_announced_on_stderr(home, monkeypatch, capsys):
    """A silent multi-second pause reads as a hang -- and the message must
    not land on stdout, where a --json consumer is reading."""
    monkeypatch.setattr(lock, "_ANNOUNCE_AFTER", 0.0)
    with lock.file_lock("k", "venv 'dev'", timeout=30):
        with pytest.raises(lock.LockBusy):
            with lock.file_lock("k", "venv 'dev'", timeout=0.3):
                pass
    captured = capsys.readouterr()
    assert "Waiting for another seed command" in captured.err
    assert captured.out == ""


def test_no_announcement_when_uncontended(home, capsys):
    with lock.file_lock("k", "venv 'dev'", timeout=30):
        pass
    assert "Waiting" not in capsys.readouterr().err


def test_venv_locks_are_keyed_by_path_not_name(home, tmp_path):
    """`seed install` follows VIRTUAL_ENV wherever it points, so two
    unrelated venvs that happen to share a leaf name must not block each
    other."""
    elsewhere = tmp_path / "unrelated" / "dev"
    elsewhere.mkdir(parents=True)
    with lock.venv_lock(paths.venv_dir("dev"), timeout=30):
        with lock.venv_lock(elsewhere, timeout=1) as acquired:
            assert acquired is True


def test_same_venv_contends_however_it_is_spelled(home):
    make_venv_dirs(home, "dev")
    with lock.venv_lock(paths.venv_dir("dev"), timeout=30):
        with pytest.raises(lock.LockBusy):
            # Same directory, reached by a different-looking path.
            with lock.venv_lock(paths.VENVS_DIR / "." / "dev", timeout=0.3):
                pass


def test_active_venv_lock_is_a_noop_without_a_venv(home, monkeypatch):
    """With no VIRTUAL_ENV, uv falls back to a .venv in the working
    directory -- outside seedling's world, and not its to serialize."""
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    with lock.active_venv_lock() as acquired:
        assert acquired is False
        # Proves it really took nothing: a genuine lock would exclude this.
        with lock.active_venv_lock() as again:
            assert again is False


def test_active_venv_lock_follows_virtual_env(home, monkeypatch):
    make_venv_dirs(home, "dev")
    monkeypatch.setenv("VIRTUAL_ENV", str(paths.venv_dir("dev")))
    with lock.active_venv_lock(timeout=30) as acquired:
        assert acquired is True
        with pytest.raises(lock.LockBusy):
            with lock.venv_lock(paths.venv_dir("dev"), timeout=0.3):
                pass


def test_unwritable_lock_dir_does_not_block_the_command(home, monkeypatch):
    """Losing serialization is bad; refusing to work at all because a lock
    file couldn't be written is worse -- the same trade-off seedling already
    makes for its logs."""
    def _boom():
        raise OSError("read-only file system")
    monkeypatch.setattr(lock, "_locks_dir", _boom)
    with lock.file_lock("k", "the thing", timeout=30) as acquired:
        assert acquired is False


def test_lock_filenames_are_safe(home):
    """Venv names arrive straight from the command line; a separator in one
    must not escape the locks directory."""
    with lock.file_lock("../../evil name", "it", timeout=30):
        written = list(paths.LOCKS_DIR.glob("*.lock"))
    assert len(written) == 1
    assert written[0].parent == paths.LOCKS_DIR
    assert "/" not in written[0].name and "\\" not in written[0].name
