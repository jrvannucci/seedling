"""
Shared, defensive directory deletion, used everywhere seedling deletes a
directory tree (remove-venv(-all), remove-python, remove-repo, remove-user,
purge).

Plain `shutil.rmtree(path, ignore_errors=True)` has several real failure
modes this works around:

1. Windows refuses to delete a directory that is any running process's
   current working directory -- including the calling process itself. If
   the terminal that ran `seed remove-user`/`seed purge` happens to have its
   cwd inside the tree being deleted (a common case: someone `cd`s into a
   project under a venv/repo, activates it, then runs the remove command
   from right there), deletion of that specific directory silently fails
   and `ignore_errors=True` hides it -- which matches the reported "unable
   to delete some file if a venv is activated" symptom.
2. A process we just force-killed (see kill_cmd) may not release its file
   handles instantly; deleting immediately can race that.
3. Read-only files fail deletion on Windows outright -- and git marks every
   file in .git/objects read-only, so any tree containing a git checkout
   (cloned repos, seedling's own source copy) hits this on every single
   run. The error handler clears the read-only bit and retries.
4. A process cannot delete its own running executable on Windows. `seed
   purge`/`seed remove-user` run AS seed-cli.exe (plus the tool venv's
   python.exe underneath it), which live inside the very tree being
   deleted. See schedule_deferred_delete()/failures_are_only_running_cli()
   for how the callers finish the job after this process exits.

This retries with a short backoff and actually reports which paths, if
any, are still stuck after all attempts, instead of swallowing everything.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path


def robust_rmtree(path: Path, retries: int = 3, delay: float = 0.75) -> list[str]:
    """Delete a directory tree. Returns a list of paths that still
    couldn't be removed after all retries (empty on full success)."""
    path = Path(path)
    if not path.exists():
        return []

    _escape_if_inside(path)

    failures: list[str] = []
    for attempt in range(retries):
        failures = []

        def _on_error(func, failed_path, _exc_info):
            # Most common cause on Windows: the file is read-only (git
            # marks all of .git/objects read-only). Clear the bit and
            # retry the exact operation that failed; only report a
            # failure if that still doesn't work.
            try:
                os.chmod(failed_path, stat.S_IWRITE)
                func(failed_path)
            except OSError:
                failures.append(str(failed_path))

        shutil.rmtree(path, onerror=_on_error)
        if not path.exists() and not failures:
            return []
        if attempt < retries - 1:
            time.sleep(delay)

    return failures


# One wording for the escalation, shared by every remove command's prompt and
# --preview, so the promise made to the user matches remove_tree() below.
ESCALATION_NOTE = (
    "nothing is closed up front -- if a file turns out to be locked, seedling "
    "names the process holding it and closes only that, and falls back to "
    "force-closing all Python/VS Code processes only if that isn't enough")


def remove_tree(path: Path, *, label: str = "", allow_sledgehammer: bool = True,
                on_message=print) -> list[str]:
    """Delete `path`, escalating only as far as it has to. Returns the paths
    that survived everything (empty on success).

    The ladder, quietest rung first:

      1. Just delete it. On POSIX this is the whole story -- unlinking an open
         file succeeds there, so nothing below ever runs. On Windows it is also
         the common case: usually nothing is holding anything.
      2. Ask WHO is blocking, and close exactly those. The Restart Manager
         names the processes holding the surviving files (authoritative -- see
         winlocks); a scoped search covers the working-directory case it can't
         see. Only those pids are closed, and the user is told which.
      3. Sledgehammer. Every Python/VS Code process on the machine, the old
         unconditional behaviour, now reached only when the targeted step
         failed to free the tree.

    The point of the ordering is that the destructive rungs are reached on
    evidence rather than on suspicion. `seed remove-venv scratch` used to close
    every editor window on the machine before it had established that anything
    was wrong; now it closes nothing at all unless a delete actually fails."""
    from . import winlocks
    from .commands import kill_cmd

    what = f" ({label})" if label else ""

    failures = robust_rmtree(path)
    if not failures:
        return []

    # --- rung 2: identify and close only the actual blockers ---------------
    holders = winlocks.holders(failures)
    scoped: list[tuple[int, str]] = []
    if not holders:
        # Nothing holds a HANDLE -- so a working directory inside the tree is
        # the likely blocker, which Restart Manager cannot report.
        scoped = kill_cmd.find_seedling_processes(str(path))

    blockers = holders or scoped
    if blockers:
        on_message(f"Something is holding files{what}: "
                   f"{winlocks.describe(blockers)}")
        on_message("Closing just those...")
        kill_cmd.terminate([pid for pid, _ in blockers])
        failures = robust_rmtree(path)
        if not failures:
            return []

    if not allow_sledgehammer:
        return failures

    # --- rung 3: last resort ------------------------------------------------
    on_message("Still blocked. Force-closing all Python and VS Code "
               "processes as a last resort...")
    kill_cmd.kill_python_and_vscode()
    return robust_rmtree(path)


def failures_are_only_running_cli(failures: list[str], home: Path) -> bool:
    """True when everything robust_rmtree couldn't delete is seedling's own
    currently-running program -- the seed-cli shim in system/bin and the
    tool venv (whose python.exe is literally executing this code) -- plus
    the directories those files keep non-empty. That's not an error the
    user can fix by closing something; it's inherent to a program deleting
    itself, and the caller should hand off to schedule_deferred_delete()."""
    home_str = str(home)
    for f in failures:
        p = Path(f)
        try:
            if os.path.commonpath([home_str, f]) != home_str:
                return False
        except ValueError:  # different drives
            return False
        if p.is_dir():
            continue
        rel = os.path.relpath(f, home_str).replace("\\", "/").lower()
        if rel.startswith("system/bin/seed-cli") or rel.startswith("system/tool/"):
            continue
        return False
    return True


def schedule_deferred_delete(path: Path) -> None:
    """Finish deleting `path` a moment AFTER this process exits, from a
    detached helper process -- the only way a program can remove its own
    running executable. Tries twice with a pause in between, in case the
    process takes a beat to fully exit."""
    if os.name == "nt":
        # A real .bat file avoids the nested-quoting minefield of passing a
        # compound command through CreateProcess to cmd.exe. `ping -n` is
        # the classic batch sleep (`timeout` refuses to run without an
        # interactive stdin); the last line is the standard batch
        # self-delete idiom, so the helper cleans itself up too.
        import tempfile
        bat = Path(tempfile.gettempdir()) / f"seedling-cleanup-{os.getpid()}.bat"
        bat.write_text(
            "@echo off\r\n"
            "ping -n 3 127.0.0.1 >nul\r\n"
            f'rmdir /s /q "{path}"\r\n'
            "ping -n 3 127.0.0.1 >nul\r\n"
            f'rmdir /s /q "{path}"\r\n'
            '(goto) 2>nul & del "%~f0"\r\n'
        )
        # CREATE_NO_WINDOW, not DETACHED_PROCESS: a detached (console-less)
        # cmd.exe causes every console child it launches (the `ping` sleeps)
        # to get a fresh VISIBLE console -- windows flashing at the user
        # right after a purge. A hidden console is inherited by the
        # children, so the whole cleanup runs invisibly.
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        # The marker file lets the `seed` shell function (the only thing
        # still alive in the user's terminal after purge) detect that a
        # cleanup is pending, wait for it, and confirm the result. On
        # Windows the .bat file itself plays that role -- it self-deletes
        # when finished.
        import tempfile
        marker = Path(tempfile.gettempdir()) / "seedling-cleanup.pending"
        try:
            marker.write_text(str(path))
        except OSError:
            pass
        subprocess.Popen(
            ["sh", "-c",
             'sleep 2; rm -rf "$1"; sleep 2; rm -rf "$1"; rm -f "$2"',
             "sh", str(path), str(marker)],
            start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


def _escape_if_inside(path: Path) -> None:
    """If the current process's cwd is inside (or is) `path`, move out of
    it first -- otherwise Windows will refuse to delete that directory."""
    safe = str(Path.home())
    try:
        current = Path.cwd().resolve()
    except OSError:
        # cwd is already invalid for some reason; just try to land somewhere sane
        try:
            os.chdir(safe)
        except OSError:
            pass
        return

    resolved_target = path.resolve()
    if current == resolved_target or resolved_target in current.parents:
        try:
            os.chdir(safe)
        except OSError:
            pass
