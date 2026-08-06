from __future__ import annotations

import os
import platform
import subprocess

from .. import confirm, lock, paths, pkgspec, uv_tool, git_tool, fsutil, venv_target
from . import vscode_cmd


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
    print(f"  seed vscode-repo {name}    # open it in VS Code")
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

    # Checked BEFORE the confirm prompt so the answer is in front of the user
    # at the moment they decide -- and before any process is closed, since a
    # blocked delete can escalate to closing the editor holding those buffers.
    risk = git_tool.unsaved_work(target)

    if confirm.preview_requested(args):
        confirm.print_preview(
            f"delete repo '{name}'",
            [str(target)],
            notes=[fsutil.ESCALATION_NOTE],
        )
        git_tool.warn_unsaved_work([(name, risk)] if risk else [])
        return 0

    git_tool.warn_unsaved_work([(name, risk)] if risk else [])

    if not confirm.confirm(
        args,
        f"Delete repo '{name}' at {target}?",
    ):
        print("Aborted. Nothing was deleted.")
        return 1

    failures = fsutil.remove_tree(target, label=name)
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
    `seed vscode-repo`."""
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
    """`seed vscode-repo <name>` -- open a cloned repo in VS Code."""
    name = getattr(args, "name", None)
    if not name:
        print("Usage: seed vscode-repo <name>")
        return 1

    target = paths.repo_dir(name)
    if not target.exists():
        print(f"No repo named '{name}' found in {paths.REPO_DIR}")
        return 1

    # Same first-run download gate as `seed vscode` -- reaching the editor
    # from a repo shouldn't cost 300MB more quietly than reaching it directly.
    if not vscode_cmd.confirm_first_install(args):
        return 0

    cli = vscode_cmd.install(force=False)
    if cli is None:
        print("Could not find any way to launch VS Code after installing it.")
        return 1

    print(f"Opening VS Code -> {target}")
    vscode_cmd.open_window(cli, str(target))
    return 0


def install_repo(args) -> int:
    spec = getattr(args, "name", None)
    if not spec:
        print("Usage: seed repo-install <name>[extra,...] [--venv <name>]")
        return 1

    try:
        name, extras = pkgspec.split_extras(spec)
    except pkgspec.BadExtras as e:
        print(f"error: {e}")
        return 1
    if not name:
        print(f"error: no repo name in {spec!r} -- expected name[extra,...]")
        return 1

    target = paths.repo_dir(name)
    if not target.exists():
        print(f"No repo named '{name}' found in {paths.REPO_DIR}")
        return 1

    # Which environment gets it. A named venv is resolved here and its
    # interpreter passed to uv explicitly, so the answer can't depend on what
    # happens to be active -- that's what lets `seed apply` install one repo
    # into several venvs in a row. With no name this keeps following
    # VIRTUAL_ENV exactly as `seed install` does.
    requested = getattr(args, "venv", None)
    venv_python = None
    venv_path = None
    if requested:
        resolved, failure = venv_target.resolve(requested)
        if failure is not None:
            print(f"error: {failure}")
            return 1
        venv_python, venv_path = resolved.python, resolved.path
    elif not os.environ.get("VIRTUAL_ENV"):
        print("Note: no venv looks active (VIRTUAL_ENV isn't set). "
              "Run `seed activate <name>` first, or uv will fall back to "
              "whatever it can find (e.g. a .venv in the current directory).")

    where = f" into '{requested}'" if requested else ""
    interpreter = ["--python", str(venv_python)] if venv_python else []

    pyproject = target / "pyproject.toml"
    requirements = target / "requirements.txt"

    if pyproject.exists():
        # Extras ride on the path exactly as they would on a package spec:
        # `uv pip install -e /path/to/repo[gui]`.
        with_extras = f" with extras {', '.join(extras)}" if extras else ""
        print(f"Installing '{name}' (editable){with_extras}{where} "
              "via `uv pip install -e` ...")
        command = ["pip", "install", *interpreter, "-e",
                   pkgspec.join_extras(str(target), extras)]
    elif requirements.exists():
        if extras:
            # requirements.txt has no extras to select -- silently dropping
            # them would install something other than what was asked for.
            print(f"error: repo '{name}' has no pyproject.toml, only "
                  f"{requirements.name}, which has no extras to choose from. "
                  f"Re-run as `seed repo-install {name}`.")
            return 1
        print(f"Installing dependencies from {requirements}{where} ...")
        command = ["pip", "install", *interpreter, "-r", str(requirements)]
    else:
        print(f"Nothing to install: no pyproject.toml or requirements.txt found in {target}.")
        return 1

    # Serialized like every other write into a venv: unpacking two
    # distributions into one site-packages can leave a half-written one behind.
    guard = lock.venv_lock(venv_path) if venv_path else lock.active_venv_lock()
    with guard:
        result = uv_tool.run(command, check=False)
    # check=False, then report: a failed install has to come back as an exit
    # code so `seed apply` can name it and carry on with the rest of the
    # profile, rather than aborting the whole run on an exception.
    if result.returncode != 0:
        print(f"Install of '{name}' failed.")
        return 1
    return 0
