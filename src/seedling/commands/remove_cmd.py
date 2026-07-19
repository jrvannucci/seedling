from __future__ import annotations

from .. import colors, confirm, fsutil, git_tool, paths, runlog
from . import kill_cmd


def run(args) -> int:
    home = paths.HOME
    if not home.exists():
        print(f"Nothing to remove; {home} does not exist.")
        return 0

    if confirm.preview_requested(args):
        top_level = sorted(str(p) for p in home.iterdir())
        confirm.print_preview(
            f"delete everything under {home}",
            top_level,
            notes=["any running Python/VS Code processes will be force-closed "
                   "first (not just seedling's) so nothing blocks deletion",
                   "the `seed` shell hook stays installed (use `seed purge` "
                   "to remove that too)"],
        )
        git_tool.warn_unsaved_work(git_tool.scan_for_unsaved_work(paths.REPO_DIR))
        return 0

    if not confirm.auto_confirmed(args):
        print()
        print(colors.danger("This deletes EVERYTHING under") + f" {home}")
        print("(all base pythons, venvs, VS Code, cloned repos, and its extensions/settings).")
        print()
        print("It will also force-close any running Python and VS Code processes first")
        print("(not just seedling's) to make sure nothing is left in use.")
        print()
    # Outside the block above so it is printed under -y too. It reports rather
    # than blocks -- see the same note in purge_cmd.
    git_tool.warn_unsaved_work(git_tool.scan_for_unsaved_work(paths.REPO_DIR))
    if not confirm.confirm(args):
        print("Aborted. Nothing was deleted.")
        return 1
    print()

    print("Closing Python and VS Code processes so nothing is left in use...")
    killed = kill_cmd.kill_python_and_vscode()
    print(f"Closed {len(killed)} process(es)." if killed else "Nothing matching was running.")
    print()

    print(f"Deleting {home} ...")
    runlog.close_before_deleting_home()
    failures = fsutil.robust_rmtree(home)

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
    elif failures:
        print()
        print(colors.warn("Some files could not be removed after several attempts:"))
        for f in failures:
            print(f"  - {f}")
        print()
        print("These are usually held open by something outside Python/VS Code")
        print("(a file explorer window, an editor, antivirus/indexing).")
        print("Close whatever has them open and run `seed remove-user` again.")
        return 1

    print()
    print(colors.ok("Done.") + " seedling has been fully removed from your user directory.")
    print()
    print("Note: the `seed` shell function/alias itself is still in your shell profile.")
    print("Run `seed purge` instead next time for a full clean removal, or")
    print("run the uninstaller (uninstall.cmd -- or `sh uninstall.cmd` on")
    print("macOS/Linux) to just remove the shell hook now.")
    return 0
