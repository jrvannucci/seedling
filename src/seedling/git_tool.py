"""
Bundled portable git, used only by the repo-related commands
(`seed repo-clone`, and anything else that shells out to git) when no
system git is found.

Only auto-bootstrapped on Windows, where Git for Windows publishes a
genuinely portable, dependency-free build ("MinGit") as a plain zip -- no
installer, no admin rights, extract and run. macOS and Linux don't have an
equivalent official portable build (git there is dynamically linked against
system libraries expected to already be present), so on those platforms
this points the user at their package manager instead of faking a portable
install that would likely be broken.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import colors, download, paths

GIT_DIR = paths.EXTENSIONS_DIR / "git"


class GitNotFound(RuntimeError):
    pass


def _bundled_git_exe() -> Path | None:
    if platform.system() != "Windows":
        return None
    for candidate in (GIT_DIR / "cmd" / "git.exe", GIT_DIR / "bin" / "git.exe"):
        if candidate.exists():
            return candidate
    return None


def find_git() -> str | None:
    """System git if present, else our bundled copy (Windows only).
    Read-only lookup -- never triggers a download. Returns a string usable
    as argv[0], or None if nothing is available anywhere."""
    on_path = shutil.which("git")
    if on_path:
        return on_path
    bundled = _bundled_git_exe()
    return str(bundled) if bundled else None


def _git_out(git: str, repo: Path, args: list[str]) -> str | None:
    """Run a read-only git command in `repo`. None if it fails for any reason
    -- these checks run on the path to a destructive command, so they must
    never raise, hang, or block the operation they're warning about."""
    try:
        result = subprocess.run(
            [git, "-C", str(repo), *args], stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True,
            timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def unsaved_work(repo: Path, git: str | None = None) -> str | None:
    """A one-line description of work that would be LOST if `repo` were
    deleted, or None if there's nothing at risk (or we can't tell).

    Covers the two ways work lives only in a working copy: changes that were
    never committed, and commits that were never pushed. Deliberately reports
    nothing rather than guessing when git is unavailable, the directory isn't
    a repo, or a branch has no upstream to compare against -- a warning that
    cries wolf on every clean repo trains people to skip it."""
    git = git or find_git()
    if git is None or not (repo / ".git").exists():
        return None

    parts: list[str] = []
    status = _git_out(git, repo, ["status", "--porcelain"])
    if status:
        modified = untracked = 0
        for line in status.splitlines():
            if line.startswith("??"):
                untracked += 1
            elif line.strip():
                modified += 1
        if modified:
            parts.append(f"{modified} uncommitted change"
                         f"{'s' if modified != 1 else ''}")
        if untracked:
            parts.append(f"{untracked} untracked file"
                         f"{'s' if untracked != 1 else ''}")

    # Unpushed commits. A branch with no upstream produces a non-zero exit,
    # which _git_out turns into None -- correct, since "unpushed" is
    # meaningless without a remote to compare to.
    ahead = _git_out(git, repo, ["rev-list", "--count", "@{u}..HEAD"])
    if ahead and ahead.strip().isdigit() and int(ahead.strip()) > 0:
        count = int(ahead.strip())
        parts.append(f"{count} unpushed commit{'s' if count != 1 else ''}")

    return ", ".join(parts) if parts else None


def scan_for_unsaved_work(repo_dir: Path) -> list[tuple[str, str]]:
    """[(repo name, what's at risk)] for every repo under `repo_dir` holding
    work that deletion would destroy. Empty when everything is clean, when
    git isn't available, or when there are no repos -- callers treat an empty
    result as "nothing to warn about", never as "verified safe"."""
    if not repo_dir.is_dir():
        return []
    git = find_git()
    if git is None:
        return []
    found: list[tuple[str, str]] = []
    for child in sorted(repo_dir.iterdir()):
        if not child.is_dir():
            continue
        risk = unsaved_work(child, git)
        if risk:
            found.append((child.name, risk))
    return found


def warn_unsaved_work(items: list[tuple[str, str]]) -> None:
    """Print the standard 'you are about to lose this' block. Shared by every
    destructive command so the wording is identical wherever it appears."""
    if not items:
        return
    print(colors.danger(
        f"{len(items)} repo(s) contain work that deleting them would destroy:"))
    for name, risk in items:
        print(f"  - {name}: {risk}")
    print(colors.dim(
        "  (unsaved editor buffers can't be detected, and a branch with no "
        "remote can't be checked for unpushed commits)"))


def run_streamed(cmd: list[str]) -> int:
    """Run a git command, streaming its combined stdout/stderr live with a
    `[git]` tag on every line -- same convention as uv_tool.run's `[uv]`
    tag -- so git's output is attributed in the terminal and captured by
    seedling's command logging. Returns the exit code."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        if line.strip():
            sys.stdout.write(f"{colors.dim('[git]')} {line}")
        else:
            sys.stdout.write(line)
    return proc.wait()


def _latest_mingit_url() -> tuple[str, str | None]:
    """Returns (download-url, sha256-digest-or-None) for the latest MinGit.
    GitHub's release API publishes a per-asset SHA-256 digest, which lets
    the download be verified before extraction."""
    api_url = "https://api.github.com/repos/git-for-windows/git/releases/latest"
    req = urllib.request.Request(api_url, headers={"User-Agent": "seedling"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise GitNotFound(
                "GitHub's API rate limit was hit while looking up the latest "
                "MinGit release (this is a per-IP limit on anonymous "
                "requests, common on shared/corporate networks). Wait a "
                "while and try again, or download MinGit manually from "
                "https://github.com/git-for-windows/git/releases "
                f"(the '...-64-bit.zip' asset) and extract it into {GIT_DIR}."
            ) from e
        raise GitNotFound(f"Could not reach GitHub's API ({e}).") from e
    except urllib.error.URLError as e:
        raise GitNotFound(f"Could not reach GitHub's API ({e}).") from e

    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.startswith("MinGit-") and name.endswith("-64-bit.zip") and "busybox" not in name:
            return asset["browser_download_url"], asset.get("digest")
    raise GitNotFound("Could not find a MinGit release asset to download.")


def ensure_git() -> str:
    """Return a usable git executable, bootstrapping a portable MinGit on
    Windows if nothing is found. Raises GitNotFound with actionable
    instructions on macOS/Linux, where no auto-install is attempted."""
    existing = find_git()
    if existing:
        return existing

    system = platform.system()
    if system != "Windows":
        if system == "Darwin":
            hint = "Run `xcode-select --install`, or `brew install git` if you use Homebrew"
        else:
            hint = ("Install it with your package manager, e.g. "
                    "`sudo apt install git`, `sudo dnf install git`, or `sudo pacman -S git`")
        raise GitNotFound(
            f"git isn't installed, and seedling can't bundle a portable copy "
            f"on {system} (unlike Windows, there's no official portable "
            f"build). {hint}, then try again."
        )

    print(f"git isn't installed -- downloading a portable copy (MinGit) into {GIT_DIR} ...")
    GIT_DIR.mkdir(parents=True, exist_ok=True)
    url, digest = _latest_mingit_url()
    archive = GIT_DIR / "mingit-download.zip"
    try:
        download.fetch(url, archive, expected_sha256=digest, label="MinGit")
    except download.ChecksumMismatch as e:
        raise GitNotFound(str(e)) from e
    with zipfile.ZipFile(archive) as z:
        z.extractall(GIT_DIR)
    archive.unlink(missing_ok=True)

    exe = _bundled_git_exe()
    if exe is None:
        raise GitNotFound(f"MinGit was downloaded but its git.exe couldn't be located in {GIT_DIR}.")
    print(f"git is ready at {exe}")
    return str(exe)
