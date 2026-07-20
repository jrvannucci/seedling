"""
`seed kill-processes` -- an escape hatch for when a venv, a runaway script, or
VS Code itself is stuck and you just want a clean slate.

Scoped by DEFAULT to processes belonging to the seedling tree; `--system` is
the machine-wide sledgehammer, and a bare process name closes just that name.
The default is the narrow one because "something of mine is stuck" shouldn't
close a colleague's editor or an unrelated long-running job.

"Belonging to seedling" is decided by LOCATION -- executable path, command
line, or working directory under the seedling home -- never by process name.
Name matching is wrong in both directions: it hits unrelated system Pythons,
and it misses the processes that matter most, like a PyQt app's
QtWebEngineProcess.exe or a node/ffmpeg binary bundled inside a venv, which
are named nothing like Python but live inside the tree.

Deliberately uses only OS-builtin tools (pgrep/kill on macOS+Linux, taskkill
and WMI on Windows) rather than a third-party dependency like psutil, to stay
consistent with seedling's "nothing pre-installed required" design.

Always excludes seedling's own running process (and its parent) so it can't
kill itself mid-cleanup on platforms where seed-cli's own process image is
literally a python interpreter.
"""

from __future__ import annotations

import os
import platform
import signal
import subprocess

from .. import colors, confirm

PYTHON_PROCESS_NAMES_UNIX = [
    "python", "python3",
    "python3.8", "python3.9", "python3.10", "python3.11",
    "python3.12", "python3.13", "python3.14",
    "pythonw",
]
VSCODE_PROCESS_NAMES_UNIX = [
    "code", "Code",
    "Code Helper", "Code Helper (Renderer)", "Code Helper (GPU)", "Code Helper (Plugin)",
    "Electron",
]

WINDOWS_PYTHON_IMAGES = ["python.exe", "pythonw.exe", "py.exe"]
WINDOWS_VSCODE_IMAGES = ["Code.exe"]


def _under(path: str | None, root: str) -> bool:
    if not path:
        return False
    try:
        return os.path.normcase(os.path.abspath(path)).startswith(
            os.path.normcase(os.path.abspath(root)).rstrip("\\/") + os.sep)
    except (OSError, ValueError):
        return False


def _windows_scoped(root: str, exclude: set[int]) -> list[tuple[int, str]]:
    """Processes whose executable or command line sits under `root`, via WMI.

    This is the FALLBACK for what the Restart Manager can't see -- chiefly a
    process whose working directory is inside the tree, which blocks directory
    removal without holding any file handle. It is a heuristic, so it is only
    ever used after the authoritative check has come up empty."""
    script = (
        "Get-CimInstance Win32_Process | "
        "ForEach-Object { \"$($_.ProcessId)`t$($_.Name)`t$($_.ExecutablePath)`t$($_.CommandLine)\" }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    found: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or not parts[0].strip().isdigit():
            continue
        pid = int(parts[0].strip())
        name, exe, cmdline = parts[1].strip(), parts[2].strip(), parts[3]
        if pid in exclude:
            continue
        if _under(exe, root) or (root.lower() in (cmdline or "").lower()):
            found.append((pid, name))
    return found


def _unix_scoped(root: str, exclude: set[int]) -> list[tuple[int, str]]:
    """Same idea on POSIX, via /proc where available. Only used by
    `--diagnose`-style reporting: POSIX deletes open files happily, so nothing
    here is needed to make a removal succeed."""
    found: list[tuple[int, str]] = []
    proc = "/proc"
    if not os.path.isdir(proc):
        return found
    for entry in os.listdir(proc):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid in exclude:
            continue
        base = os.path.join(proc, entry)
        try:
            exe = os.readlink(os.path.join(base, "exe"))
        except OSError:
            exe = None
        try:
            cwd = os.readlink(os.path.join(base, "cwd"))
        except OSError:
            cwd = None
        try:
            with open(os.path.join(base, "cmdline"), "rb") as f:
                cmdline = f.read().decode("utf-8", "replace").replace("\0", " ")
        except OSError:
            cmdline = ""
        if _under(exe, root) or _under(cwd, root) or root in cmdline:
            found.append((pid, os.path.basename(exe) if exe else f"pid {pid}"))
    return found


def find_seedling_processes(root: str | None = None) -> list[tuple[int, str]]:
    """[(pid, name)] for processes tied to the seedling tree -- by executable
    location, command line, or working directory.

    Scoped on purpose: it does NOT match by process name, so an unrelated
    system Python or a VS Code window on another project is left alone, while
    oddly-named children living inside a venv (a PyQt app's
    QtWebEngineProcess.exe, a bundled node/ffmpeg) ARE caught."""
    from .. import paths as _paths
    root = str(root or _paths.HOME)
    exclude = _self_and_parent()
    if platform.system() == "Windows":
        return _windows_scoped(root, exclude)
    return _unix_scoped(root, exclude)


def terminate(pids: list[int]) -> list[int]:
    """Force-close specific pids. Returns those actually signalled."""
    killed: list[int] = []
    exclude = _self_and_parent()
    for pid in pids:
        if pid in exclude:
            continue
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    killed.append(pid)
            else:
                os.kill(pid, signal.SIGKILL)
                killed.append(pid)
        except (ProcessLookupError, OSError):
            pass
        except PermissionError:
            print(f"  (skipped pid {pid}: permission denied)")
    return killed


def _self_and_parent() -> set[int]:
    pids = {os.getpid()}
    try:
        pids.add(os.getppid())
    except OSError:
        pass
    return pids


def _pgrep(name: str) -> list[int]:
    try:
        result = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []
    return [int(line) for line in result.stdout.split() if line.isdigit()]


def _kill_unix(names: list[str], exclude: set[int]) -> list[int]:
    killed: list[int] = []
    seen: set[int] = set()
    for name in names:
        for pid in _pgrep(name):
            if pid in exclude or pid in seen:
                continue
            seen.add(pid)
            try:
                os.kill(pid, signal.SIGKILL)
                killed.append(pid)
            except ProcessLookupError:
                pass
            except PermissionError:
                print(f"  (skipped pid {pid}: permission denied)")
    return killed


def _kill_windows(images: list[str], exclude: set[int]) -> list[str]:
    killed: list[str] = []
    for image in images:
        cmd = ["taskkill", "/F", "/IM", image]
        for pid in exclude:
            cmd += ["/FI", f"PID ne {pid}"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        # taskkill exits 0 only if it actually terminated something
        if result.returncode == 0:
            killed.append(image)
    return killed


def _list_windows(images: list[str], exclude: set[int]) -> list[str]:
    """What would be killed: 'image (pid N)' entries, via tasklist."""
    found: list[str] = []
    for image in images:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, check=False,
        )
        for line in result.stdout.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit() and int(parts[1]) not in exclude:
                found.append(f"{parts[0]} (pid {parts[1]})")
    return found


def _list_unix(names: list[str], exclude: set[int]) -> list[str]:
    found: list[str] = []
    seen: set[int] = set()
    for name in names:
        for pid in _pgrep(name):
            if pid in exclude or pid in seen:
                continue
            seen.add(pid)
            found.append(f"{name} (pid {pid})")
    return found


# Sentinel for "the machine-wide sweep" -- deliberately not a string, so
# it can never be confused with a process NAME a user passed in. It used
# to be the literal "all", which meant `kill-processes all` reached the
# machine-wide branch even after that spelling was removed.
SYSTEM_WIDE = object()


def list_matching(target) -> list[str]:
    """Human-readable list of the processes a kill would hit right now.

    `target` is a process name, or SYSTEM_WIDE for the whole machine."""
    exclude = _self_and_parent()
    if platform.system() == "Windows":
        if target is SYSTEM_WIDE:
            images = WINDOWS_PYTHON_IMAGES + WINDOWS_VSCODE_IMAGES
        else:
            images = [target if target.lower().endswith(".exe") else f"{target}.exe"]
        return _list_windows(images, exclude)
    names = (PYTHON_PROCESS_NAMES_UNIX + VSCODE_PROCESS_NAMES_UNIX
             if target is SYSTEM_WIDE else [target])
    return _list_unix(names, exclude)


def kill_python_and_vscode() -> list:
    """Force-closes every Python/VS Code process, sparing seedling's own.
    Shared by `seed kill-processes --system` and `seed remove-user` (which uses
    this to release any file locks before deleting ~/seedling)."""
    exclude = _self_and_parent()
    if platform.system() == "Windows":
        return _kill_windows(WINDOWS_PYTHON_IMAGES + WINDOWS_VSCODE_IMAGES, exclude)
    return _kill_unix(PYTHON_PROCESS_NAMES_UNIX + VSCODE_PROCESS_NAMES_UNIX, exclude)


def kill_seedling_processes() -> list[tuple[int, str]]:
    """Close only the processes tied to the seedling tree. Returns what was
    actually closed, as (pid, name)."""
    found = find_seedling_processes()
    if not found:
        return []
    closed = set(terminate([pid for pid, _ in found]))
    return [(pid, name) for pid, name in found if pid in closed]


def run(args) -> int:
    """Three modes, narrowest first:

      seed kill-processes            only seedling's own processes  (default)
      seed kill-processes --system   every python/VS Code on the machine
      seed kill-processes <name>     every process named <name>

    The default is scoped because that is what an ordinary "something is
    stuck" actually calls for; closing a colleague's editor and every unrelated
    python job should take an explicit --system."""
    target = getattr(args, "target", None)
    system_wide = getattr(args, "system", False)

    if target and system_wide:
        print("error: give a process name OR --system, not both.")
        return 1

    if system_wide:
        description = "ALL Python and VS Code processes on this machine"
    elif target:
        description = f"all '{target}' processes on this machine"
    else:
        description = "seedling's own processes"

    if confirm.preview_requested(args):
        if system_wide:
            items = list_matching(SYSTEM_WIDE)
        elif target:
            items = list_matching(target)
        else:
            items = [f"{name} (pid {pid})"
                     for pid, name in find_seedling_processes()]
        confirm.print_preview(
            f"force-close {description}",
            items,
            notes=["processes are listed as of right now; a real run "
                   "re-matches at execution time"],
        )
        return 0

    if not confirm.auto_confirmed(args):
        print()
        if system_wide or target:
            print(colors.warn(f"This force-closes {description}") + " --")
            print("not just seedling's -- including any unsaved work.")
            print("Use `seed kill-processes` with no arguments to close only "
                  "seedling's.")
        else:
            print(f"This force-closes {description} " +
                  colors.warn("(anything running from a seedling venv or repo)") +
                  ",")
            print("including any unsaved work. Unrelated Python and editor "
                  "windows are left alone.")
        print()
    if not confirm.confirm(args):
        print("Aborted.")
        return 1
    print()

    print(f"Closing {description}...")

    if not system_wide and not target:
        closed = kill_seedling_processes()
        if closed:
            print(colors.ok(f"Closed {len(closed)} process(es): "
                            + ", ".join(f"{n} (pid {p})" for p, n in closed)))
        else:
            print("Nothing of seedling's was running.")
        return 0

    plat = platform.system()
    if system_wide:
        killed = kill_python_and_vscode()
    else:
        exclude = _self_and_parent()
        if plat == "Windows":
            image = target if target.lower().endswith(".exe") else f"{target}.exe"
            killed = _kill_windows([image], exclude)
        else:
            killed = _kill_unix([target], exclude)

    if not killed:
        print("Nothing matching was running.")
    elif plat == "Windows":
        print(colors.ok(f"Closed: {', '.join(killed)}"))
    else:
        print(colors.ok(f"Killed {len(killed)} process(es): "
                        + ", ".join(str(p) for p in killed)))
    return 0
