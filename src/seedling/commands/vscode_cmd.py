from __future__ import annotations

import json
import os
import platform
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from .. import config, download, paths
from . import editors

# A minimal, opinionated starter kit: Python debugging, Jupyter, and linting.
DEFAULT_EXTENSIONS = [
    "ms-python.python",
    "ms-python.vscode-pylance",
    "ms-python.debugpy",
    "ms-toolsai.jupyter",
    "ms-toolsai.jupyter-keymap",
    "ms-toolsai.jupyter-renderers",
    "charliermarsh.ruff",  # fast linter/formatter for python
    "editorconfig.editorconfig",
    "mechatroner.rainbow-csv",  # color-codes CSV/TSV columns, adds a query feature
]

# The same kit minus the extensions that only the Microsoft Marketplace
# serves. Pylance is proprietary and licensed to run only in official
# Microsoft products, so it is absent from Open VSX by design rather than by
# oversight -- ms-python.python falls back to its bundled Jedi language
# server without it. The Microsoft-published Jupyter extensions are mirrored
# to Open VSX under the same identifiers.
OPEN_VSX_EXTENSIONS = [
    "ms-python.python",
    "ms-python.debugpy",
    "ms-toolsai.jupyter",
    "ms-toolsai.jupyter-keymap",
    "ms-toolsai.jupyter-renderers",
    "charliermarsh.ruff",
    "editorconfig.editorconfig",
    "mechatroner.rainbow-csv",
]

# Extension registries, as VS Code's product.json spells them.
GALLERIES = {
    "microsoft": {
        "serviceUrl": "https://marketplace.visualstudio.com/_apis/public/gallery",
        "itemUrl": "https://marketplace.visualstudio.com/items",
    },
    "openvsx": {
        "serviceUrl": "https://open-vsx.org/vscode/gallery",
        "itemUrl": "https://open-vsx.org/vscode/item",
    },
}

FLAVORS = ("microsoft", "vscodium")

_VSCODIUM_RELEASE_API = (
    "https://api.github.com/repos/VSCodium/vscodium/releases/latest")

DEFAULT_SETTINGS = {
    "python.terminal.activateEnvironment": True,
    "editor.formatOnSave": True,
    "editor.defaultFormatter": "charliermarsh.ruff",
    "notebook.formatOnSave.enabled": True,
    "files.autoSave": "onFocusChange",
    "python.analysis.typeCheckingMode": "basic",
    "telemetry.telemetryLevel": "off",
    "update.mode": "none",
    "extensions.autoUpdate": False,
}

# Keeps an editor's own log spam out of the user's terminal. Family-wide --
# any bundled GUI editor needs it -- so it lives in editors; aliased here
# because this module references it throughout.
_QUIET = editors.QUIET


def _write_status(phase: str, done: int = 0, total: int = 0) -> None:
    """One-line machine-readable progress ('<phase> <done> <total>') for the
    installers' background-job status bar: they poll this file while waiting
    on `seed vscode --no-open`. Written via replace so pollers never see a
    half-written line; never fatal -- a status bar must not break installs."""
    try:
        paths.VSCODE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = paths.VSCODE_DIR / "setup-status.tmp"
        tmp.write_text(f"{phase} {done} {total}\n")
        os.replace(tmp, paths.VSCODE_DIR / "setup-status")
    except OSError:
        pass


def _download_progress_reporter():
    """An on_progress callback for download.fetch that mirrors progress into
    the status file, throttled to one write per whole-percent (or per 8 MB
    when the size is unknown) so a 300MB download doesn't mean thousands of
    file writes."""
    last = {"pct": -1, "mb": -1}

    def on_progress(done: int, total: int) -> None:
        if total > 0:
            pct = done * 100 // total
            if pct != last["pct"]:
                last["pct"] = pct
                _write_status("downloading", done, total)
        else:
            mb = done // (8 * 1024 * 1024)
            if mb != last["mb"]:
                last["mb"] = mb
                _write_status("downloading", done, 0)

    return on_progress


def _os_build() -> tuple[str, str]:
    """Return (download-os-id, archive-kind) for the current platform."""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows":
        return "win32-x64-archive", "zip"
    if system == "Darwin":
        arch = "darwin-arm64" if machine in ("arm64", "aarch64") else "darwin"
        return arch, "zip"
    # Linux
    arch = "linux-arm64" if machine in ("arm64", "aarch64") else "linux-x64"
    return arch, "tar"


class UnknownFlavor(ValueError):
    """Raised when vscode_flavor names a build seedling doesn't know."""


def flavor() -> str:
    """Which editor build to install.

    An unrecognized value is fatal rather than falling back. A deployer who
    typoed "vscodium" would otherwise silently receive the Microsoft build --
    staging proprietary binaries they had deliberately chosen to avoid. A
    stopped install is recoverable; an unnoticed licensing problem on a share
    is not."""
    value = str(config.get("vscode_flavor") or "microsoft").strip().lower()
    if value not in FLAVORS:
        raise UnknownFlavor(
            f"unknown vscode_flavor {value!r}. Valid values: "
            f"{', '.join(FLAVORS)}. Fix it with "
            f"`seed config set vscode_flavor <value>`.")
    return value


def gallery_for(name: str) -> dict[str, str] | None:
    """The extensionsGallery block to force into product.json, or None to
    leave the build's own default alone.

    `extension_gallery` accepts a base URL and derives the two endpoints from
    it, since they differ only by suffix on every registry that implements
    this protocol -- so an internal Open VSX mirror is one setting, not two."""
    configured = config.get("extension_gallery")
    if configured:
        base = str(configured).rstrip("/")
        # Accept a bare host, the base, or a full serviceUrl.
        base = base.removesuffix("/gallery")
        return {"serviceUrl": f"{base}/gallery", "itemUrl": f"{base}/item"}
    # No override: Microsoft builds already point at the Marketplace and
    # VSCodium builds at Open VSX, so there is nothing to patch.
    return None


def extensions_for(name: str) -> list[str]:
    """The extension set to install. An explicitly configured list always
    wins -- including an empty one, which means "install nothing"."""
    configured = config.get("vscode_extensions")
    if isinstance(configured, list):
        return [str(e) for e in configured]
    if isinstance(configured, str):
        # PowerShell 5.1's ConvertTo-Json renders a one-element array as a
        # bare string, so a conf naming a single extension arrives as one.
        # Hand-edited settings.json files hit this too.
        return [e.strip() for e in configured.split(",") if e.strip()]
    gallery = config.get("extension_gallery")
    if name == "vscodium" or gallery:
        # Anything not served by the Marketplace can't offer Pylance.
        return list(OPEN_VSX_EXTENSIONS)
    return list(DEFAULT_EXTENSIONS)


def _vscodium_asset_id() -> str:
    """VSCodium's release-asset platform tag (its own naming, not VS Code's)."""
    system = platform.system()
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if system == "Windows":
        return "win32-arm64" if arm else "win32-x64"
    if system == "Darwin":
        return "darwin-arm64" if arm else "darwin-x64"
    return "linux-arm64" if arm else "linux-x64"


def _resolve_vscodium() -> tuple[str, str | None]:
    """Latest VSCodium release asset for this platform, from the GitHub
    releases API. Returns (url, sha256) -- GitHub publishes a per-asset
    digest, which download.fetch accepts in its 'sha256:<hex>' form.

    Both halves of the asset name come from _vscodium_asset_id() rather than
    from _os_build()'s archive kind: those are VS Code's platform names, not
    VSCodium's, and letting the two drift apart yields a lookup for an asset
    that was never published."""
    asset_id = _vscodium_asset_id()
    suffix = ".tar.gz" if asset_id.startswith("linux-") else ".zip"
    req = urllib.request.Request(
        _VSCODIUM_RELEASE_API, headers={"User-Agent": "seedling"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        # Match VSCodium-<platform>-<version><suffix>, and nothing else --
        # the release also carries REH server tarballs and .deb/.rpm
        # packages whose names share the platform tag.
        if (name.startswith(f"VSCodium-{asset_id}-")
                and name.endswith(suffix)):
            return asset["browser_download_url"], asset.get("digest")
    raise OSError(f"no VSCodium asset for {asset_id}{suffix} in the latest release")


def _resolve_download(os_id: str, kind: str, name: str) -> tuple[str, str | None]:
    """Resolve the editor archive's direct URL and its published SHA-256, so
    the download can be verified. Falls back to an unverified URL only for
    Microsoft builds, whose plain redirect endpoint needs no API call --
    useful on locked-down networks where the update API is blocked."""
    if name == "vscodium":
        return _resolve_vscodium()
    api = f"https://update.code.visualstudio.com/api/update/{os_id}/stable/latest"
    try:
        req = urllib.request.Request(api, headers={"User-Agent": "seedling"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        url = data.get("url")
        if url:
            return url, data.get("sha256hash")
    except (OSError, ValueError):
        pass
    return f"https://code.visualstudio.com/sha/download?build=stable&os={os_id}", None


def _extract(archive: Path, dest: Path, kind: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    print(f"Extracting to {dest} ...")
    if kind == "zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        download.extract_tar(archive, dest)


def _find_cli(app_dir: Path) -> list[str] | None:
    """The argv PREFIX for VS Code's actual CLI entry point -- the thing
    that runs when you type `code --install-extension ...` or `code .` in a
    normal terminal. This is what handles extension management and window
    opening headlessly, without spawning a bare Electron/GPU process.

    Using the raw main GUI binary instead of this (an earlier bug in this
    file) opens a full window per --install-extension call, and floods
    stdout/stderr with Electron log spam. Always prefer this over the GUI
    binary for anything CLI-shaped.
    """
    system = platform.system()
    if system == "Windows":
        # The .cmd wrapper is what actually runs VS Code's CLI JS entry
        # point as a plain Node process; Code.exe alone does not do this.
        script = app_dir / "bin" / "code.cmd"
        if script.exists():
            return ["cmd", "/c", str(script)]
        return None
    if system == "Darwin":
        bundle = next(app_dir.glob("*.app"), None)
        if bundle:
            candidate = bundle / "Contents" / "Resources" / "app" / "bin" / "code"
            if candidate.exists():
                return [str(candidate)]
        return None
    # Linux
    candidate = app_dir / "bin" / "code"
    if candidate.exists():
        return [str(candidate)]
    candidate = app_dir / "code"
    if candidate.exists():
        return [str(candidate)]
    return None


def _find_gui_executable(app_dir: Path) -> Path | None:
    """The main GUI binary. Only used as a last-resort fallback for opening
    a window if the CLI script (above) can't be found for some reason."""
    system = platform.system()
    if system == "Windows":
        candidate = app_dir / "Code.exe"
        if candidate.exists():
            return candidate
    elif system == "Darwin":
        bundle = next(app_dir.glob("*.app"), None)
        if bundle:
            candidate = bundle / "Contents" / "MacOS" / "Electron"
            if candidate.exists():
                return candidate
    else:
        candidate = app_dir / "code"
        if candidate.exists():
            return candidate
    return None


def _write_default_settings() -> None:
    user_dir = paths.VSCODE_APP_DIR / "data" / "user-data" / "User"
    user_dir.mkdir(parents=True, exist_ok=True)
    settings_file = user_dir / "settings.json"
    if not settings_file.exists():
        settings_file.write_text(json.dumps(DEFAULT_SETTINGS, indent=2))


def _product_json(app_dir: Path) -> Path | None:
    """The extracted build's product.json, which is where the editor records
    which extension registry it talks to."""
    if platform.system() == "Darwin":
        bundle = next(app_dir.glob("*.app"), None)
        if bundle is None:
            return None
        candidate = bundle / "Contents" / "Resources" / "app" / "product.json"
    else:
        candidate = app_dir / "resources" / "app" / "product.json"
    return candidate if candidate.exists() else None


def _apply_gallery(app_dir: Path, gallery: dict[str, str] | None) -> None:
    """Point the editor at a specific extension registry by rewriting the
    extensionsGallery block in product.json.

    Note this MODIFIES the extracted build. On the Microsoft flavor that
    means modifying a proprietary binary distribution, which is a licensing
    question of its own -- which is why nothing here happens unless a
    deployer explicitly sets `extension_gallery`. VSCodium already ships
    pointing at Open VSX, so the common case patches nothing."""
    if gallery is None:
        return
    target = _product_json(app_dir)
    if target is None:
        print("  warning: product.json not found; the extension gallery "
              "setting could not be applied.")
        return
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
        data["extensionsGallery"] = gallery
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, ValueError) as e:
        print(f"  warning: could not set the extension gallery ({e}).")
        return
    print(f"  extensions will install from {gallery['serviceUrl']}")


def _chmod_executables(app_dir: Path) -> None:
    if os.name == "nt":
        return
    for candidate in (app_dir / "bin" / "code", app_dir / "code"):
        if candidate.exists():
            candidate.chmod(candidate.stat().st_mode | 0o111)
    bundle = next(app_dir.glob("*.app"), None)
    if bundle:
        candidate = bundle / "Contents" / "Resources" / "app" / "bin" / "code"
        if candidate.exists():
            candidate.chmod(candidate.stat().st_mode | 0o111)


def install(force: bool = False, install_extensions: bool = True) -> list[str] | None:
    """Ensure VS Code is installed, returning the CLI argv prefix to use for
    opening it (or None on failure). Only re-downloads if `force` is set or
    nothing is installed yet -- this is what makes plain `seed vscode` calls
    idempotent instead of re-downloading/reinstalling every single time.

    `install_extensions=False` downloads/extracts VS Code but skips the default
    extension install -- used by the offline bundle builder, which installs the
    extensions itself with a longer retry window (a freshly-extracted tree isn't
    immediately ready for the CLI while the OS finishes scanning it)."""
    paths.ensure_layout()

    cli = _find_cli(paths.VSCODE_APP_DIR)
    if cli and not force:
        return cli

    name = flavor()
    label = "VSCodium" if name == "vscodium" else "VS Code"
    os_id, kind = _os_build()
    _write_status("resolving")
    try:
        url, sha256 = _resolve_download(os_id, kind, name)
    except OSError as e:
        print(f"error: {label} could not be resolved ({e}).")
        _write_status("failed")
        return None
    tmp_archive = paths.VSCODE_DIR / f"vscode-download.{'zip' if kind == 'zip' else 'tar.gz'}"

    paths.VSCODE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {label} from {url} ...")
    try:
        download.fetch(url, tmp_archive, expected_sha256=sha256, label=label,
                       on_progress=_download_progress_reporter())
    except download.ChecksumMismatch as e:
        print(f"error: {e}")
        _write_status("failed")
        return None
    except OSError as e:
        # Clean failure instead of a traceback -- e.g. an offline network.
        # (On offline deployments, pre-seed extensions/vscode instead; see
        # docs/OFFLINE.md.)
        print(f"error: {label} could not be downloaded ({e}).")
        tmp_archive.unlink(missing_ok=True)
        _write_status("failed")
        return None
    _write_status("extracting")
    _extract(tmp_archive, paths.VSCODE_APP_DIR, kind)
    tmp_archive.unlink(missing_ok=True)
    _apply_gallery(paths.VSCODE_APP_DIR, gallery_for(name))

    # Portable mode: a `data` folder next to the executable keeps *everything*
    # (settings, extensions, workspace state) inside extensions/vscode/app,
    # instead of the OS-default per-user locations.
    (paths.VSCODE_APP_DIR / "data").mkdir(exist_ok=True)

    _chmod_executables(paths.VSCODE_APP_DIR)

    cli = _find_cli(paths.VSCODE_APP_DIR)
    if cli is None:
        print(f"{label} was downloaded but its CLI script could not be located "
              "-- extensions won't be installed automatically. You can still "
              f"install them by hand from within {label}.")
        _write_status("failed")
        gui = _find_gui_executable(paths.VSCODE_APP_DIR)
        return [str(gui)] if gui else None

    _write_default_settings()

    if install_extensions:
        wanted = extensions_for(name)
        if wanted:
            print(f"Installing default extensions ({len(wanted)})...")
            _write_status("extensions")
            _install_extensions(cli, wanted)

    print(f"{label} installed at {paths.VSCODE_APP_DIR}")
    _write_status("done")
    return cli


def _install_extensions(cli: list[str], wanted: list[str]) -> None:
    """Install the default extensions in ONE CLI invocation (the
    --install-extension flag repeats) instead of nine separate processes --
    saves ~8 process boots of the Node CLI, measured at roughly a second
    each. NOT run as concurrent processes: that was tried and empirically
    corrupts installs (ms-python.python races the parallel installs of its
    own dependency extensions, pylance/debugpy, and fails). On failure, fall
    back to one-at-a-time so a single bad extension can't sink the others."""
    args = []
    for ext in wanted:
        args += ["--install-extension", ext]
    result = subprocess.run([*cli, *args, "--force"], **_QUIET, check=False)
    if result.returncode == 0:
        return
    print("  batch install failed; retrying extensions one at a time...")
    for ext in wanted:
        result = subprocess.run(
            [*cli, "--install-extension", ext, "--force"],
            **_QUIET, check=False,
        )
        if result.returncode != 0:
            print(f"  warning: failed to install {ext} (exit {result.returncode})")


def open_window(cli: list[str], path: str) -> None:
    """Open VS Code at `path` via its CLI entry point, fully detached from
    seedling's own process. Kept as the name `seed vscode` and `seed
    repo-vscode` already call; the detaching itself is family-generic."""
    editors.open_detached(cli, path)


def is_installed() -> bool:
    """Whether a usable VS Code is already unpacked in the seedling tree.
    Same test `install()` uses to decide it has nothing to do, so the two can
    never disagree about whether a download is about to happen."""
    return _find_cli(paths.VSCODE_APP_DIR) is not None


DOWNLOAD_NOTE = "~300 MB download"


def confirm_first_install(args) -> bool:
    """Ask before the first-run ~300MB download, via the shared editor-family
    gate. Shared by `seed vscode` and `seed repo-vscode`, which trigger the
    same download from different directions."""
    # flavor() before prompting on purpose: a misconfigured vscode_flavor
    # should fail as a config error (cli._invoke renders UnknownFlavor)
    # rather than after the user has agreed to a download. Resolved here
    # rather than in the family registry so `seed help` can't inherit the
    # crash.
    label = "VSCodium" if flavor() == "vscodium" else "VS Code"
    return editors.confirm_first_install(
        args, label=label, note=DOWNLOAD_NOTE, installed=is_installed())


def run(args) -> int:
    reinstall = getattr(args, "reinstall", False)
    # --reinstall is exempt from the gate: it only means anything when a copy
    # already exists, so the user has already said "fetch it again".
    if not reinstall and not confirm_first_install(args):
        return 0

    cli = install(force=reinstall)
    if cli is None:
        print("Could not find any way to launch VS Code after installing it.")
        return 1

    if getattr(args, "no_open", False):
        # Install-only mode, used by the installers' default setup: get VS
        # Code onto disk without popping a window in the middle of install.
        print("VS Code is installed and ready. Open it with:  seed vscode")
        return 0

    open_path = getattr(args, "path", None) or str(Path.cwd())
    print(f"Opening VS Code -> {open_path}")
    open_window(cli, open_path)
    return 0


# Join the editor family. Done at import time (cli imports this module), so
# `seed help` renders VS Code's rows without cli.py needing to know anything
# about editors beyond "ask the registry".
editors.register(editors.Editor(
    key="vscode",
    label="VS Code",
    command="vscode",
    args_hint="[path] [--reinstall]",
    summary="Install (once) and open VS Code",
    download_note=DOWNLOAD_NOTE,
    is_installed=is_installed,
    repo_command="repo-vscode",
    repo_summary="Open a cloned repo in VS Code",
))
