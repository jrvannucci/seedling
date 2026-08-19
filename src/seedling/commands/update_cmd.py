"""
`seed update-commands` -- the ONLY way seedling's own commands change.

The installers copy seedling's source into ~/seedling/system/src (WITHOUT
its .git folder -- no git checkout lives inside seedling) and record where
that source came from in the `update_source` setting: the git URL it was
cloned from, or the directory it was copied from. That copy never changes
on its own. This command updates by RE-FETCHING from the recorded source:

  - git URL          -> fresh `git clone --depth 1` into a temp folder,
                        then swap it in (minus .git); `--from-branch <b>`
                        clones that branch/tag instead of the default one
  - directory path   -> re-copy from that directory (minus .git)
  - nothing recorded -> reinstall the local copy as-is, which doubles as a
                        "repair" command for hand-edited sources

Either way, seed-cli is then reinstalled from the refreshed copy, and the
`seed` shell function (system/shell/seed.ps1|.sh) is re-rendered from the
refreshed templates so shell-side changes ship with updates too.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .. import colors, config, fsutil, paths, shell_integration, uv_tool, git_tool

# Suffix for the rename-aside trick below; also what the sweep looks for.
_ASIDE_MARKER = ".old-"

# A git URL (scheme:// or git's scp-like user@host:path). Anything else --
# a drive letter, a UNC share, a leading slash, a bare hostname-free path --
# reads as a filesystem path that just isn't reachable right now, not
# something to hand to `git clone`. Used only to pick the right WORDING for
# an unreachable update_source; `_refresh_from_url` still does the honest
# thing (fails cleanly, falls back) if this heuristic is ever wrong.
_GIT_URL_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*://|[^/\\:]+@[^/\\:]+:)")

# Matches the installers' own KEY="value" reader (install.ps1's
# Read-SeedlingConf regex). One value per line, always double-quoted.
_CONF_LINE_RE = re.compile(r'^\s*([A-Z_]+)\s*=\s*"([^"]*)"\s*$')


def _split_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _drift_list(raw: str):
    items = _split_list(raw)
    return items or None


def _drift_plain(raw: str):
    return raw if raw.strip() else None


def _drift_native_tls(raw: str):
    return True if raw.strip().lower() == "true" else None


def _drift_conda_channel(raw: str):
    v = raw.strip()
    return v if v and v != "conda-forge" else None


def _drift_vscode_flavor(raw: str):
    v = raw.strip().lower()
    return v if v and v != "microsoft" else None


def _drift_vscode_extensions(raw: str):
    v = raw.strip()
    if v.lower() == "none":
        return []
    return _split_list(v) or None


# (conf key, settings.json key, raw-string -> seedable-value or None). Only
# the VALUE-shaped settings a fresh install seeds unconditionally from a
# plain transform of the conf string -- deliberately excludes update_source,
# profile, custom_commands, and shared_root, which are FILE PATHS an
# installer resolves (and sometimes copies) relative to its own invocation
# context; replicating that faithfully from here, after the fact, risks
# reporting drift that was never really there. Those four still need a
# person to notice and re-run `seed config set` by hand.
_DRIFT_CHECKS = [
    ("SEEDLING_VENV_DEFAULT_PACKAGES", "venv_default_packages", _drift_list),
    ("SEEDLING_PYTHON_MIRROR", "python_mirror", _drift_plain),
    ("SEEDLING_PACKAGE_INDEX", "package_index", _drift_plain),
    ("SEEDLING_CONDA_CHANNEL", "conda_channel", _drift_conda_channel),
    ("SEEDLING_NATIVE_TLS", "native_tls", _drift_native_tls),
    ("SEEDLING_VSCODE_FLAVOR", "vscode_flavor", _drift_vscode_flavor),
    ("SEEDLING_EXTENSION_GALLERY", "extension_gallery", _drift_plain),
    ("SEEDLING_VSCODE_EXTENSIONS", "vscode_extensions", _drift_vscode_extensions),
    ("SEEDLING_STARTUP_COMMANDS", "startup_commands", _drift_list),
]


def _parse_conf(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        m = _CONF_LINE_RE.match(line)
        if m:
            values[m.group(1)] = m.group(2)
    return values


def report_conf_drift(refreshed_src: Path) -> None:
    """After refreshing from `update_source`, check whether the org's
    global.conf now asks for something different than what's already
    configured on this machine, and say so -- never applies anything.

    `seed update-commands` only ever refreshes seed-cli's own code; it has
    never re-seeded settings.json from a changed global.conf (settings
    are seeded once, at install time). An org moving a share path or
    changing an index previously left every existing user's machine
    silently out of sync with no way to discover it short of something
    breaking. This closes the DISCOVERY gap without touching the
    auto-apply-vs-respect-local-customization tradeoff: it tells you
    exactly what changed and the command to apply it, and stops there."""
    conf_path = refreshed_src / "global.conf"
    if not conf_path.is_file():
        return
    try:
        conf = _parse_conf(conf_path.read_text(encoding="utf-8-sig"))
    except OSError:
        return

    drifted: list[tuple[str, object, object]] = []
    for conf_key, settings_key, transform in _DRIFT_CHECKS:
        raw = conf.get(conf_key)
        if raw is None:
            continue
        new_value = transform(raw)
        if new_value is None:
            continue
        if config.get(settings_key) != new_value:
            drifted.append((settings_key, config.get(settings_key), new_value))

    if not drifted:
        return

    print()
    print(colors.warn(
        "The organization's global.conf now sets these differently than "
        "what's configured on this machine (settings are only ever seeded "
        "at install time, never re-applied automatically):"))
    for key, current, new in drifted:
        print(f"  {key}: {current!r} -> {new!r}")
        value = ",".join(new) if isinstance(new, list) else new
        print(f"    seed config set {key} \"{value}\"")


def _swap_in(src: Path, tmp: Path) -> bool:
    """Replace ~/seedling/system/src with the freshly fetched copy at `tmp`.
    robust_rmtree (not plain rmtree) because pre-existing installs may still
    have a .git full of read-only object files in the old copy."""
    failures = fsutil.robust_rmtree(src)
    if failures:
        print("Could not replace the old source copy; these files are stuck:")
        for f in failures:
            print(f"  - {f}")
        fsutil.robust_rmtree(tmp)
        return False
    tmp.rename(src)
    return True


def _refresh_from_directory(src: Path, source_dir: Path) -> bool:
    """Replace ~/seedling/system/src with a copy of `source_dir`."""
    if not (source_dir / "src" / "pyproject.toml").exists():
        print(f"error: {source_dir} doesn't look like a seedling source tree "
              "(no src/pyproject.toml). Check the `update_source` config value.")
        return False
    print(f"Copying seedling source from {source_dir} ...")
    tmp = src.parent / (src.name + ".new")
    fsutil.robust_rmtree(tmp)
    # .git never lives inside seedling, and vendor/ payloads (offline
    # binaries -- possibly hundreds of MB of pre-seeded VS Code) belong on
    # the distribution source, not in the private source copy. The dev/build
    # artifacts matter just as much for speed: `update_source` pointing at a
    # LOCAL CHECKOUT (the "edit -> update-commands -> live" loop this exists
    # for) routinely has a `.venv`, `__pycache__`, and lint/test caches sitting
    # right in it -- none of it gitignored-away for free the way the git-URL
    # clone path already gets for free (git only ever clones tracked files).
    # Measured: excluding these cut a real copytree() of this checkout from
    # 7.3s to a fraction of that.
    shutil.copytree(
        source_dir, tmp,
        ignore=shutil.ignore_patterns(
            ".git", "vendor", ".venv", "__pycache__",
            ".pytest_cache", ".ruff_cache"),
    )
    return _swap_in(src, tmp)


def _refresh_from_url(src: Path, url: str, branch: str | None = None) -> bool:
    """Replace ~/seedling/system/src with a fresh shallow clone of `url`.
    `branch` (from --from-branch) clones that branch or tag instead of the
    remote's default branch. Never fatal: a failed download leaves the current
    copy in place, and the reinstall below still runs against it."""
    try:
        git = git_tool.ensure_git()
    except git_tool.GitNotFound as e:
        print(f"git isn't available ({e}), so seedling can't download updates. "
              "Reinstalling from the current local copy instead.")
        return True

    clone = [git, "clone", "--depth", "1"]
    if branch:
        clone += ["--branch", branch]
        print(f"Downloading the latest seedling from {url} (branch {branch}) ...")
    else:
        print(f"Downloading the latest seedling from {url} ...")
    tmp = src.parent / (src.name + ".new")
    fsutil.robust_rmtree(tmp)
    returncode = git_tool.run_streamed([*clone, url, str(tmp)])
    if returncode != 0:
        print("Download failed; reinstalling from the current local copy instead.")
        fsutil.robust_rmtree(tmp)
        return True
    if not (tmp / "src" / "pyproject.toml").exists():
        print(f"warning: what {url} serves doesn't look like a seedling source "
              "tree (no src/pyproject.toml); keeping the current copy.")
        fsutil.robust_rmtree(tmp)
        return True
    fsutil.robust_rmtree(tmp / ".git")
    fsutil.robust_rmtree(tmp / "vendor")
    return _swap_in(src, tmp)


def _self_install_targets() -> list[Path]:
    """What `uv tool install` must replace: the tool venv (whose python.exe
    IS the currently running seed-cli) and the seed-cli shim."""
    exe = "seed-cli.exe" if os.name == "nt" else "seed-cli"
    return [paths.TOOL_DIR / "seedling", paths.BIN_DIR / exe]


def _sweep_aside_leftovers() -> None:
    """Delete the renamed-aside copies a PREVIOUS update left behind (see
    _move_running_self_aside). By now that update's process has long exited,
    so they delete normally. Best-effort."""
    for target in _self_install_targets():
        for leftover in target.parent.glob(target.name + _ASIDE_MARKER + "*"):
            fsutil.robust_rmtree(leftover)


def _move_running_self_aside() -> list[tuple[Path, Path]]:
    """The self-update trick that keeps `uv tool install --force --reinstall`
    from failing with 'Access is denied' on Windows: the reinstall must
    DELETE the tool venv, but this very process is running from its
    python.exe -- Windows refuses to delete a running executable (and, worse,
    uv gets partway before failing, leaving a gutted install with a broken
    `seed`). Windows DOES allow renaming a running executable's tree, so the
    live copies are renamed aside, uv installs into fresh paths, and the
    aside copies are swept on the NEXT update (or rolled back if uv fails).
    Returns [(original, aside), ...] for rollback."""
    if os.name != "nt":
        return []  # POSIX replaces in-use files fine
    moved = []
    for target in _self_install_targets():
        if not target.exists():
            continue
        aside = target.with_name(target.name + _ASIDE_MARKER + str(os.getpid()))
        try:
            target.rename(aside)
            moved.append((target, aside))
        except OSError:
            pass  # locked harder than expected; let uv try its luck as-is
    return moved


def _roll_back_aside(moved: list[tuple[Path, Path]]) -> None:
    """uv failed mid-install: put the renamed-aside live copies back so the
    user still has a working `seed` (the failure must never brick the CLI)."""
    for original, aside in reversed(moved):
        try:
            if original.exists():
                fsutil.robust_rmtree(original)  # uv's partial debris
            aside.rename(original)
        except OSError:
            print(f"warning: couldn't restore {original} from {aside}; "
                  "if `seed` stops working, re-run the installer.")


def run(args) -> int:
    src = paths.SRC_DIR
    if not src.exists():
        print(f"No seedling source found at {src}.")
        print("Re-run the installer (install.cmd -- or `sh install.cmd` on "
              "macOS/Linux) to set it up.")
        return 1

    branch = getattr(args, "from_branch", None)
    update_source = config.get("update_source")

    if update_source:
        source_dir = Path(str(update_source)).expanduser()
        if source_dir.is_dir():
            if branch:
                print(colors.warn(
                    f"note: --from-branch is ignored -- update_source "
                    f"({source_dir}) is a directory, not a git URL."))
            if not _refresh_from_directory(src, source_dir):
                return 1
        elif not _GIT_URL_RE.match(str(update_source)):
            # Looks like a filesystem path (a drive letter, a UNC share, a
            # leading slash), not a git URL -- most likely a network share
            # that isn't mounted right now, not something to `git clone`.
            # Saying so plainly beats the confusing "Downloading the latest
            # seedling from S:\..." that _refresh_from_url would print for
            # what's actually a path.
            print(colors.warn(
                f"update_source ({update_source}) looks like a directory, "
                f"but isn't reachable right now -- is the share mounted?"))
            print("Reinstalling from the current local copy instead.")
        else:
            if not _refresh_from_url(src, str(update_source), branch=branch):
                return 1
    else:
        if branch:
            print(colors.warn(
                "note: --from-branch is ignored -- no update_source git URL "
                "is recorded to clone a branch from."))
        print("No update source is recorded, so there's nowhere to fetch a "
              "newer version from; reinstalling from the current local copy "
              "(this still picks up any changes made there by hand).")
        print("Tip: `seed config set update_source <git-url-or-directory>` "
              "gives this command somewhere to update from.")

    # Windows-only: an install from before system\bin was added to the
    # persistent PATH (or one where the entry was removed by hand) picks it
    # up here instead of needing a full reinstall -- see
    # shell_integration.ensure_bin_on_windows_path. No-op (and no message)
    # everywhere else. Deliberately BEFORE the reinstall below, not after:
    # this also patches THIS PROCESS's os.environ["PATH"], which is what
    # keeps uv_tool.run() from printing uv's own "is not on your PATH"
    # warning moments later -- registering it only after uv already ran
    # left the registry correct for next time but did nothing for the
    # warning uv had already printed during the very install that added it.
    if shell_integration.ensure_bin_on_windows_path():
        print(f"Added {paths.BIN_DIR} to your PATH "
              "(new terminals/processes will see it).")

    print("Reinstalling the seed CLI ...")
    _sweep_aside_leftovers()
    moved = _move_running_self_aside()
    try:
        # The python package (pyproject.toml) lives in src/ within the repo tree.
        uv_tool.run(["tool", "install", "--force", "--reinstall", str(src / "src")],
                    env=uv_tool.selfinstall_env())
    except (subprocess.CalledProcessError, uv_tool.UvNotFound):
        _roll_back_aside(moved)
        print("The reinstall failed; the previous seed CLI was restored and "
              "still works. Fix the problem above and re-run "
              "`seed update-commands`.")
        return 1

    # The `seed` shell FUNCTION (system/shell/seed.ps1|.sh, hooked into the
    # user's profile by the installer) is part of "the commands" too --
    # re-render it from the refreshed templates, or template changes would
    # only ever reach users on a full reinstall.
    refreshed = shell_integration.refresh()
    if refreshed:
        print("Refreshing shell integration ...")
        print("(takes effect in new shells; or re-source "
              f"{refreshed[0]} in this one)")

    report_conf_drift(src)

    print(colors.ok("Done. Your `seed` commands are up to date."))
    return 0
