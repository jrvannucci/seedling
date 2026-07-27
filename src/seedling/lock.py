"""
Cross-process locking, so two `seed` commands can't mutate the same venv at
once.

The failure this prevents is real and quiet: two `seed install` runs against
one venv have uv unpacking wheels into the same site-packages concurrently,
and the loser can leave a half-written distribution that imports but is
missing modules. It stops being hypothetical the moment anything automated
drives seedling -- CI matrix jobs, a profile being applied while someone
works, several agents sharing a machine.

Why OS file locks rather than a PID file
----------------------------------------
A PID file has to answer "is the holder still alive?", and every answer is
wrong somewhere: PIDs get reused, a killed process never cleans up, and the
staleness timeout is either too short (breaking a slow install) or too long
(hanging after a crash). An OS advisory lock has no such question -- the
kernel drops it when the holding process dies, however it dies. Both
mechanisms used here are stdlib and present everywhere seedling runs:
`msvcrt.locking` on Windows, `fcntl.flock` elsewhere. Nothing to install,
which is seedling's rule.

The lock is advisory and seedling-scoped. It serializes seedling commands
against each other; it cannot stop someone running `uv pip install --python
<that venv>` by hand, and doesn't pretend to.

Waiting is visible. A command that blocks says so once, with the reason,
because a silent multi-second pause reads as a hang.

Lock files are never deleted, only unlocked. They are empty, one per venv
ever touched, and removing one is a race in itself -- a process can be
holding a lock on a file another process is about to unlink and recreate,
after which the two hold "the same" lock simultaneously. `seed purge`
removes the directory along with everything else.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import sys
import time
from pathlib import Path

from . import paths

# How long to wait for the holder to finish before giving up. Generous on
# purpose: the thing being waited for is usually a package install, and
# downloading a large wheel over a slow link legitimately takes minutes.
# Timing out is not a fallback to running anyway -- it's an error.
DEFAULT_TIMEOUT = 300.0

# How often to retry, and when to tell the user we're waiting. The message
# is delayed so the overwhelmingly common case -- no contention at all --
# stays silent.
_POLL_SECONDS = 0.2
_ANNOUNCE_AFTER = 1.0


class LockBusy(RuntimeError):
    """Raised when the lock could not be acquired within the timeout."""


def _locks_dir():
    paths.LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    return paths.LOCKS_DIR


def _safe_name(name: str) -> str:
    """A lock filename that can't escape the locks directory or collide with
    a path separator. Venv names reach here straight from the command line."""
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in name)


def _try_acquire(handle) -> bool:
    """One non-blocking attempt at an exclusive lock on an open file."""
    if os.name == "nt":
        import msvcrt
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    else:
        import fcntl
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False


def _release(handle) -> None:
    if os.name == "nt":
        import msvcrt
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


@contextlib.contextmanager
def file_lock(key: str, what: str, timeout: float = DEFAULT_TIMEOUT):
    """Hold an exclusive lock named `key` for the duration of the block.

    `what` describes the contended resource for the waiting message, e.g.
    "venv 'dev'". Raises LockBusy on timeout. If the lock file itself can't
    be created -- a read-only or full disk -- the command proceeds UNLOCKED
    rather than failing: losing serialization is bad, but refusing to work
    at all because a lock file couldn't be written is worse, and that
    trade-off matches how seedling already treats its logs.
    """
    try:
        lock_path = _locks_dir() / f"{_safe_name(key)}.lock"
        handle = open(lock_path, "a+")
    except OSError:
        yield False
        return

    acquired = False
    announced = False
    started = time.monotonic()
    try:
        while True:
            if _try_acquire(handle):
                acquired = True
                break
            waited = time.monotonic() - started
            if waited >= timeout:
                raise LockBusy(
                    f"another seed command has been working on {what} for "
                    f"over {int(timeout)}s, so this one stopped instead of "
                    f"running alongside it. Wait for it to finish, or check "
                    f"for a stuck process with `seed kill-processes`.")
            if not announced and waited >= _ANNOUNCE_AFTER:
                announced = True
                # stderr: a --json consumer must still get clean stdout.
                print(f"Waiting for another seed command to finish with "
                      f"{what}...", file=sys.stderr)
            time.sleep(_POLL_SECONDS)
        yield True
    finally:
        if acquired:
            _release(handle)
        try:
            handle.close()
        except OSError:
            pass


def venv_lock(venv_path, timeout: float = DEFAULT_TIMEOUT):
    """Serialize work on ONE venv, so two different venvs never wait on each
    other -- installing into 'web' while 'ml' builds is fine and common.

    Keyed by absolute path, not by name: `seed install` follows VIRTUAL_ENV
    wherever it points, including outside ~/seedling, and two unrelated
    `.venv` directories must not serialize against each other just because
    they share a leaf name. The name still leads the filename so the locks
    directory stays readable; the digest is what makes it exact.
    """
    venv_path = Path(venv_path)
    resolved = os.path.normcase(os.path.abspath(str(venv_path)))
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:8]
    return file_lock(f"venv-{venv_path.name}-{digest}",
                     f"venv '{venv_path.name}'", timeout)


def active_venv_lock(timeout: float = DEFAULT_TIMEOUT):
    """Lock whatever venv is active, or nothing at all when none is.

    With no VIRTUAL_ENV, uv falls back to a `.venv` in the working
    directory -- outside seedling's world and not its to serialize -- so
    this is deliberately a no-op there rather than a lock on some
    catch-all key that would make unrelated commands queue behind
    each other.
    """
    active = os.environ.get("VIRTUAL_ENV")
    if not active:
        return contextlib.nullcontext(False)
    return venv_lock(active, timeout)
