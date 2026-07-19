"""
Who is holding a file open on Windows -- asked properly, via the Restart
Manager API (rstrtmgr.dll), the same mechanism MSI and Windows Update use for
"the following applications are using files that need to be updated".

Why this exists
---------------
Deleting seedling's tree fails on Windows when another process holds a handle
to something inside it; POSIX has no such problem (unlinking an open file
succeeds, so none of this is needed there -- see fsutil.robust_rmtree).

The obvious workaround -- force-close everything named python/Code -- is wrong
in both directions. It closes the user's unrelated editor and long-running
jobs, and it MISSES the processes that actually matter: a PyQt/PySide app's
QtWebEngineProcess.exe lives inside site-packages and is named nothing like
python, and the same goes for node/ffmpeg/chromedriver spawned from a venv.

Restart Manager answers the real question directly and authoritatively: given
these files, which processes hold them? No name matching, no path guessing --
no false positives on an unrelated editor, and no misses on oddly-named
children.

It is reached through ctypes against a DLL present on every supported Windows,
so it stays inside seedling's "nothing pre-installed required" rule.

What it cannot see
------------------
A directory that is another process's CURRENT WORKING DIRECTORY also blocks
removal, and that is not a file handle -- Restart Manager reports nothing for
it. Callers fall back to a scoped heuristic for that case; see
kill_cmd.find_seedling_processes.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

_CCH_RM_MAX_APP_NAME = 255
_CCH_RM_MAX_SVC_NAME = 63
_RM_SESSION_KEY_LEN = 32
_ERROR_MORE_DATA = 234
_MAX_REGISTERED = 512  # a cap on how many paths we hand to one RM session


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


class _RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [("dwProcessId", wintypes.DWORD),
                ("ProcessStartTime", _FILETIME)]


class _RM_PROCESS_INFO(ctypes.Structure):
    _fields_ = [
        ("Process", _RM_UNIQUE_PROCESS),
        ("strAppName", wintypes.WCHAR * (_CCH_RM_MAX_APP_NAME + 1)),
        ("strServiceShortName", wintypes.WCHAR * (_CCH_RM_MAX_SVC_NAME + 1)),
        ("ApplicationType", ctypes.c_uint),
        ("AppStatus", ctypes.c_ulong),
        ("TSSessionId", wintypes.DWORD),
        ("bRestartable", wintypes.BOOL),
    ]


def available() -> bool:
    """True when the Restart Manager can be used on this machine."""
    if os.name != "nt":
        return False
    try:
        ctypes.WinDLL("rstrtmgr")
    except OSError:
        return False
    return True


def _load():
    return ctypes.WinDLL("rstrtmgr")


def holders(paths: list[str]) -> list[tuple[int, str]]:
    """[(pid, application name)] for the processes holding any of `paths`.

    Never raises: this runs on the path to a destructive operation, so a
    failure here must degrade to "we couldn't find out" rather than block a
    delete the caller could still complete another way. An empty list means
    "nothing found", never "verified clear"."""
    if not paths or not available():
        return []
    # RM takes real files; directories and vanished paths are not useful to
    # register and can make the whole call fail.
    files = [p for p in paths[:_MAX_REGISTERED] if os.path.isfile(p)]
    if not files:
        return []

    try:
        rm = _load()
        session = wintypes.DWORD()
        key = (wintypes.WCHAR * (_RM_SESSION_KEY_LEN + 1))()
        if rm.RmStartSession(ctypes.byref(session), 0, key) != 0:
            return []
        try:
            arr = (ctypes.c_wchar_p * len(files))(*files)
            if rm.RmRegisterResources(session, len(files), arr,
                                      0, None, 0, None) != 0:
                return []
            needed = ctypes.c_uint(0)
            count = ctypes.c_uint(0)
            reasons = ctypes.c_ulong(0)
            # First call is a sizing probe: it reports how many entries the
            # buffer needs via `needed` (and returns ERROR_MORE_DATA).
            rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count),
                         None, ctypes.byref(reasons))
            if needed.value == 0:
                return []
            count = ctypes.c_uint(needed.value)
            infos = (_RM_PROCESS_INFO * needed.value)()
            if rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count),
                            infos, ctypes.byref(reasons)) != 0:
                return []
            own = os.getpid()
            found: list[tuple[int, str]] = []
            for i in range(count.value):
                pid = int(infos[i].Process.dwProcessId)
                if pid == own:
                    continue  # we hold our own executable; never our problem
                name = infos[i].strAppName or f"pid {pid}"
                if (pid, name) not in found:
                    found.append((pid, name))
            return found
        finally:
            rm.RmEndSession(session)
    except (OSError, ValueError, AttributeError):
        return []


def describe(found: list[tuple[int, str]]) -> str:
    """'VS Code (pid 4821), Python (pid 913)' -- for user-facing messages."""
    return ", ".join(f"{name} (pid {pid})" for pid, name in found)
