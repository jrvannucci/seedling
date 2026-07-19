"""
Shared machinery for the `admin-*` command family: cross-user teardown of a
shared-root install (SEEDLING_HOME_DIR="<root>/{user}").

These operations reach into OTHER users' folders, so two things separate
them from the ordinary per-user commands:

1. They require elevation (Administrator on Windows, root on POSIX). A
   normal user cannot -- and must not be able to -- delete another user's
   protected files.
2. Before deleting, they defeat the other user's ACLs: on Windows via
   `takeown` + `icacls` (seize ownership, grant Administrators full
   control), on POSIX by virtue of running as root. This is what makes the
   teardown actually complete despite user-owned, read-only, or
   runtime-generated files (see docs/DEPLOYMENT.md, "Admin commands").
"""

from __future__ import annotations

import os
import subprocess

from pathlib import Path

from . import colors, config, fsutil


def is_elevated() -> bool:
    """True when the current process can act on other users' files."""
    if os.name == "nt":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def require_elevation() -> bool:
    """Gate every admin command. Prints how to elevate and returns False
    when not elevated."""
    if is_elevated():
        return True
    if os.name == "nt":
        print(colors.danger("This is an admin command.") +
              " It touches other users' files, so it must run elevated.")
        print("Open an Administrator PowerShell (right-click -> Run as "
              "administrator) and run it again.")
    else:
        print(colors.danger("This is an admin command.") +
              " It touches other users' files, so it must run as root.")
        print("Re-run it with sudo, e.g.:  sudo seed <command>")
    return False


def shared_root():
    """The directory that holds per-user seedling homes, or None if this
    isn't a shared multi-user install. Recorded at install time ONLY when
    SEEDLING_HOME_DIR used a {user} token -- so a plain ~/seedling never
    looks like a shared root by accident."""
    value = config.get("shared_root")
    return Path(value) if value else None


def require_shared_root():
    """Gate for the admin family: returns the root, or None (with a clear
    message) when this install isn't a shared {user} deployment."""
    root = shared_root()
    if root is None:
        print(colors.warn("This isn't a shared multi-user install."))
        print("The admin commands manage a deployment where SEEDLING_HOME_DIR "
              "used a {user} token (e.g. C:\\seedling\\{user}), so each user "
              "has a sibling folder under one root. This install doesn't.")
        return None
    return root


def _looks_like_home(path) -> bool:
    return path.is_dir() and (path / "system").exists()


def resolve_user_home(user: str):
    """The seedling home of another user under the shared root, or None."""
    root = shared_root()
    if root is None:
        return None
    candidate = root / user
    return candidate if _looks_like_home(candidate) else None


def list_user_homes() -> list:
    """Every per-user seedling home under the shared root, sorted."""
    root = shared_root()
    if root is None or not root.exists():
        return []
    return sorted(d for d in root.iterdir() if _looks_like_home(d))


def user_name_of(home) -> str:
    return home.name


def take_ownership(path) -> None:
    """Seize ownership / grant delete rights so a subsequent delete can
    remove files owned by other users. Best-effort and quiet: any failure
    just means the delete below reports whatever it still can't remove.
    No-op on POSIX (running as root already bypasses ownership)."""
    if os.name != "nt" or not path.exists():
        return
    _run_quiet(["takeown", "/f", str(path), "/r", "/d", "Y"])
    # S-1-5-32-544 = the built-in Administrators group, locale-independent.
    _run_quiet(["icacls", str(path), "/grant", "*S-1-5-32-544:F", "/t", "/c", "/q"])


def _run_quiet(cmd) -> None:
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       stdin=subprocess.DEVNULL, check=False)
    except OSError:
        pass


def force_delete(path) -> list:
    """Take ownership, then delete -- a file (e.g. an alias.json) or a whole
    directory tree. Returns paths that still couldn't be removed (empty on
    success)."""
    if not path.exists() and not path.is_symlink():
        return []
    take_ownership(path)
    if path.is_dir():
        return fsutil.robust_rmtree(path)
    # single file: clear the read-only bit (Windows won't delete otherwise)
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    try:
        path.unlink()
        return []
    except OSError:
        return [str(path)]


# --- cross-user shell-hook cleanup (for admin-purge-all-users) --------------

def all_user_profiles() -> list:
    """Every shell profile on the machine that might carry a seedling hook,
    across all users. Windows: each C:\\Users\\<name> profile. POSIX: each
    /home/<name> (and /root) rc file. Best-effort -- unreadable ones are
    skipped by the caller."""
    profiles = []
    if os.name == "nt":
        users_root = Path_C_Users()
        if users_root and users_root.exists():
            for udir in users_root.iterdir():
                if not udir.is_dir():
                    continue
                for rel in (
                    "Documents/PowerShell/Microsoft.PowerShell_profile.ps1",
                    "Documents/WindowsPowerShell/Microsoft.PowerShell_profile.ps1",
                ):
                    profiles.append(udir / rel)
    else:
        import glob
        homes = glob.glob("/home/*") + ["/root"]
        for h in homes:
            for rc in (".bashrc", ".zshrc", ".profile", ".bash_profile"):
                from pathlib import Path
                profiles.append(Path(h) / rc)
    return profiles


def Path_C_Users():
    """The Users root that siblings the current user's OS home (usually
    C:\\Users). Derived from Path.home() so it works under test overrides."""
    from pathlib import Path
    return Path.home().parent
