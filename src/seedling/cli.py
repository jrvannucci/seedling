from __future__ import annotations

import argparse
import subprocess
import sys

from . import __version__, colors, config, paths, runlog
from .commands import (
    activate_cmd,
    admin_cmd,
    config_cmd,
    deactivate_cmd,
    default_venv_cmd,
    download_cmd,
    install_cmd,
    kill_cmd,
    list_cmd,
    logs_viewer_cmd,
    purge_cmd,
    python_cmd,
    python_remove_cmd,
    remove_cmd,
    repo_cmd,
    status_cmd,
    summary_cmd,
    uninstall_cmd,
    update_cmd,
    venv_cmd,
    venv_remove_cmd,
    vscode_cmd,
)
from .uv_tool import UvNotFound

# (command, args-hint, description) -- grouped for the custom help layout.
# argparse's own auto-generated help lists every subcommand as one flat,
# alphabetized block, which stops being readable somewhere around a dozen
# commands. This groups them the way a person actually thinks about them.
_HELP_GROUPS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Seedling Status", [
        ("summary", "[--sizes] [--json]", "Show everything seedling has installed"),
        ("health-check", "", "Health-check the whole seedling install"),
        ("logs-viewer", "[--days N]", "Open the command logs in a browser"),
        ("where", "", "Print the seedling home directory"),
    ]),
    ("Python interpreters -- the base installs venvs are built from", [
        ("python", "[version]", "Install a base Python (newest stable if no version)"),
        ("python-list", "", "List installed base Python interpreters"),
    ]),
    ("Venvs & packages -- day-to-day environment work", [
        ("venv", "<name> [--python <tag>]", "Create a venv from a base Python"),
        ("venv-list", "", "List venvs, and which one is active"),
        ("activate", "<name>", "Activate a venv in this shell"),
        ("deactivate", "", "Deactivate the current venv"),
        ("venv-default", "[name]", "Show or set the venv new shells auto-activate"),
        ("install", "<package...>", "Install packages (uv pip install)"),
        ("uninstall", "<package...>", "Uninstall packages (uv pip uninstall)"),
        ("package-list", "", "List installed packages (uv pip list)"),
    ]),
    ("Offline utilities -- download wheels to carry to an air-gapped machine", [
        ("download-whl", "<package...>", "Download a package + its deps as wheels"),
        ("download-requirements", "<req.txt>", "Download a requirements file's wheels"),
    ]),
    ("Git repos", [
        ("repo-clone", "<git-url>", "Clone a repo into ~/seedling/repo"),
        ("repo-list", "", "List cloned repos"),
        ("repo-cd", "[name]", "cd into a cloned repo (or the repos folder)"),
        ("repo-vscode", "<name>", "Open a repo in VS Code"),
        ("repo-open", "[name]", "Open a repo in the file manager"),
        ("repo-install", "<name>", "Install a repo's dependencies into the active venv"),
    ]),
    ("VS Code", [
        ("vscode", "[path] [--reinstall]", "Install (once) and open VS Code"),
    ]),
    ("Utilities", [
        ("config", "[get|set|unset]", "View or change seedling settings"),
        ("kill-processes", "[name] [--system]", "Force-close seedling's processes (or all, or named)"),
        ("update-commands", "[--from-branch B]", "Update the seed CLI itself"),
    ]),
    ("Danger zone -- these delete things (all support --preview)", [
        ("remove-repo", "<name>", "Delete a cloned repo"),
        ("remove-venv", "<name>", "Delete a single venv"),
        ("remove-venv-all", "", "Delete every venv"),
        ("remove-python", "<tag>", "Delete a base Python and its venvs"),
        ("remove-user", "", "Delete everything seedling manages"),
        ("purge", "", "Full uninstall (also removes the shell hook)"),
        ("purge-and-reinstall", "", "Wipe seedling and reinstall it fresh from its original source"),
    ]),
]

# The admin family is hidden from normal help -- it's elevated, cross-user
# teardown of a shared-root install, not something a normal user runs.
# `seed help --admin` reveals it.
_ADMIN_HELP_GROUP: tuple[str, list[tuple[str, str, str]]] = (
    "Admin (elevated; shared-root installs) -- run as Administrator/root", [
        ("admin-purge-all-users", "", "Remove EVERY user's install under the shared root"),
        ("admin-remove-user", "<user>", "Remove one user's entire install"),
        ("admin-remove-venv", "<user> <name>", "Remove one user's venv"),
        ("admin-remove-venv-all", "<user>", "Remove all of one user's venvs"),
        ("admin-remove-python", "<user> <tag>", "Remove one user's base Python + its venvs"),
        ("admin-remove-repo", "<user> <name>", "Remove one user's cloned repo"),
    ],
)


def _print_group(title: str, commands) -> None:
    heading = colors.danger(title) if ("Danger" in title or "Admin" in title) else colors.header(title)
    print(heading)
    for name, args_hint, desc in commands:
        left = f"  {name} {args_hint}".rstrip()
        print(f"{left:<38} {colors.dim(desc)}")
    print()


def print_grouped_help(show_admin: bool = False) -> None:
    print(colors.bold("seed") + " -- a tidy, single-folder wrapper around uv")
    print()
    print("Usage: seed <command> [arguments]")
    print()
    for title, commands in _HELP_GROUPS:
        _print_group(title, commands)
    if show_admin:
        _print_group(*_ADMIN_HELP_GROUP)
        print("These take ownership of other users' files and must run "
              "elevated. See docs/DEPLOYMENT.md.")
    elif config.is_multi_user():
        # Only surface the admin family on installs where it actually
        # applies -- a shared multi-user deployment. On a normal per-user
        # install it would just be noise (and refuses to run anyway).
        print(colors.header("This is a shared multi-user install.") +
              " Managing it as an admin?")
        print("  Run " + colors.bold("seed help --admin") +
              " for the elevated commands that remove other users' installs.")
        print()
    print("Run any command with -h for its full options, e.g. `seed venv -h`.")
    print(f"seedling {__version__} -- `seed --version` prints this on its own.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seed",
        description="seedling: a tidy, single-folder wrapper around uv for "
                     "getting started with Python.",
    )
    parser.add_argument("-V", "--version", action="version",
                        version=f"seedling {__version__}",
                        help="Print seedling's version and exit")
    sub = parser.add_subparsers(dest="command")

    # Flags shared by every destructive command.
    danger = argparse.ArgumentParser(add_help=False)
    danger.add_argument("-y", "--yes", action="store_true",
                        help="Skip the confirmation prompt")
    danger.add_argument("--preview", action="store_true",
                        help="Show exactly what would be deleted/closed, "
                             "then exit without changing anything")
    danger.add_argument("--non-interactive", dest="non_interactive",
                        action="store_true",
                        help="Never wait for keyboard input: abort instead "
                             "of prompting (combine with -y to proceed). "
                             "SEEDLING_NONINTERACTIVE=1 does the same.")

    p_python = sub.add_parser("python", help="Install a base Python version")
    p_python.add_argument("version", nargs="?",
                           help="e.g. 312, 3.12, 3.12.4; omit to install "
                                "the newest stable version")

    p_remove_python = sub.add_parser(
        "remove-python", parents=[danger],
        help="Remove a base Python and any venvs built from it")
    p_remove_python.add_argument("tag", nargs="?", help="e.g. 312")

    p_venv = sub.add_parser("venv", help="Create a venv from a base Python")
    p_venv.add_argument("name", nargs="?", help="Name of the venv to create")
    p_venv.add_argument("--python", dest="python", default=None,
                         help="Base python tag to build from (defaults to "
                              "the first one installed)")
    p_venv.add_argument("--no-default-packages", "--bare",
                         dest="no_default_packages", action="store_true",
                         help="Don't install the default packages "
                              "(see `seed config get venv_default_packages`)")

    sub.add_parser("venv-list", help="List every venv seedling has created")
    sub.add_parser("python-list", help="List every base Python interpreter installed")

    p_activate = sub.add_parser("activate", help="Activate a venv")
    p_activate.add_argument("name", nargs="?", help="Name of the venv to activate")
    p_activate.add_argument("--print-path", dest="print_path", action="store_true",
                             help=argparse.SUPPRESS)  # used internally by the shell wrapper

    sub.add_parser("deactivate", help="Deactivate the current venv")

    p_default_venv = sub.add_parser(
        "venv-default", help="Show or set the venv every new shell auto-activates")
    p_default_venv.add_argument("name", nargs="?",
                                 help="Venv to auto-activate in new shells; "
                                      "omit to show the current one")

    p_install = sub.add_parser(
        "install", help="Install packages into the active venv (passthrough to `uv pip install`)")
    p_install.add_argument("packages", nargs=argparse.REMAINDER,
                            help="Anything after this is passed straight to `uv pip install`")

    p_uninstall = sub.add_parser(
        "uninstall", help="Uninstall packages from the active venv (passthrough to `uv pip uninstall`)")
    p_uninstall.add_argument("packages", nargs=argparse.REMAINDER,
                              help="Anything after this is passed straight to `uv pip uninstall`")

    p_list_packages = sub.add_parser(
        "package-list", help="List packages in the active venv (passthrough to `uv pip list`)")
    p_list_packages.add_argument("extra", nargs=argparse.REMAINDER,
                                  help="Anything after this is passed straight to `uv pip list`")

    p_dl_whl = sub.add_parser(
        "download-whl",
        help="Download a package and all its dependencies as wheels for an offline install")
    p_dl_whl.add_argument(
        "args", nargs=argparse.REMAINDER,
        help="<package...> plus any `pip download` flags (e.g. --platform, "
             "--python-version, --only-binary=:all:, --dest). Wheels land in "
             "./wheelhouse unless you pass your own --dest.")

    p_dl_req = sub.add_parser(
        "download-requirements",
        help="Download every package in a requirements file (+deps) as wheels for an offline install")
    p_dl_req.add_argument(
        "args", nargs=argparse.REMAINDER,
        help="<requirements.txt> plus any `pip download` flags. Wheels land "
             "in ./wheelhouse unless you pass your own --dest.")

    p_vscode = sub.add_parser("vscode", help="Install (if needed) and open VS Code")
    p_vscode.add_argument("path", nargs="?", help="Path to open (defaults to cwd)")
    p_vscode.add_argument("--reinstall", action="store_true",
                           help="Force a fresh VS Code install")
    p_vscode.add_argument("--no-open", dest="no_open", action="store_true",
                           help="Install (if needed) without opening a window "
                                "(used by the installer's default setup)")

    p_clone_repo = sub.add_parser(
        "repo-clone", help="Clone a git repo into ~/seedling/repo")
    p_clone_repo.add_argument("url", nargs="?", help="Git URL to clone")

    sub.add_parser("repo-list", help="List every repo cloned with `seed repo-clone`")

    p_cd_repo = sub.add_parser(
        "repo-cd", help="Change directory to a cloned repo (or ~/seedling/repo with no name)")
    p_cd_repo.add_argument("name", nargs="?", help="Name of the repo to cd into")
    p_cd_repo.add_argument("--print-path", dest="print_path", action="store_true",
                            help=argparse.SUPPRESS)  # used internally by the shell wrapper

    p_remove_repo = sub.add_parser("remove-repo", parents=[danger],
                                   help="Delete a cloned repo")
    p_remove_repo.add_argument("name", nargs="?", help="Name of the repo to delete")

    p_open_repo = sub.add_parser(
        "repo-open", help="Open a cloned repo (or ~/seedling/repo) in the file manager")
    p_open_repo.add_argument("name", nargs="?", help="Name of the repo to open")

    p_vscode_repo = sub.add_parser("repo-vscode", help="Open a cloned repo in VS Code")
    p_vscode_repo.add_argument("name", nargs="?", help="Name of the repo to open")

    p_install_repo = sub.add_parser(
        "repo-install",
        help="Install a cloned repo's dependencies into the active venv")
    p_install_repo.add_argument("name", nargs="?", help="Name of the repo to install")

    sub.add_parser("remove-user", parents=[danger],
                   help="Delete everything seedling manages")

    sub.add_parser("remove-venv-all", parents=[danger],
                   help="Delete every venv seedling has created")

    p_remove_venv = sub.add_parser("remove-venv", parents=[danger],
                                   help="Delete a single venv")
    p_remove_venv.add_argument("name", nargs="?", help="Name of the venv to delete")

    p_purge = sub.add_parser(
        "purge", parents=[danger],
        help="Fully uninstall seedling: delete everything AND remove the shell hook")
    p_purge.add_argument("--keep-repos", action="store_true",
                          help="Move ~/seedling/repo out to safety before deleting everything else")

    # Like `purge`, but immediately reinstalls from the recorded update_source
    # afterward. Cloned repos are always preserved (moved aside, then restored
    # into the fresh install), so no --keep-repos flag here.
    sub.add_parser(
        "purge-and-reinstall", parents=[danger],
        help="Wipe seedling and reinstall it fresh from the source it was originally installed from")

    p_kill = sub.add_parser(
        "kill-processes", parents=[danger],
        help="Force-close seedling's processes (--system for every python/VS Code)")
    p_kill.add_argument("target", nargs="?",
                         help="A specific process name to close. Omit to close "
                              "only seedling's own processes.")
    p_kill.add_argument("--system", action="store_true",
                         help="Close EVERY python and VS Code process on the "
                              "machine, not just seedling's. The sledgehammer.")

    p_update = sub.add_parser("update-commands",
                    help="Update the seed CLI itself from its source in ~/seedling/system/src")
    p_update.add_argument(
        "--from-branch", dest="from_branch", metavar="BRANCH", default=None,
        help="When update_source is a git URL, clone this branch (or tag) "
             "instead of the remote's default branch. Ignored for "
             "directory/share update sources.")

    sub.add_parser("where", help="Print the seedling home directory")

    p_summary = sub.add_parser(
        "summary", help="Show everything seedling has installed, on one screen")
    p_summary.add_argument("--sizes", action="store_true",
                            help="Also compute disk usage per item (slower)")
    p_summary.add_argument("--json", action="store_true",
                            help="Emit the summary as JSON, for scripts and tools")

    sub.add_parser("health-check", help="Health-check the whole seedling install")

    p_logs = sub.add_parser(
        "logs-viewer",
        help="Render the command logs as an HTML page and open it in a browser")
    p_logs.add_argument("--days", type=int, default=None,
                         help="Only include the last N days of logs (default: all)")
    p_logs.add_argument("--no-open", dest="no_open", action="store_true",
                         help="Write the HTML file without opening a browser")

    p_config = sub.add_parser("config", help="View or change seedling settings")
    config_sub = p_config.add_subparsers(dest="action")
    p_cfg_get = config_sub.add_parser("get", help="Print one setting's value")
    p_cfg_get.add_argument("key")
    p_cfg_set = config_sub.add_parser("set", help="Change a setting")
    p_cfg_set.add_argument("key")
    p_cfg_set.add_argument("value",
                            help="New value (lists take comma-separated input)")
    p_cfg_unset = config_sub.add_parser("unset", help="Reset a setting to its default")
    p_cfg_unset.add_argument("key")

    p_help = sub.add_parser("help", help="Show grouped help (add --admin for admin commands)")
    p_help.add_argument("--admin", action="store_true",
                         help="Also list the elevated admin/multi-user commands")

    # --- Admin family: elevated, cross-user teardown of a shared-root
    #     install. Registered so they dispatch, but omitted from the grouped
    #     help unless `seed help --admin` is used. All support the danger
    #     flags (-y / --preview / --non-interactive).
    sub.add_parser("admin-purge-all-users", parents=[danger],
                   help="[admin] Remove EVERY user's install under the shared root")

    p_aru = sub.add_parser("admin-remove-user", parents=[danger],
                            help="[admin] Remove one user's entire seedling install")
    p_aru.add_argument("user", nargs="?", help="Username whose install to remove")

    p_avr = sub.add_parser("admin-remove-venv", parents=[danger],
                            help="[admin] Remove one user's venv")
    p_avr.add_argument("user", nargs="?")
    p_avr.add_argument("name", nargs="?")

    p_avra = sub.add_parser("admin-remove-venv-all", parents=[danger],
                             help="[admin] Remove all of one user's venvs")
    p_avra.add_argument("user", nargs="?")

    p_apr = sub.add_parser("admin-remove-python", parents=[danger],
                            help="[admin] Remove one user's base Python + its venvs")
    p_apr.add_argument("user", nargs="?")
    p_apr.add_argument("tag", nargs="?")

    p_arr = sub.add_parser("admin-remove-repo", parents=[danger],
                            help="[admin] Remove one user's cloned repo")
    p_arr.add_argument("user", nargs="?")
    p_arr.add_argument("name", nargs="?")

    return parser


def main(argv=None) -> int:
    """Thin wrapper so every invocation -- including argparse usage errors
    and Ctrl-C -- gets its command line, output, and exit code logged."""
    argv = argv if argv is not None else sys.argv[1:]
    runlog.start(argv)
    try:
        code = _dispatch_main(argv)
    except SystemExit as e:  # argparse --help / usage errors
        runlog.finish(e.code if isinstance(e.code, int) else 0)
        raise
    except BaseException:
        runlog.finish(1)
        raise
    runlog.finish(code)
    return code


# Commands that forward everything after the verb straight to uv's pip
# interface. They deliberately bypass argparse: argparse.REMAINDER mishandles a
# LEADING option-like token, so `seed install -e .` would otherwise fail with
# "unrecognized arguments: -e". _dispatch_main slices their tail off argv and
# passes it through verbatim, so any flag order works (-e ., -U pkg, --no-deps).
def _passthrough_handlers() -> dict:
    return {
        "install": install_cmd.run,
        "uninstall": uninstall_cmd.run,
        "package-list": list_cmd.list_packages,
        "download-whl": download_cmd.run_whl,
        "download-requirements": download_cmd.run_requirements,
    }


def _invoke(handler, args) -> int:
    """Run a command handler, turning the shared uv/subprocess failures into
    tidy one-line errors (and Ctrl-C into a clean 130)."""
    try:
        return handler(args)
    except UvNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except vscode_cmd.UnknownFlavor as e:
        # A misconfigured editor build is fatal on purpose (see flavor()),
        # but it should read as a config mistake, not a crash.
        print(f"error: {e}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"error: `{' '.join(str(a) for a in e.cmd)}` failed "
              f"(exit code {e.returncode})", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130


def _dispatch_main(argv: list[str]) -> int:
    # Show the custom grouped help for a bare `seed`, `seed -h`, or
    # `seed --help` -- argparse's own auto-generated help (which would
    # otherwise fire for -h/--help before we get a chance to intercept it)
    # lists every subcommand as one flat block, which stops being readable
    # somewhere around a dozen commands. Subcommand-specific help, e.g.
    # `seed venv -h`, is untouched and still uses argparse's normal output.
    if not argv or argv[0] in ("-h", "--help"):
        print_grouped_help(show_admin="--admin" in argv)
        return 0
    if argv[0] == "help":
        print_grouped_help(show_admin="--admin" in argv)
        return 0

    # Passthrough commands (install/uninstall/package-list/download-*) forward
    # every remaining token straight to uv -- see _passthrough_handlers. Done
    # before argparse so option-like args aren't swallowed; a leading -h/--help
    # still falls through to argparse's per-command help.
    passthrough = _passthrough_handlers().get(argv[0])
    if passthrough is not None and not (len(argv) > 1 and argv[1] in ("-h", "--help")):
        paths.ensure_layout()
        config.apply_runtime_env()
        rest = argv[1:]
        ns = argparse.Namespace(command=argv[0], packages=rest, extra=rest, args=rest)
        return _invoke(passthrough, ns)

    parser = build_parser()
    args = parser.parse_args(argv)

    paths.ensure_layout()
    # TLS settings (private-CA bundle, native trust store) become process
    # environment here, so uv, git, and seedling's own downloads all
    # honor them without users ever setting variables themselves.
    config.apply_runtime_env()

    dispatch = {
        "python": python_cmd.run,
        "remove-python": python_remove_cmd.run,
        "venv": venv_cmd.run,
        "venv-list": list_cmd.list_venvs,
        "python-list": list_cmd.list_python,
        "activate": activate_cmd.run,
        "deactivate": deactivate_cmd.run,
        "venv-default": default_venv_cmd.run,
        "install": install_cmd.run,
        "uninstall": uninstall_cmd.run,
        "package-list": list_cmd.list_packages,
        "download-whl": download_cmd.run_whl,
        "download-requirements": download_cmd.run_requirements,
        "vscode": vscode_cmd.run,
        "repo-clone": repo_cmd.clone,
        "repo-list": repo_cmd.list_repos,
        "repo-cd": repo_cmd.cd_repo,
        "remove-repo": repo_cmd.remove,
        "repo-open": repo_cmd.open_repo,
        "repo-vscode": repo_cmd.vscode_repo,
        "repo-install": repo_cmd.install_repo,
        "remove-user": remove_cmd.run,
        "remove-venv-all": venv_remove_cmd.run_all,
        "remove-venv": venv_remove_cmd.run_one,
        "purge": purge_cmd.run,
        "purge-and-reinstall": purge_cmd.run,
        "kill-processes": kill_cmd.run,
        "update-commands": update_cmd.run,
        "summary": summary_cmd.run,
        "health-check": status_cmd.run,
        "logs-viewer": logs_viewer_cmd.run,
        "config": config_cmd.run,
        "admin-purge-all-users": admin_cmd.purge_all_users,
        "admin-remove-user": admin_cmd.remove_user,
        "admin-remove-venv": admin_cmd.venv_remove,
        "admin-remove-venv-all": admin_cmd.venv_remove_all,
        "admin-remove-python": admin_cmd.python_remove,
        "admin-remove-repo": admin_cmd.repo_remove,
    }

    if args.command == "where":
        print(paths.HOME)
        return 0

    handler = dispatch.get(args.command)
    if handler is None:
        print_grouped_help()
        return 0 if args.command is None else 1

    return _invoke(handler, args)


if __name__ == "__main__":
    raise SystemExit(main())
