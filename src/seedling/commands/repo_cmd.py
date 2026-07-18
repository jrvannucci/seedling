from __future__ import annotations

import os
import platform
import subprocess

from .. import confirm, paths, uv_tool, git_tool, fsutil
from . import kill_cmd, vscode_cmd


def _derive_name(url: str) -> str:
    """Best-effort repo-name extraction from any common git URL shape:
    https://host/group/name.git, git@host:group/name.git, ./local/path,
    and Windows/UNC share paths like S:\\repos\\name.git."""
    name = url.replace("\\", "/").rstrip("/")
    if name.endswith(".git"):
        name = name[: -len(".git")]
    name = name.split("/")[-1]
    name = name.split(":")[-1]  # scp-style git@host:name (no slash after colon)
    return name or "repo"


def clone(args) -> int:
    url = getattr(args, "url", None)
    if not url:
        print("Usage: seed repo-clone <git-url>")
        return 1

    try:
        git = git_tool.ensure_git()
    except git_tool.GitNotFound as e:
        print(f"error: {e}")
        return 1

    name = _derive_name(url)
    target = paths.repo_dir(name)
    if target.exists():
        print(f"'{name}' already exists at {target}.")
        print(f"Run `seed remove-repo {name}` first if you want to re-clone it.")
        return 1

    paths.REPO_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Cloning {url} -> {target} ...")
    returncode = git_tool.run_streamed([git, "clone", url, str(target)])
    if returncode != 0:
        print("git clone failed.")
        return 1

    print(f"Cloned '{name}'.")
    print(f"  seed repo-cd {name}        # jump into it (git commands work there)")
    print(f"  seed repo-vscode {name}    # open it in VS Code")
    print(f"  seed repo-open {name}      # open it in the file manager")
    print(f"  seed repo-install {name}   # install its dependencies into the active venv")
    return 0


def list_repos(args) -> int:
    if not paths.REPO_DIR.exists() or not any(paths.REPO_DIR.iterdir()):
        print("No repos cloned yet. Run: seed repo-clone <git-url>")
        return 0

    repos = sorted(d for d in paths.REPO_DIR.iterdir() if d.is_dir())
    if not repos:
        print("No repos cloned yet. Run: seed repo-clone <git-url>")
        return 0

    git = git_tool.find_git()  # best-effort only here; don't auto-download just to list
    print(f"Repos in {paths.REPO_DIR}:")
    for r in repos:
        remote = ""
        if git and (r / ".git").exists():
            result = subprocess.run(
                [git, "-C", str(r), "remote", "get-url", "origin"],
                capture_output=True, text=True,
            )
            remote = result.stdout.strip()
        suffix = f"  -> {remote}" if remote else ""
        print(f"  {r.name}{suffix}")
    return 0


def remove(args) -> int:
    name = getattr(args, "name", None)
    if not name:
        print("Usage: seed remove-repo <name>")
        return 1

    target = paths.repo_dir(name)
    if not target.exists():
        print(f"No repo named '{name}' found in {paths.REPO_DIR}")
        return 1

    if confirm.preview_requested(args):
        confirm.print_preview(
            f"delete repo '{name}'",
            [str(target)],
            notes=["any running Python/VS Code processes will be force-closed "
                   "first (not just seedling's) so nothing blocks deletion"],
        )
        return 0

    if not confirm.confirm(
        args,
        f"Delete repo '{name}' at {target}? This will also force-close "
        "any running Python/VS Code processes first (not just seedling's).",
    ):
        print("Aborted. Nothing was deleted.")
        return 1

    print("Closing Python and VS Code processes so nothing is left in use...")
    killed = kill_cmd.kill_python_and_vscode()
    print(f"Closed {len(killed)} process(es)." if killed else "Nothing matching was running.")

    failures = fsutil.robust_rmtree(target)
    if failures:
        print(f"Some files in repo '{name}' could not be removed after several attempts:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"Deleted repo '{name}'.")
    return 0


def cd_repo(args) -> int:
    """`seed repo-cd [name]` -- change the current shell's directory to a
    cloned repo (or to ~/seedling/repo itself with no name). The directory
    change happens in the `seed` shell function; this command's job is
    resolving and validating the target (same split as `seed activate`)."""
    name = getattr(args, "name", None)
    target = paths.repo_dir(name) if name else paths.REPO_DIR

    if not target.exists():
        if name:
            print(f"No repo named '{name}' found in {paths.REPO_DIR}")
            print("Clone it first with:  seed repo-clone <git-url>")
        else:
            print(f"No repos cloned yet ({paths.REPO_DIR} doesn't exist). "
                  "Run: seed repo-clone <git-url>")
        return 1

    if getattr(args, "print_path", False):
        # Consumed by the `seed` shell function, which cd's to this path so
        # the change actually affects the caller's shell.
        print(str(target))
        return 0

    print(
        "This only works when 'seed' is the shell function installed by the "
        "seedling installer (it's what lets a directory change affect your "
        "current shell). If you're seeing this, re-run the installer or "
        "open a new terminal.\n"
        f"Target directory: {target}"
    )
    return 0


def open_repo(args) -> int:
    """`seed repo-open [name]` -- open a cloned repo (or the repos folder
    itself) in the OS file manager. For opening in VS Code, that's
    `seed repo-vscode`."""
    name = getattr(args, "name", None)
    target = paths.repo_dir(name) if name else paths.REPO_DIR
    if not target.exists():
        if name:
            print(f"No repo named '{name}' found in {paths.REPO_DIR}")
        else:
            print(f"No repos cloned yet ({paths.REPO_DIR} doesn't exist). "
                  "Run: seed repo-clone <git-url>")
        return 1

    print(f"Opening in the file manager -> {target}")
    system = platform.system()
    if system == "Windows":
        os.startfile(str(target))  # Explorer; returns immediately
    elif system == "Darwin":
        subprocess.Popen(["open", str(target)], start_new_session=True)
    else:
        subprocess.Popen(["xdg-open", str(target)], start_new_session=True)
    return 0


def vscode_repo(args) -> int:
    """`seed repo-vscode <name>` -- open a cloned repo in VS Code."""
    name = getattr(args, "name", None)
    if not name:
        print("Usage: seed repo-vscode <name>")
        return 1

    target = paths.repo_dir(name)
    if not target.exists():
        print(f"No repo named '{name}' found in {paths.REPO_DIR}")
        return 1

    cli = vscode_cmd.install(force=False)
    if cli is None:
        print("Could not find any way to launch VS Code after installing it.")
        return 1

    print(f"Opening VS Code -> {target}")
    vscode_cmd.open_window(cli, str(target))
    return 0


def install_repo(args) -> int:
    name = getattr(args, "name", None)
    if not name:
        print("Usage: seed repo-install <name>")
        return 1

    target = paths.repo_dir(name)
    if not target.exists():
        print(f"No repo named '{name}' found in {paths.REPO_DIR}")
        return 1

    if not os.environ.get("VIRTUAL_ENV"):
        print("Note: no venv looks active (VIRTUAL_ENV isn't set). "
              "Run `seed activate <name>` first, or uv will fall back to "
              "whatever it can find (e.g. a .venv in the current directory).")

    pyproject = target / "pyproject.toml"
    requirements = target / "requirements.txt"

    if pyproject.exists():
        print(f"Installing '{name}' (editable) via `uv pip install -e` ...")
        uv_tool.run(["pip", "install", "-e", str(target)])
    elif requirements.exists():
        print(f"Installing dependencies from {requirements} ...")
        uv_tool.run(["pip", "install", "-r", str(requirements)])
    else:
        print(f"Nothing to install: no pyproject.toml or requirements.txt found in {target}.")
        return 1

    return 0
