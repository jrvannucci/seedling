"""
`seed purge` -- the nuclear option. Unlike `seed remove-user` (which only
deletes what's under ~/seedling but leaves the `seed` shell hook installed,
so a fresh `seed update-commands`/reinstall can pick back up cleanly),
`seed purge` also strips the shell hook from every shell profile it can
find. After this, `seed` stops existing as a command entirely -- this is
the same end state as running uninstall.sh/uninstall.ps1, just reachable
from inside `seed` itself.

`seed purge-and-reinstall` runs that same wipe, then reinstalls seedling
from the source the original install recorded (`update_source`). Because a
program can't delete-then-relaunch its own executable, this command only
writes a self-contained reinstall script to a temp path (surviving the
wipe); the `seed` shell FUNCTION -- still loaded in the user's terminal --
runs it once the wipe is confirmed. Cloned repos are always moved aside
first and restored into the fresh install. Both entry points share run().
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from .. import colors, config, confirm, fsutil, git_tool, paths, runlog
from . import kill_cmd

_BACKUP_NAME_RE = re.compile(r"^seedling-repo-backup(-\d+)?$")

# Shown before confirming and again after a successful purge -- once `seed`
# is gone, this screen is the last place the user will see these. Must
# match the installers' baked-in default so a public-GitHub install is
# recognized as such.
_PUBLIC_REPO = "https://github.com/cryocliff/seedling.git"

_PUBLIC_REINSTALL_LINES = [
    "  macOS/Linux:  curl -fsSL https://raw.githubusercontent.com/cryocliff/seedling/main/installers/install.sh | sh",
    "  PowerShell:   irm https://raw.githubusercontent.com/cryocliff/seedling/main/installers/install.ps1 | iex",
]


def _print_reinstall(update_source) -> None:
    """Reinstall instructions matched to how THIS copy was installed
    (recorded as `update_source` at install time): the public one-liners
    only fit a public-GitHub install; a network-share install reinstalls
    from the share, and a self-hosted-git install by cloning that URL --
    pointing those users at github.com would be wrong (and, on an isolated
    network, impossible)."""
    print("To reinstall seedling later:")
    source = str(update_source) if update_source else ""

    if not source or source == _PUBLIC_REPO:
        for line in _PUBLIC_REINSTALL_LINES:
            print(line)
        return

    is_url = "://" in source or source.startswith("git@")
    if is_url:
        print(f"  this copy was installed from {source} -- clone it and run the installer:")
        print(f'    git clone "{source}" seedling')
        print("    then, inside the clone:  install.cmd   (Windows)")
        print("                             sh ./install.cmd   (macOS/Linux)")
    else:
        sep = "\\" if ("\\" in source or re.match(r"^[A-Za-z]:", source)) else "/"
        print(f"  this copy was installed from {source} -- run the installer there again:")
        print(f"    Windows:      {source}{sep}install.cmd   (double-clicking it also works)")
        print(f"    macOS/Linux:  sh {source}{sep}install.cmd")

_PARTIAL_REMOVE_LINES = [
    "  seed remove-venv <name>    delete one venv",
    "  seed remove-venv-all       delete all venvs",
    "  seed remove-python <tag>   delete a base Python and the venvs built from it",
    "  seed remove-repo <name>    delete one cloned repo",
    "  seed remove-user           delete everything under ~/seedling, but keep the",
    "                             `seed` command hook so a reinstall picks right back up",
]


def _candidate_profiles() -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".zshrc",
        home / ".bashrc",
        home / ".bash_profile",
        home / ".profile",
        # PowerShell profile locations (checked on every OS since PowerShell
        # itself is cross-platform; harmless no-ops where they don't exist)
        home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
        home / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1",
    ]
    return candidates


def _is_hook_line(line: str) -> bool:
    """Any line that dot-sources a seed shell script from under the seedling
    home -- deliberately matching on the home dir plus the script name
    rather than the exact current hook text, so hooks written by OLDER
    seedling layouts (e.g. ~/seedling/shell/ before it moved under
    system/) are cleaned up too. A stale survivor here means every new
    shell greets the user with a 'file not found' error after a purge."""
    if line.strip() == "# seedling":
        return True
    return str(paths.HOME) in line and ("seed.ps1" in line or "seed.sh" in line)


def _strip_hook(profile: Path) -> bool:
    if not profile.exists():
        return False
    try:
        lines = profile.read_text().splitlines()
    except OSError:
        return False

    new_lines = [line for line in lines if not _is_hook_line(line)]

    if new_lines == lines:
        return False

    try:
        profile.write_text("\n".join(new_lines).rstrip() + "\n" if new_lines else "")
    except OSError:
        return False
    return True


def _has_repos() -> bool:
    return paths.REPO_DIR.exists() and any(paths.REPO_DIR.iterdir())


def _move_repos_to_safety() -> Path:
    """Moves ~/seedling/repo out to a sibling folder in the user's home
    directory, so it survives `shutil.rmtree`-ing everything else under
    ~/seedling. Picks a non-colliding name if run more than once."""
    base = Path.home() / "seedling-repo-backup"
    dest = base
    n = 1
    while dest.exists():
        dest = Path(f"{base}-{n}")
        n += 1
    shutil.move(str(paths.REPO_DIR), str(dest))
    return dest


def _existing_backups() -> list[Path]:
    """Backup folders left behind by previous `seed purge --keep-repos` runs
    (~/seedling-repo-backup, -1, -2, ...). Without --keep-repos this time,
    the user has said they don't want cloned repos kept around at all, so
    these stale backups get cleaned up too instead of accumulating forever."""
    home = Path.home()
    return sorted(
        p for p in home.iterdir()
        if p.is_dir() and _BACKUP_NAME_RE.match(p.name)
    )


def _reinstall_marker() -> Path:
    """Fixed temp path the reinstall script is written to -- the same
    convention the `seed` shell function looks for after a wipe. Kept in the
    system temp dir (tempfile.gettempdir(), matching the deferred-delete
    marker in fsutil) so it survives deleting ~/seedling itself. Platform
    picks the flavor the matching shell function knows how to run."""
    name = "seedling-reinstall.ps1" if os.name == "nt" else "seedling-reinstall.sh"
    return Path(tempfile.gettempdir()) / name


def _write_reinstall_script(source: str, repo_backup: Path | None) -> Path:
    """Write a self-contained script that reinstalls seedling from `source`
    (mirroring install.sh's own source resolution: run a directory's
    installer in place, or clone a URL first), then restores cloned repos
    from `repo_backup` into the fresh install. Passing SEEDLING_REPO=<source>
    makes the installer record the same source again as `update_source`, so a
    reinstalled copy updates from where the original did."""
    marker = _reinstall_marker()
    dest = str(paths.REPO_DIR)
    is_url = "://" in source or source.startswith("git@")

    if os.name == "nt":
        src = source.replace("'", "''")
        backup = str(repo_backup).replace("'", "''") if repo_backup else ""
        dest_ps = dest.replace("'", "''")
        lines = [
            "# Generated by `seed purge-and-reinstall`. Reinstalls seedling,",
            "# then restores cloned repos. Safe to delete.",
            "$ErrorActionPreference = 'Stop'",
            f"$Src = '{src}'",
        ]
        if is_url:
            lines += [
                "$Tmp = Join-Path $env:TEMP ('seedling-reinstall-src-' + [guid]::NewGuid().ToString('N'))",
                'Write-Host "Cloning $Src ..."',
                "git clone --depth 1 $Src (Join-Path $Tmp 'seedling')",
                "$env:SEEDLING_REPO = $Src",
                "& (Join-Path $Tmp 'seedling\\installers\\install.ps1')",
                "Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue",
            ]
        else:
            lines += [
                "$env:SEEDLING_REPO = $Src",
                "& (Join-Path $Src 'installers\\install.ps1')",
            ]
        if backup:
            lines += [
                f"$Backup = '{backup}'",
                f"$Dest = '{dest_ps}'",
                "if (Test-Path $Backup) {",
                "    New-Item -ItemType Directory -Force -Path $Dest | Out-Null",
                "    Get-ChildItem -Force -Path $Backup | ForEach-Object {",
                "        Move-Item -Force $_.FullName -Destination $Dest",
                "    }",
                "    Remove-Item -Force $Backup -ErrorAction SilentlyContinue",
                '    Write-Host "Restored your cloned repos into $Dest."',
                "}",
            ]
        marker.write_text("\r\n".join(lines) + "\r\n")
    else:
        src = source.replace("'", "'\\''")
        backup = str(repo_backup).replace("'", "'\\''") if repo_backup else ""
        dest_sh = dest.replace("'", "'\\''")
        lines = [
            "#!/bin/sh",
            "# Generated by `seed purge-and-reinstall`. Reinstalls seedling,",
            "# then restores cloned repos. Safe to delete.",
            "set -e",
            f"SRC='{src}'",
        ]
        if is_url:
            lines += [
                'TMP=$(mktemp -d)',
                'echo "Cloning $SRC ..."',
                'git clone --depth 1 "$SRC" "$TMP/seedling"',
                'SEEDLING_REPO="$SRC" sh "$TMP/seedling/installers/install.sh"',
                'rm -rf "$TMP"',
            ]
        else:
            lines += [
                'SEEDLING_REPO="$SRC" sh "$SRC/installers/install.sh"',
            ]
        if backup:
            lines += [
                f"BACKUP='{backup}'",
                f"DEST='{dest_sh}'",
                'if [ -d "$BACKUP" ]; then',
                '    mkdir -p "$DEST"',
                '    for d in "$BACKUP"/* "$BACKUP"/.[!.]*; do',
                '        [ -e "$d" ] || continue',
                '        mv "$d" "$DEST"/ 2>/dev/null || true',
                '    done',
                '    rmdir "$BACKUP" 2>/dev/null || true',
                '    echo "Restored your cloned repos into $DEST."',
                'fi',
            ]
        marker.write_text("\n".join(lines) + "\n")

    return marker


def run(args) -> int:
    home = paths.HOME
    reinstall = getattr(args, "command", None) == "purge-and-reinstall"
    # purge-and-reinstall always preserves cloned repos (moved aside, then
    # restored into the fresh install); plain purge honors --keep-repos.
    keep_repos = True if reinstall else getattr(args, "keep_repos", False)
    old_backups = [] if keep_repos else _existing_backups()
    # Read this before anything is deleted -- it's needed for the reinstall
    # instructions printed at the very end, when the config file is gone.
    update_source = config.get("update_source")

    # purge-and-reinstall needs a source to reinstall FROM. Prefer the one
    # this install recorded; if none was ever recorded, offer the public repo
    # (but never guess silently -- an org/offline install pointed elsewhere).
    reinstall_source = str(update_source) if update_source else ""
    if reinstall and not reinstall_source and not confirm.preview_requested(args):
        if not confirm.confirm(
                args, "No update source is recorded. Reinstall from the public "
                "repo (github.com/cryocliff/seedling)?"):
            print("Aborted. Nothing was removed.")
            print("Record where to reinstall from first, then re-run:")
            print("  seed config set update_source <git-url-or-directory>")
            return 1
        reinstall_source = _PUBLIC_REPO

    if confirm.preview_requested(args):
        items = []
        if home.exists():
            items += sorted(str(p) for p in home.iterdir())
        items += [f"{p}  (shell hook line removed)"
                  for p in _candidate_profiles() if p.exists()]
        items += [f"{p}  (leftover backup from a previous --keep-repos purge)"
                  for p in old_backups]
        notes = ["any running Python/VS Code processes will be force-closed "
                 "first (not just seedling's) so nothing blocks deletion"]
        if reinstall:
            where = reinstall_source or "the public repo (after confirming, since none is recorded)"
            notes.append(f"seedling would then be reinstalled from {where}")
            if _has_repos():
                notes.append(f"{paths.REPO_DIR} would be moved to safety first, "
                             "then restored into the fresh install")
        else:
            notes.append("after a real run, `seed` stops working entirely")
            if keep_repos and _has_repos():
                notes.append(f"{paths.REPO_DIR} would be moved to safety first "
                             "(--keep-repos), not deleted")
        title = "wipe and reinstall seedling" if reinstall else "fully uninstall seedling"
        confirm.print_preview(title, items, notes=notes)
        # Only when the repos would actually be DELETED -- with --keep-repos
        # (and always for purge-and-reinstall) they're moved aside and restored,
        # so there's nothing at risk and a warning would just be noise.
        if not keep_repos:
            git_tool.warn_unsaved_work(git_tool.scan_for_unsaved_work(paths.REPO_DIR))
        return 0

    if not confirm.auto_confirmed(args) and reinstall:
        print()
        print(colors.danger("This wipes seedling and reinstalls it fresh.") + " It will:")
        print()
        print(f"  - delete {colors.bold('everything')} under {home}")
        print("    (base pythons, venvs, VS Code, uv, and seedling's own source)")
        print("  - remove, then re-add, the `seed` shell hook in your shell profile")
        print("  - force-close any running Python/VS Code processes first,")
        print("    not just seedling's, so nothing blocks deletion")
        print(f"  - reinstall seedling from {colors.bold(reinstall_source)}")
        print()
        if _has_repos():
            print(f"Your cloned repos ({paths.REPO_DIR}) are moved to safety first,")
            print("then restored into the fresh install -- they are not lost.")
            print()
        print(colors.warn("Everything else -- installed pythons, venvs, packages -- is gone "
                          "and rebuilt from scratch."))
        print()

    if not confirm.auto_confirmed(args) and not reinstall:
        print()
        print(colors.danger("This fully uninstalls seedling.") + " It will:")
        print()
        print(f"  - delete {colors.bold('everything')} under {home}")
        print("    (base pythons, venvs, VS Code, cloned repos, uv, and seedling's own source)")
        print("  - remove the `seed` shell hook from your shell profile")
        print("  - force-close any running Python/VS Code processes first,")
        print("    not just seedling's, so nothing blocks deletion")
        print()
        print(colors.warn("After this, `seed` stops working entirely -- you'd need to reinstall."))
        print()

        if not keep_repos and _has_repos():
            print(colors.header("Want to keep your cloned repos?") +
                  f" ({paths.REPO_DIR} has some.)")
            print("Abort now and re-run as `seed purge --keep-repos` -- they get moved")
            print(f"out to {Path.home() / 'seedling-repo-backup'} before everything else is deleted.")
            print()

        if old_backups:
            print("Note: also deleting leftover repo backup folder(s) from a previous "
                  "`seed purge --keep-repos` (this run isn't keeping repos, so these "
                  "won't be left behind either):")
            for p in old_backups:
                print(f"  - {p}")
            print()

        print(colors.header("Only need to remove part of seedling?") +
              " There are smaller hammers:")
        for line in _PARTIAL_REMOVE_LINES:
            print(line)
        print()

        _print_reinstall(update_source)
        print()

    # Deliberately OUTSIDE the interactive blocks above, so it is printed under
    # -y as well. It doesn't block: someone who passed -y asked for no prompts,
    # and turning that into a hard failure would break scripted teardowns -- but
    # the record of what was destroyed belongs in the output and the run log.
    # Only when repos are actually being deleted: --keep-repos and
    # purge-and-reinstall move them aside, so nothing is at risk there.
    if not keep_repos and _has_repos():
        git_tool.warn_unsaved_work(git_tool.scan_for_unsaved_work(paths.REPO_DIR))
        print()

    if not confirm.confirm(args):
        print("Aborted. Nothing was removed.")
        return 1
    print()

    print("Closing Python and VS Code processes so nothing is left in use...")
    killed = kill_cmd.kill_python_and_vscode()
    print(f"Closed {len(killed)} process(es)." if killed else "Nothing matching was running.")
    print()

    repo_backup = None
    if keep_repos and _has_repos():
        repo_backup = _move_repos_to_safety()
        print(f"Moved your cloned repos to {repo_backup} before deleting the rest.")
        print()

    # Stage the reinstall script OUTSIDE ~/seedling before the wipe, so it
    # survives. The still-loaded `seed` shell function runs it once the wipe
    # is confirmed (seed-cli can't relaunch its own just-deleted executable).
    if reinstall:
        _write_reinstall_script(reinstall_source, repo_backup)

    removed_from = [p for p in _candidate_profiles() if _strip_hook(p)]

    failures: list[str] = []

    if old_backups:
        print(f"Deleting {len(old_backups)} leftover repo backup folder(s) ...")
        for p in old_backups:
            failures.extend(fsutil.robust_rmtree(p))
        print()

    if home.exists():
        print(f"Deleting {home} ...")
        runlog.close_before_deleting_home()
        failures.extend(fsutil.robust_rmtree(home))

    print()
    if removed_from:
        print("Removed the seedling shell hook from:")
        for p in removed_from:
            print(f"  - {p}")
    else:
        print("No shell hook found in the usual profile locations.")
        print("(Nothing to clean up there, or it lives somewhere this command doesn't check.)")

    if failures and fsutil.failures_are_only_running_cli(failures, home):
        # The only survivors are seedling's own running program (the
        # seed-cli shim and the tool venv python executing this very
        # command) -- Windows can't delete a running executable, so hand
        # the last few files to a detached helper that runs after exit.
        fsutil.schedule_deferred_delete(home)
        print()
        print("The only files left are seedling's own running program, which")
        print("can't delete itself while it's still running. A background")
        print("cleanup removes them automatically a moment after this")
        print("command exits -- your terminal will confirm once it's done.")
        failures = []
    elif failures:
        print()
        print(colors.warn("Some files under seedling could not be removed after several attempts:"))
        for f in failures:
            print(f"  - {f}")
        print()
        print("These are usually held open by something outside Python/VS Code.")
        cmd = "purge-and-reinstall" if reinstall else "purge"
        print(f"Close whatever has them open and run `seed {cmd}` again.")
        # A staged reinstall must not run against a half-deleted tree.
        if reinstall:
            _reinstall_marker().unlink(missing_ok=True)
        return 1

    if reinstall:
        # The wipe is done (or scheduled, on Windows). The `seed` shell
        # function takes over from here: it waits for any deferred cleanup,
        # then runs the reinstall script staged above -- visibly, in this
        # terminal. Nothing more for seed-cli to do; it's about to be gone.
        print()
        print(colors.ok("seedling has been wiped -- reinstalling now."))
        print(f"Reinstalling from {reinstall_source}. Your shell takes over below.")
        if repo_backup:
            print("Your cloned repos will be restored into the fresh install.")
        return 0

    print()
    print(colors.ok("seedling has been fully uninstalled."))
    if repo_backup:
        print()
        print(f"Your cloned repos are safe at {repo_backup}.")
        print("Move them wherever you'd like -- seedling won't touch that folder again.")
    print()
    _print_reinstall(update_source)
    return 0
