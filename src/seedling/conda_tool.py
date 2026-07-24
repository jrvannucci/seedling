"""
micromamba-backed conda-forge tools.

seedling's Python side is uv (PyPI world). This module is the *other* engine:
micromamba, used only to install command-line tools from **conda-forge** --
the community channel, whose packaging is BSD-licensed and free to use, and
which is distinct from Anaconda's `defaults` channel and its commercial terms.
seedling never consults `defaults`: every install passes
`--override-channels -c <channel>` (conda-forge by default).

Like uv, micromamba is never assumed to be on PATH. It is fetched once into
system/bin (or dropped there as a vendored binary for offline installs) and
always called by that exact path, keeping seedling self-contained.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import colors, config, download, paths

# Pinned so every machine gets the same micromamba; bump deliberately.
MICROMAMBA_VERSION = "2.8.1-0"
_RELEASE_TAG_API = (
    "https://api.github.com/repos/mamba-org/micromamba-releases/releases/tags/"
    + MICROMAMBA_VERSION)
_RELEASE_DL = (
    "https://github.com/mamba-org/micromamba-releases/releases/download/"
    f"{MICROMAMBA_VERSION}/{{asset}}")


class MicromambaNotFound(RuntimeError):
    pass


def tag_line(line: str) -> str:
    """Prefix micromamba's own output so it never reads as seedling's."""
    if not line.strip():
        return line
    return f"{colors.dim('[micromamba]')} {line}"


def asset_name() -> str:
    """The micromamba release asset for this platform (verified against the
    real release: mamba-org/micromamba-releases)."""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows":
        return ("micromamba-win-arm64.exe"
                if machine in ("arm64", "aarch64")
                else "micromamba-win-64.exe")
    if system == "Darwin":
        return ("micromamba-osx-arm64"
                if machine in ("arm64", "aarch64")
                else "micromamba-osx-64")
    # Linux
    if machine in ("aarch64", "arm64"):
        return "micromamba-linux-aarch64"
    if machine == "ppc64le":
        return "micromamba-linux-ppc64le"
    return "micromamba-linux-64"


def find_micromamba() -> Path:
    """Locate the sandboxed micromamba, falling back to PATH as a last resort."""
    local = paths.micromamba_binary()
    if local.exists():
        return local
    on_path = shutil.which("micromamba")
    if on_path:
        return Path(on_path)
    raise MicromambaNotFound(
        "micromamba is not installed yet. `seed tool-install` fetches it "
        "automatically on first use, or drop a micromamba binary at "
        f"{paths.micromamba_binary()} for an offline install.")


def _digest_for(asset: str) -> str | None:
    """Resolve the published SHA-256 for a release asset, so the download is
    verified. Returns None if the release metadata can't be reached (the
    download then proceeds unverified, exactly as the git/VS Code fetchers do
    when a digest is unavailable)."""
    try:
        req = urllib.request.Request(
            _RELEASE_TAG_API, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except (OSError, ValueError):
        return None
    for entry in data.get("assets", []):
        if entry.get("name") == asset:
            return entry.get("digest")
    return None


def ensure_micromamba() -> Path:
    """Return the micromamba binary, fetching the pinned build if it isn't
    already present (or vendored). Verified against the release digest."""
    local = paths.micromamba_binary()
    if local.exists():
        return local
    on_path = shutil.which("micromamba")
    if on_path:
        return Path(on_path)

    paths.BIN_DIR.mkdir(parents=True, exist_ok=True)
    asset = asset_name()
    url = _RELEASE_DL.format(asset=asset)
    print(f"Fetching micromamba {MICROMAMBA_VERSION} ({asset}) ...")
    download.fetch(url, local, expected_sha256=_digest_for(asset))
    if os.name != "nt":
        local.chmod(0o755)
    return local


def channel() -> str:
    """The conda channel to install from. conda-forge by default; a URL or a
    local directory (an internal mirror) for the offline/proxied case."""
    return str(config.get("conda_channel") or "conda-forge")


def _env(extra: dict | None) -> dict:
    full = os.environ.copy()
    if extra:
        full.update(extra)
    # Keep micromamba's root prefix (envs + package cache) inside the seedling
    # tree, like uv's cache, rather than ~/.local / %USERPROFILE%.
    full.setdefault("MAMBA_ROOT_PREFIX", str(paths.MAMBA_DIR))
    full.setdefault("CONDA_PKGS_DIRS", str(paths.MAMBA_PKGS_DIR))
    return full


def run(args: list[str], *, env: dict | None = None,
        check: bool = True) -> subprocess.CompletedProcess:
    """Run micromamba, streaming its output with a `[micromamba]` tag."""
    mm = find_micromamba()
    proc = subprocess.Popen(
        [str(mm), *args], env=_env(env),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(tag_line(line))
    proc.wait()
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, [str(mm), *args])
    return subprocess.CompletedProcess([str(mm), *args], proc.returncode)


def run_captured(args: list[str], *, env: dict | None = None,
                 check: bool = True) -> subprocess.CompletedProcess:
    mm = find_micromamba()
    return subprocess.run([str(mm), *args], env=_env(env), check=check,
                          capture_output=True, text=True)
