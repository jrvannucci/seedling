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


class CondaSolveError(RuntimeError):
    """micromamba could not resolve the requested packages."""


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
        "micromamba is not installed yet. `seed forge-install` fetches it "
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
        with urllib.request.urlopen(req, timeout=download.NETWORK_TIMEOUT) as resp:
            data = json.load(resp)
    except (OSError, ValueError):
        return None
    for entry in data.get("assets", []):
        if entry.get("name") == asset:
            return entry.get("digest")
    return None


def fetch_micromamba(dest: Path) -> Path:
    """Download the pinned micromamba binary to `dest`, verified against the
    release digest. Used both for the first-use bootstrap and to vendor
    micromamba into an offline bundle."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    asset = asset_name()
    download.fetch(_RELEASE_DL.format(asset=asset), dest,
                   expected_sha256=_digest_for(asset))
    if os.name != "nt":
        dest.chmod(0o755)
    return dest


def ensure_micromamba() -> Path:
    """Return the micromamba binary, fetching the pinned build if it isn't
    already present (or vendored). Verified against the release digest."""
    local = paths.micromamba_binary()
    if local.exists():
        return local
    on_path = shutil.which("micromamba")
    if on_path:
        return Path(on_path)
    print(f"Fetching micromamba {MICROMAMBA_VERSION} ({asset_name()}) ...")
    return fetch_micromamba(local)


def channel() -> str:
    """The conda channel to install from. conda-forge by default; a URL or a
    local directory (an internal mirror) for the offline/proxied case."""
    return str(config.get("conda_channel") or "conda-forge")


def channel_is_local(ch: str) -> bool:
    """Whether `ch` is a local filesystem channel (a directory built by
    `seed download-forge`) rather than a remote one. A bare name like
    "conda-forge" is a REMOTE named channel, not a path -- only something that
    looks like a path (or a file:// URL) counts as local."""
    if ch.startswith("file://"):
        return True
    if "://" in ch:               # http(s): a remote mirror
        return False
    return ("/" in ch or "\\" in ch or ch.startswith("~")
            or (len(ch) > 1 and ch[1] == ":"))   # windows drive


def channel_arg(ch: str) -> str:
    """The value to pass after micromamba's `-c`. A local directory is turned
    into a file:// URL (which micromamba reads a repodata.json from); remote
    channels and bare names pass through unchanged."""
    if channel_is_local(ch) and not ch.startswith("file://"):
        p = Path(ch).expanduser()
        if p.exists():
            return p.resolve().as_uri()
    return ch


def solve_downloads(specs: list[str], channel_str: str,
                    mm: Path | None = None) -> list[dict]:
    """The package records micromamba would fetch to install `specs` from
    `channel_str` -- name, url, sha256, subdir, and the metadata a
    repodata.json needs -- WITHOUT installing anything. Used to build an
    offline channel (`seed download-forge`, and the offline bundler). Pass `mm`
    to use a specific micromamba (e.g. one just vendored into a bundle)."""
    argv = ["create", "--dry-run", "--json", "-n", "_seed_solve",
            "--override-channels", "-c", channel_str, *specs]
    if mm is None:
        result = run_captured(argv, check=False)
    else:
        result = subprocess.run([str(mm), *argv], env=_env(None), check=False,
                                capture_output=True, text=True)
    if result.returncode != 0:
        raise CondaSolveError(
            (result.stderr or result.stdout or "").strip()
            or "micromamba could not resolve the request")
    try:
        data = json.loads(result.stdout)
    except ValueError as e:
        raise CondaSolveError(f"could not parse micromamba's output: {e}")
    return data.get("actions", {}).get("FETCH", [])


# Fields carried from micromamba's solve into a local channel's repodata.json.
# Taken from the solve output rather than by opening each package, so no
# .conda/zstd handling is needed.
_REPODATA_KEYS = ("name", "version", "build", "build_number", "depends",
                  "constrains", "license", "md5", "sha256", "size", "subdir",
                  "timestamp")


def build_channel(records: list[dict], dest: Path) -> list[str]:
    """Download each package in `records` into a conda-channel layout under
    `dest`, and write a repodata.json per subdir (synthesized from the
    records). Every channel needs a noarch subdir, so an empty one is created
    if the solve produced none. Returns the subdirs written."""
    subdirs: dict[str, dict] = {}
    for p in records:
        sub = p["subdir"]
        pkg_dir = dest / sub
        pkg_dir.mkdir(parents=True, exist_ok=True)
        download.fetch(p["url"], pkg_dir / p["fn"],
                       expected_sha256=p.get("sha256"))
        table = "packages.conda" if p["fn"].endswith(".conda") else "packages"
        rec = {k: p[k] for k in _REPODATA_KEYS if k in p}
        subdirs.setdefault(sub, {"packages": {}, "packages.conda": {}})
        subdirs[sub][table][p["fn"]] = rec

    subdirs.setdefault("noarch", {"packages": {}, "packages.conda": {}})
    for sub, tables in subdirs.items():
        d = dest / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / "repodata.json").write_text(json.dumps(
            {"info": {"subdir": sub}, "repodata_version": 1, **tables}))
    return sorted(subdirs)


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


def exec_tool(env_name: str, command: str, toolargs: list[str]) -> int:
    """Run `command` inside a tool's environment, inheriting this process's
    stdin/stdout/stderr so the tool behaves exactly as if run directly --
    interactive prompts (`gh auth login`), colour, and pagers all work. No
    `[micromamba]` tagging: the user asked for the tool, not for micromamba.
    Returns the tool's own exit code."""
    mm = find_micromamba()
    result = subprocess.run(
        [str(mm), "run", "-r", str(paths.MAMBA_DIR), "-n", env_name,
         command, *toolargs],
        env=_env(None))
    return result.returncode
