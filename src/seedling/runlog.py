"""
Per-command logging. Every `seed` invocation appends to a daily file under
~/seedling/system/logs/ (e.g. seed-2026-07-05.log): the exact command line,
a timestamp, everything the command printed (stdout AND stderr, with ANSI
color codes stripped), and the exit code.

Implemented as a tee: sys.stdout/sys.stderr keep writing to the real
terminal untouched (colors, isatty behavior, and the `seed activate
--print-path` capture done by the shell wrapper all still work), while a
plain-text copy lands in the log file. ANSI color codes are stripped on
purpose: the logs are plain text end to end so they can be shipped to a
server, grepped, or displayed anywhere without escape-code handling.

Logging never breaks the command itself: if the log file can't be created
or written (locked, disk full, permissions), seedling silently carries on
without it. Set SEEDLING_NO_LOG=1 to disable logging entirely.
"""

from __future__ import annotations

import datetime as _dt
import io
import os
import re
import sys

from . import paths

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

RETENTION_DAYS = 30


class _Tee(io.TextIOBase):
    """Wraps a real stream; mirrors every write into the shared log file."""

    def __init__(self, real, logfile):
        self._real = real
        self._log = logfile

    def write(self, s: str) -> int:
        n = self._real.write(s)
        try:
            self._log.write(_ANSI_RE.sub("", s))
        except (OSError, ValueError):
            pass  # never let a logging failure break the command
        return n

    def flush(self) -> None:
        self._real.flush()
        try:
            self._log.flush()
        except (OSError, ValueError):
            pass

    def isatty(self) -> bool:
        return self._real.isatty()

    def fileno(self) -> int:
        return self._real.fileno()

    @property
    def encoding(self):  # type: ignore[override]
        return getattr(self._real, "encoding", "utf-8")


_logfile = None
_saved_streams: tuple | None = None


def _prune_old_logs() -> None:
    cutoff = _dt.date.today() - _dt.timedelta(days=RETENTION_DAYS)
    try:
        for f in paths.LOGS_DIR.glob("seed-*.log"):
            stamp = f.name[len("seed-"): -len(".log")]
            try:
                if _dt.date.fromisoformat(stamp) < cutoff:
                    f.unlink()
            except (ValueError, OSError):
                continue
    except OSError:
        pass


def _redacted(argv: list[str]) -> list[str]:
    """The command line as it may be written to disk.

    `seed config set <key> <value>` carries the value on the command line, and
    some keys are secrets -- an upload token most obviously. The log is a
    plain-text file that lives for as long as the install does, so the one
    place a token must never be written is the very place a full argv goes."""
    from . import config
    if len(argv) >= 3 and argv[0] == "config" and argv[1] == "set"             and argv[2] in config.SECRET_KEYS:
        return [*argv[:3], "********"]
    return list(argv)


def start(argv: list[str]) -> None:
    """Begin logging this invocation. Safe to call exactly once per process."""
    global _logfile, _saved_streams
    if os.environ.get("SEEDLING_NO_LOG") == "1" or _logfile is not None:
        return
    try:
        paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        today = _dt.date.today().isoformat()
        _logfile = open(paths.LOGS_DIR / f"seed-{today}.log", "a", encoding="utf-8")
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _logfile.write(f"\n=== [{now}] seed {' '.join(_redacted(argv))}\n")
        _logfile.flush()
    except OSError:
        _logfile = None
        return

    _saved_streams = (sys.stdout, sys.stderr)
    sys.stdout = _Tee(sys.stdout, _logfile)
    sys.stderr = _Tee(sys.stderr, _logfile)
    _prune_old_logs()


def close_before_deleting_home() -> None:
    """Stops logging and closes the log file right now, for commands about
    to delete the very directory the log file lives in (`remove-user`,
    `purge`). Without this, this process still has seed-YYYY-MM-DD.log open
    for writing when it reaches the log directory in the tree it's
    deleting -- on Windows that file (and everything above it) fails to
    delete every single time logging is enabled, since the OS won't remove
    a file a process still holds open. No exit code is recorded (there's
    nowhere left to write it); the top-level finish() call afterward is a
    no-op once _logfile is None."""
    global _logfile, _saved_streams
    if _logfile is None:
        return
    if _saved_streams is not None:
        sys.stdout, sys.stderr = _saved_streams
        _saved_streams = None
    try:
        _logfile.close()
    except OSError:
        pass
    _logfile = None


def finish(exit_code: int) -> None:
    """Record the exit code and restore the real streams."""
    global _logfile, _saved_streams
    if _logfile is None:
        return
    if _saved_streams is not None:
        sys.stdout, sys.stderr = _saved_streams
        _saved_streams = None
    try:
        now = _dt.datetime.now().strftime("%H:%M:%S")
        _logfile.write(f"=== [{now}] exit code {exit_code}\n")
        _logfile.close()
    except OSError:
        pass
    _logfile = None
