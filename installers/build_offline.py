#!/usr/bin/env python3
"""
build_offline.py -- assemble a self-contained, air-gapped seedling bundle.

Run this on a CONNECTED machine (it needs the internet). It downloads every
piece an offline install needs, lays them out the way seedling expects, writes
a matching global.conf, and walks you through each step -- asking before it
downloads anything (or pass --yes to let it build the whole thing unattended).

The result is a folder you copy to a share or removable media and install from
on the air-gapped side, with no internet access required there. See
docs/OFFLINE.md for the full deployment story; this tool automates its
"Putting it together" section.

Not a `seed` subcommand on purpose: it prepares the distribution, so it runs
straight from a repo checkout (`build-offline.cmd`) before seedling is installed
anywhere.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Deliberately kept equal to seedling's own requires-python; a test asserts they
# match, so relaxing one is a conscious decision rather than drift.
MIN_PYTHON = (3, 12)

# The floor is enforced HERE, not just in the launchers. build-offline.cmd runs
# `py -3` with no version check at all, and this file can also be run directly
# (`python installers/build_offline.py`), so a launcher-only probe left the
# declared floor untrue on Windows -- seedling's primary platform. One check
# covers every entry point.
#
# It sits above the `seedling` import on purpose: those modules track seedling's
# requires-python, so importing them on an older interpreter is the failure this
# is meant to replace with a readable message. Everything above is stdlib that
# parses on far older Pythons, so an old interpreter reaches this check rather
# than dying on a SyntaxError first.
if sys.version_info < MIN_PYTHON:
    _want = ".".join(str(part) for part in MIN_PYTHON)
    _have = ".".join(str(part) for part in sys.version_info[:3])
    sys.stderr.write(
        "Python {0}+ is required to build the offline bundle, but this is "
        "Python {1}\n  ({2}).\n\n"
        "Install a newer Python and re-run, or point one at this file "
        "explicitly:\n"
        "  py -{0} installers\\build_offline.py    (Windows)\n"
        "  python{0} installers/build_offline.py  (macOS/Linux)\n\n"
        "This is the interpreter that BUILDS the bundle. It is unrelated to "
        "the\nPython versions the bundle ships for your users -- mirror "
        "whichever you\nlike with --python.\n".format(_want, _have, sys.executable))
    raise SystemExit(1)

# Reuse seedling's own checksum-verifying downloader and color helpers rather
# than reimplementing them -- both are import-only, no install required.
sys.path.insert(0, str(REPO_ROOT / "src"))
import seedling  # noqa: E402
from seedling import colors, download  # noqa: E402

SEEDLING_VERSION = seedling.__version__

UV_LATEST_URL = "https://github.com/astral-sh/uv/releases/latest/download/{asset}"
PBS_RELEASE_BASE = ("https://github.com/astral-sh/python-build-standalone"
                    "/releases/download")
GIT_WIN_LATEST_API = "https://api.github.com/repos/git-for-windows/git/releases/latest"

# What the offline package index MUST contain (see docs/OFFLINE.md #4):
#   hatchling  -- uv builds seed-cli from source with it, at install AND every
#                 `seed update-commands`; without it the install can't finish.
#   the default venv packages -- created in every new venv.
# Extra packages your users will `seed install` get appended with --packages.
#
# Imported rather than restated: bundle.py's validator credits a bundle with
# holding these, so if the two lists ever disagreed, a profile would be told
# a package is present that nothing downloaded.
from seedling.bundle import ALWAYS_PRESENT as REQUIRED_PACKAGES  # noqa: E402

SRC_PYPROJECT = REPO_ROOT / "src" / "pyproject.toml"

# Every third-party component a bundle can contain, with the licence it
# arrives under. seedling ships none of these -- it downloads them from their
# publisher at the builder's direction -- but assembling them into a bundle
# that is copied to a share IS redistribution, performed by whoever runs this
# tool. See docs/LICENSING.md for the full position.
#
# "restricted" gates the build behind an explicit acknowledgement;
# "permissive" and "copyleft" are recorded in the manifest but never gate.
# Copyleft is not gated because it permits redistribution -- it just carries
# obligations (a source offer) that the manifest surfaces.
COMPONENTS = {
    "uv": {
        "source": "https://github.com/astral-sh/uv/releases",
        "license": "Apache-2.0 OR MIT",
        "redistribution": "permissive",
    },
    "python-build-standalone": {
        "source": PBS_RELEASE_BASE,
        "license": "PSF-2.0 and assorted upstream",
        "redistribution": "permissive",
    },
    "python-packages": {
        "source": "PyPI (or the configured index)",
        "license": "per package -- see the wheel set",
        "redistribution": "permissive",
        "note": "Licences vary per package; review your own --packages set.",
    },
    "micromamba": {
        "source": "https://github.com/mamba-org/micromamba-releases/releases",
        "license": "BSD-3-Clause",
        "redistribution": "permissive",
    },
    "conda-forge-tools": {
        "source": "conda-forge (https://conda-forge.org)",
        "license": "per tool -- see the bundled channel",
        "redistribution": "permissive",
        "note": ("conda-forge is the community channel, distinct from "
                 "Anaconda's `defaults` and its commercial terms. Each tool "
                 "carries its own upstream licence -- review your set."),
    },
    "mingit": {
        "source": GIT_WIN_LATEST_API,
        "license": "GPL-2.0",
        "redistribution": "copyleft",
        "note": ("Redistributing binaries carries a source-offer obligation "
                 "under GPL-2.0 section 3."),
    },
    "vscode": {
        "source": "https://update.code.visualstudio.com",
        "license": "Microsoft Software License (proprietary)",
        "redistribution": "restricted",
        "note": ("The MIT licence on microsoft/vscode covers the SOURCE, not "
                 "these branded builds. Staging them on a share is "
                 "redistribution under Microsoft's terms."),
    },
    "vscode-extensions": {
        "source": "https://marketplace.visualstudio.com",
        "license": "per extension, under the Marketplace Terms of Use",
        "redistribution": "restricted",
        "note": ("Marketplace content is governed by its own Terms of Use, "
                 "separate from each extension's licence."),
    },
    "vscodium": {
        "source": "https://github.com/VSCodium/vscodium/releases",
        "license": "MIT",
        "redistribution": "permissive",
    },
    "openvsx-extensions": {
        "source": "https://open-vsx.org",
        "license": "per extension, openly licensed",
        "redistribution": "permissive",
    },
}


# --------------------------------------------------------------------------
# requires-python floor
# --------------------------------------------------------------------------
def parse_version(text: str) -> tuple[int, ...] | None:
    """'3.12' / '3.12.7' -> (3, 12) / (3, 12, 7). None if unparseable."""
    m = re.match(r"(\d+(?:\.\d+)*)\s*$", text.strip())
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split("."))


def seedling_python_floor(pyproject: Path = SRC_PYPROJECT) -> tuple[int, ...] | None:
    """seedling's own requires-python floor, read from src/pyproject.toml.

    Deliberately a regex rather than tomllib: this file is the one piece of the
    project that runs on whatever Python the DEPLOYER's build machine happens to
    have, so it shouldn't depend on a stdlib module that has its own floor.
    Returns None if the line can't be read -- an unreadable pyproject must not
    stop a bundle build, it just means we can't pre-check versions."""
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r'^requires-python\s*=\s*"[^"\d]*(\d+(?:\.\d+)*)',
                  text, flags=re.M)
    return parse_version(m.group(1)) if m else None


def check_python_versions(versions: list[str],
                          floor: tuple[int, ...] | None) -> str | None:
    """Validate the requested --python versions against seedling's floor.

    The mirrored interpreters serve two different purposes, which is why this
    isn't a blanket rejection:
      1. the one uv uses to install seed-cli itself -- MUST satisfy the floor,
      2. base Pythons your users install for their own venvs (`seed python 3.9`)
         -- any version is legitimate.
    So the rule is: at least one mirrored version has to satisfy the floor.
    Mirroring older ones alongside it is fine and supported.

    Returns an error message if the bundle would be unusable, else None.
    An empty string in `versions` means "newest", which always satisfies."""
    if floor is None:
        return None
    if any(v == "" for v in versions):
        return None  # 'newest' is mirrored; it satisfies any floor
    parsed = [(v, parse_version(v)) for v in versions]
    if any(p is None for _, p in parsed):
        return None  # can't judge a version we can't parse; let uv decide
    floor_str = ".".join(str(p) for p in floor)
    if not any(p >= floor for _, p in parsed):
        requested = ", ".join(v for v, _ in parsed)
        return (
            f"None of the requested interpreter versions ({requested}) satisfy "
            f"seedling's own requires-python (>={floor_str}).\n"
            f"    The bundle would build fine here and then FAIL on the "
            f"air-gapped machine: `uv tool install` needs >={floor_str} to "
            f"build seed-cli, and the mirror would offer nothing new enough.\n"
            f"    Add a supported version -- e.g. --python {floor_str},"
            f"{parsed[0][0]} -- to mirror both. Older interpreters are still "
            f"useful for your users' own venvs; there just has to be one "
            f"seedling itself can run on.")
    return None


# --------------------------------------------------------------------------
# small ui helpers
# --------------------------------------------------------------------------
def step(n: int, title: str) -> None:
    print()
    print(colors.header(f"[{n}] {title}"))


def info(msg: str) -> None:
    print(f"    {msg}")


def ok(msg: str) -> None:
    print("    " + colors.ok(msg))


def warn(msg: str) -> None:
    print("    " + colors.warn(msg))


def ask(question: str, *, default: bool, auto: bool) -> bool:
    """Yes/no prompt. `auto` (from --yes) answers with the default and echoes
    the choice so an unattended run is still readable."""
    suffix = "[Y/n]" if default else "[y/N]"
    if auto:
        print(f"    {question} {suffix} -> {'yes' if default else 'no'} (--yes)")
        return default
    while True:
        try:
            reply = input(f"    {question} {suffix} ").strip().lower()
        except EOFError:
            return default
        if not reply:
            return default
        if reply in ("y", "yes"):
            return True
        if reply in ("n", "no"):
            return False


def planned_components(*, vscode: bool, mingit: bool, flavor: str,
                       gallery_overridden: bool, conda: bool = False) -> list[str]:
    """Which COMPONENTS keys this build will actually stage.

    uv, the interpreters and the wheels are unconditional. The editor
    resolves to the vscodium/openvsx pair or the vscode/marketplace pair
    depending on configuration -- which is exactly what decides whether this
    bundle contains anything restricted."""
    names = ["uv", "python-build-standalone", "python-packages"]
    if conda:
        names += ["micromamba", "conda-forge-tools"]
    if mingit:
        names.append("mingit")
    if vscode:
        if flavor == "vscodium":
            names += ["vscodium", "openvsx-extensions"]
        else:
            names.append("vscode")
            # A Microsoft build pointed at another registry pulls its
            # extensions from there, not from the Marketplace.
            names.append("openvsx-extensions" if gallery_overridden
                         else "vscode-extensions")
    return names


def restricted_among(names: list[str]) -> list[str]:
    return [n for n in names
            if COMPONENTS[n]["redistribution"] == "restricted"]


def third_party_gate(names: list[str], *, accepted: bool,
                     informational: bool = False) -> bool:
    """Show what this bundle will contain and, when any of it is restricted,
    require an explicit acknowledgement before staging it.

    Deliberately NOT satisfied by --yes: that flag skips routine
    confirmations, and acknowledging someone else's licence terms is not
    routine. Returns True if the build may proceed."""
    print()
    print(colors.header("Third-party components in this bundle"))
    for name in names:
        meta = COMPONENTS[name]
        tag = {"restricted": colors.warn("RESTRICTED"),
               "copyleft": colors.warn("copyleft"),
               "permissive": "permissive"}[meta["redistribution"]]
        print(f"  {name.ljust(24)} {meta['license']}  [{tag}]")
        if meta.get("note"):
            for line in textwrap.wrap(meta["note"], 68):
                print(f"    {colors.dim(line)}")

    restricted = restricted_among(names)
    if not restricted:
        info("All permissively licensed -- nothing here restricts "
             "redistribution. (Copyleft components, if any, permit it with "
             "obligations; see docs/LICENSING.md.)")
        return True

    print()
    print(colors.warn(
        "This bundle will contain components whose terms RESTRICT "
        "redistribution."))
    print("  seedling ships none of these; it downloads them from their "
          "publisher")
    print("  at your direction. Copying the bundle to a share is "
          "redistribution")
    print("  performed by YOU, and it is your responsibility to hold the "
          "rights")
    print("  to do it. seedling grants you no such rights. See "
          "docs/LICENSING.md.")
    print()
    print("  Avoid this entirely with SEEDLING_VSCODE_FLAVOR=\"vscodium\" "
          "(MIT + Open VSX).")
    print()

    if informational:
        # --dry-run: show what the real build would ask about, without
        # claiming an acknowledgement the caller never gave.
        print("    A real build stops here for acknowledgement "
              "(or --accept-third-party-terms).")
        return True
    if accepted:
        print("    Acknowledged via --accept-third-party-terms.")
        return True
    try:
        reply = input("    Type 'yes' to confirm you hold the necessary "
                      "rights: ").strip().lower()
    except EOFError:
        reply = ""
    if reply == "yes":
        return True
    print()
    warn("Not acknowledged; the restricted components were NOT staged.")
    info("Re-run with --no-vscode to build without them, set "
         "SEEDLING_VSCODE_FLAVOR=\"vscodium\" for an openly-licensed editor, "
         "or pass --accept-third-party-terms for unattended builds.")
    return False


def write_manifest(output: Path, names: list[str], *, staged: dict) -> Path:
    """Record what actually landed in the bundle, so an organization can
    answer "what is in this, and under what terms" without re-deriving it.

    Written even for a partial build -- it describes the folder as it is,
    not as it was meant to be."""
    entries = []
    for name in names:
        meta = COMPONENTS[name]
        entry = {
            "component": name,
            "source": meta["source"],
            "license": meta["license"],
            "redistribution": meta["redistribution"],
            "staged": bool(staged.get(name, False)),
        }
        if meta.get("note"):
            entry["note"] = meta["note"]
        if staged.get(f"{name}:version"):
            entry["version"] = staged[f"{name}:version"]
        entries.append(entry)

    doc = {
        "schema": 1,
        "generated": datetime.datetime.now(datetime.UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": f"seedling build-offline {SEEDLING_VERSION}",
        "platform": f"{platform.system()}/{normalized_arch(platform.machine())}",
        "notice": (
            "seedling ships no third-party software. Each component below was "
            "downloaded from its publisher at the builder's direction. "
            "Distributing this bundle is an act of whoever distributes it, "
            "under that component's terms. See docs/LICENSING.md."),
        "components": entries,
    }
    path = output / "MANIFEST.json"
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


_ARCHIVE_FORMATS = {"zip": "zip", "tar": "tar", "tar.gz": "gztar"}


def resolve_archive_format(requested: str, system: str) -> str:
    """'auto' (the default when --archive is passed with no value) becomes
    zip on Windows, tar.gz elsewhere -- whichever format that platform's own
    tools open without installing anything extra. An explicit format passes
    through unchanged."""
    if requested != "auto":
        return requested
    return "zip" if system == "Windows" else "tar.gz"


def archive_bundle(output: Path, fmt: str) -> Path | None:
    """Pack the whole assembled bundle into one archive file next to it --
    the folder tree becomes a single file to copy across the air gap, onto
    a USB drive, or through a one-way transfer station. Built with the
    stdlib (shutil), so this needs no extra tool on the build machine.

    Archives from the bundle's PARENT directory with the bundle's own name
    as the base_dir, so the archive contains one top-level folder (e.g.
    offline-bundle/...), not its contents spilled loose at the root --
    the same layout `seed apply`/install.cmd expect after extraction.

    Returns the archive's path, or None if it couldn't be written (never
    fatal to the overall build -- the folder on disk is still complete and
    usable on its own)."""
    try:
        created = shutil.make_archive(
            str(output), _ARCHIVE_FORMATS[fmt],
            root_dir=str(output.parent), base_dir=output.name)
    except OSError as e:
        warn(f"Could not create the archive: {e}")
        return None
    return Path(created)


def _progress(done: int, total: int) -> None:
    if not (total and sys.stdout.isatty()):
        return  # a redirected/CI log doesn't benefit from \r updates
    pct = done * 100 // total
    print(f"\r    ... {pct:3d}%  ({done // 1024} / {total // 1024} KiB)",
          end="", flush=True)
    if done >= total:
        print()


def fetch(url: str, dest: Path, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    download.fetch(url, dest, label=label, on_progress=_progress)


# --------------------------------------------------------------------------
# platform / asset resolution
# --------------------------------------------------------------------------
def normalized_arch(machine: str) -> str:
    m = machine.lower()
    if m in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if m in ("arm64", "aarch64"):
        return "aarch64"
    return m  # let it flow through; the caller reports if unsupported


def uv_asset_name(system: str, arch: str) -> str:
    """The uv release asset for a platform (astral-sh/uv GitHub releases)."""
    if system == "Windows":
        return f"uv-{arch}-pc-windows-msvc.zip"
    if system == "Linux":
        return f"uv-{arch}-unknown-linux-gnu.tar.gz"
    if system == "Darwin":
        return f"uv-{arch}-apple-darwin.tar.gz"
    raise ValueError(f"unsupported OS for uv download: {system}")


def parse_pbs_target(uv_verbose_stderr: str) -> tuple[str, str] | None:
    """Pull the release tag + archive filename out of the `Downloading ...` line
    uv prints (with -v) for the interpreter it wants. Returns (tag, filename)
    with the filename URL-decoded (e.g. %2B -> +), or None if not found.

    Example line:
      DEBUG Downloading file:///.../20241016/cpython-3.12.7%2B2024...tar.gz
    """
    m = re.search(r"/(\d{8})/(cpython-[^/\s]+?\.tar\.(?:gz|zst))",
                  uv_verbose_stderr)
    if not m:
        return None
    tag = m.group(1)
    filename = urllib.parse.unquote(m.group(2))
    return tag, filename


# --------------------------------------------------------------------------
# component builders
# --------------------------------------------------------------------------
def _uv_env(*, cache: Path | None, extra: dict | None = None) -> dict:
    """The environment every download runs under.

    `cache=None` means "don't redirect the caches" -- it used to set
    UV_CACHE_DIR to the string "None", pointing uv at a directory of that
    name next to wherever the builder ran."""
    env = os.environ.copy()
    if cache is not None:
        env["UV_CACHE_DIR"] = str(cache)
        # The wheels are fetched by pip (uv has no `pip download`), and pip
        # keeps its OWN http cache -- so pointing only UV_CACHE_DIR here left
        # every wheel outside the cache this builder maintains. That costs
        # most exactly where it hurts: a bundle mirroring two interpreters
        # fetches the same py3-none-any wheels once per pass, and a CI runner
        # with no user profile cache re-downloads the whole wheelhouse every
        # build.
        env["PIP_CACHE_DIR"] = str(Path(cache) / "pip")
    if extra:
        env.update(extra)
    return env


def _extract_uv_binary(archive: Path, into: Path) -> list[str]:
    """Extract uv (+uvx) from a release archive into `into`. Returns the names
    placed. Handles both the flat zip and the folder-wrapped tarball layouts."""
    into.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp)
        else:
            download.extract_tar(archive, tmp)
        placed = []
        for name in ("uv", "uv.exe", "uvx", "uvx.exe"):
            for found in tmp.rglob(name):
                target = into / name
                shutil.copy2(found, target)
                if os.name != "nt":
                    target.chmod(0o755)
                placed.append(name)
                break
    return placed


def build_uv(vendor_uv: Path, system: str, arch: str) -> Path | None:
    """Download uv into vendor/uv/. Returns the path to the uv executable."""
    exe_name = "uv.exe" if system == "Windows" else "uv"
    existing = vendor_uv / exe_name
    if existing.exists():
        ok(f"uv already present at {existing} -- skipping download.")
        return existing

    asset = uv_asset_name(system, arch)
    url = UV_LATEST_URL.format(asset=asset)
    info(f"Downloading the latest uv ({asset}) ...")
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / asset
        try:
            fetch(url, archive, label="uv")
            placed = _extract_uv_binary(archive, vendor_uv)
        except Exception as e:  # noqa: BLE001 -- report and let caller decide
            warn(f"uv download failed: {e}")
            return None
    if exe_name not in placed:
        warn("uv archive downloaded but no uv binary was found inside it.")
        return None
    ok(f"uv placed in {vendor_uv} ({', '.join(placed)}).")
    return vendor_uv / exe_name


def build_python_mirror(uv_exe: Path, versions: list[str], mirror_dir: Path,
                        cache: Path) -> list[str]:
    """Populate `mirror_dir` with the exact python-build-standalone archives the
    shipped uv wants, laid out as <tag>/<filename> so a `file://` mirror
    resolves offline. The trick: ask uv (with a bogus local mirror) which
    archive it would fetch, then mirror that one asset from the real upstream --
    so the bundle always matches the uv version you're shipping.

    Returns the list of X.Y versions actually mirrored (so the wheel step can
    target the same interpreter)."""
    mirrored: list[str] = []
    for version in versions:
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty-mirror"
            empty.mkdir()
            env = _uv_env(cache=cache, extra={
                "UV_PYTHON_INSTALL_MIRROR": empty.as_uri(),
                "UV_PYTHON_INSTALL_DIR": str(Path(td) / "py"),
            })
            probe = [str(uv_exe), "python", "install", "-v"]
            if version:
                probe.append(version)
            result = subprocess.run(probe, env=env, capture_output=True,
                                    text=True)
            target = parse_pbs_target(result.stderr + result.stdout)
        if target is None:
            warn(f"couldn't determine the interpreter archive for "
                 f"'{version or 'newest'}' from uv -- skipping it.")
            continue
        tag, filename = target
        minor = _minor_version(filename)
        url = f"{PBS_RELEASE_BASE}/{tag}/{urllib.parse.quote(filename)}"
        dest = mirror_dir / tag / filename
        if dest.exists():
            ok(f"{filename} already mirrored -- skipping.")
            if minor:
                mirrored.append(minor)
            continue
        info(f"Mirroring {filename} (Python {version or 'newest'}) ...")
        try:
            fetch(url, dest, label=filename)
            if minor:
                mirrored.append(minor)
        except Exception as e:  # noqa: BLE001
            warn(f"failed to download {filename}: {e}")
    return mirrored


def _minor_version(pbs_filename: str) -> str | None:
    """'cpython-3.12.13+2026...' -> '3.12'."""
    m = re.match(r"cpython-(\d+\.\d+)\.", pbs_filename)
    return m.group(1) if m else None


def _download_wheels_for(uv_exe: Path, packages: list[str], wheels_dir: Path,
                         py_version: str | None, cache: Path) -> bool:
    """One `pip download` pass into the flat wheelhouse, for one interpreter."""
    cmd = [str(uv_exe), "tool", "run", "--from", "pip", "pip", "download",
           "--dest", str(wheels_dir), *packages]
    if py_version:
        # Match the interpreter you're shipping so platform/abi wheels line up.
        # pip requires --only-binary=:all: alongside --python-version (it can't
        # build sdists for a Python it isn't running) -- which is what we want
        # anyway: an offline machine has no toolchain to build sdists.
        cmd += ["--python-version", py_version, "--only-binary=:all:"]
    try:
        subprocess.run(cmd, env=_uv_env(cache=cache), check=True)
    except subprocess.CalledProcessError as e:
        label = f"Python {py_version}" if py_version else "this interpreter"
        warn(f"`pip download` failed for {label} (exit {e.returncode}). "
             "See the output above.")
        return False
    return True


def build_wheels(uv_exe: Path, packages: list[str], wheels_dir: Path,
                 py_versions: list[str], cache: Path) -> bool:
    """Download every wheel (and its dependencies) the offline index needs, via
    `uvx pip download` -- the same mechanism as `seed download-whls`.

    Runs once PER mirrored interpreter into the same flat wheelhouse. That
    matters whenever more than one version is mirrored: `--python-version`
    selects version-specific wheels, and while the headline packages are
    version-agnostic (`py3-none-any`, or `py3-none-<platform>` for ruff), their
    compiled dependencies are not -- ipykernel alone pulls pyzmq, tornado,
    debugpy and psutil, all of which ship cp3XX-tagged wheels. Resolving for
    only the first interpreter produced a bundle where `seed venv --python 3.9`
    failed offline even though 3.9 had been mirrored. A flat wheelhouse holds
    every tag happily, so the fix is just to loop.

    An empty `py_versions` means "don't pin" -- one pass with whatever the
    shipped uv resolves."""
    wheels_dir.mkdir(parents=True, exist_ok=True)
    # Dedupe, preserving order: two requested versions can map to one X.Y.
    targets: list[str] = list(dict.fromkeys(v for v in py_versions if v))
    info("Resolving and downloading wheels (hatchling + default packages"
         + (" + extras" if len(packages) > len(REQUIRED_PACKAGES) else "") + ") ...")
    info("Packages: " + ", ".join(packages))
    if targets:
        info("Interpreters: " + ", ".join(targets)
             + (" (one pass each -- compiled dependencies are "
                "version-specific)" if len(targets) > 1 else ""))

    failed: list[str] = []
    for version in targets or [None]:
        if len(targets) > 1:
            info(f"  -> Python {version} ...")
        if not _download_wheels_for(uv_exe, packages, wheels_dir, version, cache):
            failed.append(version or "default")

    count = len(list(wheels_dir.glob("*.whl")))
    if failed:
        warn(f"{count} wheel(s) downloaded, but resolution FAILED for: "
             + ", ".join(failed)
             + ". Venvs on those interpreters won't work offline.")
        return False
    ok(f"{count} wheel(s) (plus any source archives) in {wheels_dir}"
       + (f", covering Python {', '.join(targets)}." if targets else "."))
    return True


def build_mingit(vendor_git: Path) -> bool:
    """Download portable MinGit (Windows) into vendor/git/. Optional -- only
    needed for `seed repo-clone` / URL-based updates where there's no system
    git on the offline machines."""
    if any(vendor_git.rglob("git.exe")):
        ok(f"git already present in {vendor_git} -- skipping.")
        return True
    info("Looking up the latest MinGit release ...")
    try:
        req = urllib.request.Request(
            GIT_WIN_LATEST_API, headers={"User-Agent": "seedling-offline-builder"})
        import json
        with urllib.request.urlopen(req) as resp:
            data = json.load(resp)
        asset = next(
            a for a in data["assets"]
            if re.match(r"MinGit-.*-64-bit\.zip$", a["name"])
            and "busybox" not in a["name"].lower())
    except Exception as e:  # noqa: BLE001
        warn(f"couldn't find a MinGit asset: {e}")
        return False
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / asset["name"]
        info(f"Downloading {asset['name']} ...")
        try:
            fetch(asset["browser_download_url"], archive, label="MinGit")
            vendor_git.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as z:
                z.extractall(vendor_git)
        except Exception as e:  # noqa: BLE001
            warn(f"MinGit download/extract failed: {e}")
            return False
    ok(f"MinGit extracted into {vendor_git}.")
    return True


def _extensions_present(app_dir: Path) -> bool:
    """True if at least one extension is installed in the portable data dir
    (VS Code seeds a bare extensions.json even when none are installed)."""
    ext_dir = app_dir / "data" / "extensions"
    return ext_dir.is_dir() and any(p.is_dir() for p in ext_dir.iterdir())


def _install_extensions(app_dir: Path) -> bool:
    """Install the default extensions into the freshly-extracted VS Code,
    retrying over a generous window. Two things bite an unattended build here:
      1. A dot-prefixed path component makes the CLI fail signature
         verification ('ENOENT') -- so the staging dir must NOT be dotted
         (handled by the caller).
      2. Immediately after a 300MB extract the CLI fails while the OS finishes
         scanning the new files; the same tree succeeds ~a minute later. So we
         retry for up to ~2.5 minutes instead of giving up after a few seconds.
    Reuses seedling's own extension list and CLI resolution."""
    import time

    from seedling.commands import vscode_cmd

    cli = vscode_cmd._find_cli(app_dir)
    if not cli:
        warn("VS Code CLI not found; extensions were not installed.")
        return False
    # The configured set, not the built-in one: a bundle built for a
    # vscodium/Open VSX deployment must stage the extensions that deployment
    # will actually install, or the offline machines get nothing.
    wanted = vscode_cmd.extensions_for(vscode_cmd.flavor())
    if not wanted:
        info("No extensions configured; skipping.")
        return True
    ext_args: list[str] = []
    for ext in wanted:
        ext_args += ["--install-extension", ext]
    # Cumulative wait across the retries: ~150s.
    delays = [5, 10, 15, 20, 25, 25, 25, 25]
    last = "unknown"
    for attempt in range(len(delays) + 1):
        result = subprocess.run(
            [*cli, *ext_args, "--force"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            check=False)
        if result.returncode == 0:
            ok(f"Installed {len(wanted)} extensions.")
            return True
        lines = (result.stdout or "").strip().splitlines()
        last = lines[-1] if lines else "unknown"
        if attempt == 0:
            info("VS Code isn't ready for extensions yet (the OS is still "
                 "scanning the freshly-extracted files); retrying for up to "
                 "~2.5 minutes ...")
        if attempt < len(delays):
            time.sleep(delays[attempt])
    warn("Extensions couldn't be installed (VS Code itself is staged). "
         f"Last error: {last}")
    return False


def build_vscode(vendor_vscode: Path, staging: Path) -> bool:
    """Pre-seed portable VS Code AND the default extensions into vendor/vscode/.
    Rather than reimplement the VS Code update-API download + marketplace
    extension install, drive seedling's OWN vscode installer against a throwaway
    home (SEEDLING_HOME=staging), then move the finished tree into place. Heavy:
    ~300MB for VS Code plus the extensions."""
    if (vendor_vscode / "app").exists():
        ok(f"VS Code already staged in {vendor_vscode} -- skipping.")
        return True

    info("Downloading VS Code via seedling's own installer "
         "(~300MB; this can take a few minutes) ...")
    env = os.environ.copy()
    env["SEEDLING_HOME"] = str(staging)
    env["SEEDLING_NO_LOG"] = "1"
    env["PYTHONPATH"] = (str(REPO_ROOT / "src") + os.pathsep
                         + env.get("PYTHONPATH", ""))
    # Let install() download + extract, but NOT install extensions -- a
    # just-extracted tree isn't ready for the CLI yet, so the builder installs
    # them itself afterward with a long retry window (_install_extensions).
    snippet = ("import sys; from seedling.commands import vscode_cmd; "
               "sys.exit(0 if vscode_cmd.install(force=False, "
               "install_extensions=False) else 1)")
    try:
        result = subprocess.run([sys.executable, "-c", snippet], env=env)
    except OSError as e:  # noqa: BLE001 -- nothing staged yet if it never launched
        warn(f"couldn't launch the VS Code installer: {e}")
        return False

    # Everything below leaves a ~300MB staging tree behind if it doesn't finish,
    # and staging lives INSIDE the bundle folder that docs/OFFLINE.md tells
    # deployers to copy wholesale to the share -- so drop it unconditionally,
    # including on Ctrl-C partway through the extension retry window.
    try:
        app_dir = staging / "extensions" / "vscode" / "app"
        if result.returncode != 0 or not app_dir.exists():
            warn("VS Code setup didn't complete (see the output above). Skipped; "
                 "you can pre-seed it by hand later (see docs/OFFLINE.md #6).")
            return False

        if not _extensions_present(app_dir):
            _install_extensions(app_dir)

        vendor_vscode.parent.mkdir(parents=True, exist_ok=True)
        # Move (fast -- same drive: staging lives under the output folder) the
        # whole portable tree out of the throwaway home.
        shutil.move(str(app_dir.parent), str(vendor_vscode))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    ok(f"VS Code + extensions staged in {vendor_vscode}.")
    return True


def build_conda_channel(vendor_micromamba: Path, channel_dir: Path,
                        tools: list[str]) -> tuple[bool, int]:
    """Vendor micromamba and build a conda channel of `tools` + their
    dependencies under `channel_dir`, so the offline machine can
    `seed forge-install` them with no network. Returns (ok, package_count).

    The channel is downloaded from the builder's configured conda source
    (conda-forge by default, or an internal mirror), and its repodata.json is
    synthesized from the solve -- the same mechanism as `seed download-forge`,
    reused here so the bundle carries one artifact instead of a side folder."""
    from seedling import conda_tool
    mm_name = "micromamba.exe" if platform.system() == "Windows" else "micromamba"
    try:
        mm = conda_tool.fetch_micromamba(vendor_micromamba / mm_name)
    except (OSError, RuntimeError) as e:
        warn(f"Could not fetch micromamba: {e}")
        return False, 0
    ok(f"Vendored micromamba into {vendor_micromamba}")

    source = conda_tool.channel_arg(conda_tool.channel())
    info(f"Resolving {', '.join(tools)} from {conda_tool.channel()} ...")
    try:
        records = conda_tool.solve_downloads(tools, source, mm=mm)
    except conda_tool.CondaSolveError as e:
        warn(f"Could not resolve the conda-forge tools: {e}")
        return False, 0
    if not records:
        warn("No conda packages resolved for the requested tools.")
        return False, 0

    info(f"Downloading {len(records)} conda package(s) into {channel_dir} ...")
    conda_tool.build_channel(records, channel_dir)
    ok(f"Conda channel built at {channel_dir} ({len(records)} package(s)).")
    return True, len(records)


# --------------------------------------------------------------------------
# preflight: does the assembled bundle actually install?
# --------------------------------------------------------------------------
# Every step above reports "did this download succeed". None of them answer the
# question that actually matters -- WOULD THIS BUNDLE INSTALL on a machine with
# no internet. Those are different, and the gap is expensive: it's discovered in
# the air-gapped room, after the bundle has been signed off and carried in.
#
# So this runs the real thing on the build machine: uv's own offline install,
# using ONLY the bundle's contents, with the network refused.
#
# Two details make it a genuine test rather than theatre:
#   * a FRESH uv cache -- the build just populated the normal one, so a warm
#     cache would happily satisfy an install from a wheel the bundle is
#     MISSING, and the check would pass on a broken bundle.
#   * `--offline` on every uv call, plus the same UV_* knobs seedling itself
#     sets at runtime (see uv_tool._build_env), so this exercises the real code
#     path rather than an approximation of it.


def discover_mirrored_versions(mirror_dir: Path) -> list[str]:
    """The X.Y versions actually present in a python-builds mirror, so a bundle
    can be verified standalone (--verify-only) without knowing how it was
    built."""
    found: list[str] = []
    if not mirror_dir.is_dir():
        return found
    for archive in sorted(mirror_dir.rglob("cpython-*.tar.*")):
        minor = _minor_version(archive.name)
        if minor and minor not in found:
            found.append(minor)
    return found


def write_offline_index_config(cfg_path: Path, wheels_dir: Path) -> Path:
    """A uv.toml declaring the wheel folder as a flat default index, with
    pypi.org disabled. Deliberately the same shape seedling generates at
    runtime in uv_tool._offline_index_config -- if that changes, this should
    too, or preflight stops testing what users actually get."""
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        "# Generated by build_offline.py for a preflight check.\n"
        "[[index]]\n"
        'name = "seedling-offline"\n'
        f'url = "{wheels_dir.resolve().as_uri()}"\n'
        'format = "flat"\n'
        "default = true\n",
        encoding="utf-8")
    return cfg_path


def _preflight_env(cache: Path, mirror_dir: Path, cfg_path: Path,
                   py_dir: Path) -> dict:
    env = os.environ.copy()
    # Scrub anything inherited that could reach the network or a real install.
    for var in list(env):
        if var.startswith(("UV_", "PIP_", "SEEDLING_")):
            del env[var]
    env["UV_CACHE_DIR"] = str(cache)              # fresh: see note above
    env["UV_PYTHON_INSTALL_MIRROR"] = mirror_dir.resolve().as_uri()
    env["UV_PYTHON_INSTALL_DIR"] = str(py_dir)    # never touch the real one
    env["UV_CONFIG_FILE"] = str(cfg_path)
    return env


def _run_offline(uv_exe: Path, args: list[str], env: dict) -> tuple[bool, str]:
    """One uv call with the network refused. Returns (ok, last output line)."""
    result = subprocess.run(
        [str(uv_exe), *args, "--offline"], env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    out = (result.stdout or "").strip()
    tail = out.splitlines()[-1] if out else "(no output)"
    return result.returncode == 0, tail


def verify_bundle(output: Path, seedling_copy: Path, uv_exe: Path,
                  packages: list[str]) -> bool:
    """Install from the bundle, offline, on this machine. Returns True if a
    real air-gapped install would work."""
    mirror_dir = output / "python-builds"
    wheels_dir = output / "wheels"
    failures: list[str] = []

    if not uv_exe.exists():
        warn(f"No uv binary at {uv_exe} -- nothing to verify with.")
        return False

    versions = discover_mirrored_versions(mirror_dir)
    if not versions:
        warn(f"No interpreter archives found in {mirror_dir}; skipping "
             "preflight. Re-run step 3, then verify with --verify-only.")
        return False

    floor = seedling_python_floor(seedling_copy / "src" / "pyproject.toml")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        env = _preflight_env(tmp / "cache", mirror_dir,
                             write_offline_index_config(tmp / "uv.toml", wheels_dir),
                             tmp / "pythons")

        # 1. Each mirrored interpreter must actually install from the mirror,
        #    and its venv must get the default packages from the wheelhouse.
        #    This is what catches a wheel set resolved for only one version.
        usable: list[str] = []
        for version in versions:
            ok_install, tail = _run_offline(uv_exe, ["python", "install", version], env)
            if not ok_install:
                failures.append(f"Python {version} won't install from the mirror: {tail}")
                continue
            venv = tmp / f"venv{version.replace('.', '')}"
            ok_venv, tail = _run_offline(
                uv_exe, ["venv", "--python", version, str(venv)], env)
            if not ok_venv:
                failures.append(f"Python {version} venv creation failed: {tail}")
                continue
            usable.append(version)
            venv_packages = [p for p in packages if p != "hatchling"]
            ok_pkgs, tail = _run_offline(
                uv_exe, ["pip", "install", "--python", str(venv), *venv_packages], env)
            if ok_pkgs:
                ok(f"Python {version}: interpreter + {len(venv_packages)} "
                   "package(s) install offline.")
            else:
                failures.append(
                    f"Python {version}: venv packages missing from the wheel "
                    f"index ({tail}). A `seed venv --python {version}` would "
                    "fail on the air-gapped machine.")

        # 2. seed-cli itself must BUILD from the bundled source using hatchling
        #    from the wheelhouse -- the step that actually blocks an install.
        target = next((v for v in usable
                       if floor is None or (parse_version(v) or ()) >= floor), None)
        if target is None:
            failures.append(
                "No mirrored interpreter both installs and satisfies "
                "seedling's requires-python, so seed-cli could not be built.")
        else:
            venv = tmp / "seedcli"
            ok_venv, _ = _run_offline(
                uv_exe, ["venv", "--python", target, str(venv)], env)
            ok_build, tail = _run_offline(
                uv_exe, ["pip", "install", "--python", str(venv),
                         str(seedling_copy / "src")], env)
            if ok_venv and ok_build:
                ok(f"seed-cli builds offline on Python {target} "
                   "(hatchling resolved from the bundle).")
            else:
                failures.append(f"seed-cli could not be built offline: {tail}")

    if failures:
        warn("Preflight FAILED -- this bundle would not install air-gapped:")
        for f in failures:
            warn(f"  - {f}")
        return False
    ok("Preflight passed: this bundle installs with no internet.")
    return True


# --------------------------------------------------------------------------
# staging + config
# --------------------------------------------------------------------------
def stage_repo(output: Path) -> Path:
    """Copy the repo into <output>/seedling (the thing users install from),
    excluding history/caches/tests. Returns the copy's path.

    Always REFRESHES an existing copy. The heavy steps (uv, interpreters,
    wheels, VS Code) all skip work that's already staged, which is what makes
    re-running cheap -- but the repo copy is the one thing that changes between
    runs, and it's seconds to redo. Reusing it silently shipped the source as
    it was on the FIRST build: you'd edit the repo, re-run, watch step 8 rewrite
    global.conf, and get a bundle that looked freshly built around stale
    code. The vendor/ payloads are preserved across the refresh, so this costs
    nothing but the copy."""
    seedling_copy = output / "seedling"
    ignore = shutil.ignore_patterns(
        ".git", "__pycache__", "*.pyc", "offline-bundle", ".pytest_cache",
        ".claude")

    if not seedling_copy.exists():
        info(f"Copying the repo into {seedling_copy} ...")
        shutil.copytree(REPO_ROOT, seedling_copy, ignore=ignore)
        return seedling_copy

    # Refresh in place: move vendor/ aside (it holds the expensive downloads,
    # and is gitignored so it never came from REPO_ROOT anyway), replace the
    # source, then put it back.
    info(f"Refreshing the repo copy at {seedling_copy} "
         "(vendor/ payloads are kept) ...")
    vendor = seedling_copy / "vendor"
    stash = output / ".vendor-stash"
    shutil.rmtree(stash, ignore_errors=True)
    if vendor.exists():
        shutil.move(str(vendor), str(stash))
    try:
        shutil.rmtree(seedling_copy)
        shutil.copytree(REPO_ROOT, seedling_copy, ignore=ignore)
    finally:
        if stash.exists():
            shutil.rmtree(seedling_copy / "vendor", ignore_errors=True)
            shutil.move(str(stash), str(seedling_copy / "vendor"))
    return seedling_copy


def write_conf(conf_path: Path, values: dict[str, str]) -> None:
    """Set KEY="value" entries in a global.conf, replacing existing lines and
    appending any that are missing. Mirrors the installers' conf format."""
    text = conf_path.read_text(encoding="utf-8") if conf_path.exists() else ""
    for key, value in values.items():
        line = f'{key}="{value}"'
        pattern = rf'^{re.escape(key)}=.*$'
        if re.search(pattern, text, flags=re.M):
            # A function replacement -- never a string -- so backslashes in a
            # Windows path (C:\Users\...) aren't read as regex escapes (\U ...).
            text = re.sub(pattern, lambda _m: line, text, flags=re.M)
        else:
            text = text.rstrip("\n") + "\n" + line + "\n"
    conf_path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------
# main walkthrough
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="build-offline",
        description="Assemble a self-contained, offline seedling bundle.")
    parser.add_argument(
        "-o", "--output", default=str(REPO_ROOT / "offline-bundle"),
        help="Where to assemble the bundle (default: ./offline-bundle).")
    parser.add_argument(
        "--python", dest="pythons", default="",
        help="Comma-separated Python versions to mirror (e.g. 3.12,3.11). "
             "Default: the newest stable your shipped uv resolves.")
    parser.add_argument(
        "--packages", default="",
        help="Extra packages to add to the offline wheel index, "
             "comma-separated (on top of hatchling + the default venv packages).")
    parser.add_argument(
        "--tools", default="",
        help="conda-forge command-line tools to bundle (comma-separated, e.g. "
             "ripgrep,pandoc). Vendors micromamba and builds a conda channel "
             "into the bundle so `seed forge-install` works offline. A profile's "
             "[tools] are included automatically.")
    parser.add_argument(
        "--no-vscode", action="store_true",
        help="Skip the VS Code + extensions download (the ~300MB step).")
    parser.add_argument(
        "--mingit", action="store_true",
        help="Also download portable MinGit into vendor/git/ (Windows only). "
             "Off by default -- only needed if your offline machines have no "
             "system git; this is what makes it reachable under --yes.")
    parser.add_argument(
        "--deploy-root", default="",
        help="The path the bundle will live at on the TARGET machines (e.g. "
             r"S:\tools). global.conf is written with paths under it. "
             "Default: the output folder's own absolute path.")
    parser.add_argument(
        "--yes", action="store_true",
        help="Answer every prompt with its default -- build the whole bundle "
             "unattended.")
    parser.add_argument(
        "--no-verify", action="store_true",
        help="Skip the preflight check that installs from the finished bundle "
             "offline to prove it works.")
    parser.add_argument(
        "--verify-only", action="store_true",
        help="Don't build anything: run the preflight check against an "
             "existing bundle at --output and exit. Use this on a bundle "
             "you've already copied to its share.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show the plan (platform, versions, destinations) and exit "
             "without downloading anything.")
    parser.add_argument(
        "--archive", nargs="?", const="auto", default=None,
        choices=["auto", "zip", "tar", "tar.gz"], metavar="{zip,tar,tar.gz}",
        help="After building, also pack the whole bundle into one archive "
             "file next to it -- one file to carry across the air gap "
             "instead of a folder tree. Bare --archive picks zip on "
             "Windows, tar.gz elsewhere; pass a format to choose "
             "explicitly. The folder itself is left in place either way.")
    parser.add_argument(
        "--bundle", metavar="PATH",
        help="The offline-bundle.toml declaring what this share contains -- "
             "the superset profiles are validated against. Defaults to "
             "offline-bundle.toml next to global.conf if it exists. Pass "
             "--bundle= (empty) to ignore it.")
    parser.add_argument(
        "--check-profile", metavar="PATH", action="append",
        dest="check_profiles", default=None,
        help="Validate this profile against the bundle (before and after "
             "building) without adding anything to it. Repeatable -- one "
             "bundle commonly serves several teams.")
    parser.add_argument(
        "--profile", metavar="PATH",
        help="Deployment profile whose venv packages must be in the bundle. "
             "Only stocks the bundle when there is no offline-bundle.toml; "
             "with one, the superset is already declared and this profile is "
             "validated against it instead. Defaults to profile.toml next to "
             "global.conf. Pass --profile= (empty) to ignore it.")
    parser.add_argument(
        "--accept-third-party-terms", action="store_true",
        help="Acknowledge that you hold the rights to redistribute the "
             "restricted components this bundle will contain (VS Code and "
             "Marketplace extensions). Required for unattended builds that "
             "include them; --yes deliberately does NOT cover this. See "
             "docs/LICENSING.md.")
    args = parser.parse_args(argv)

    auto = args.yes
    output = Path(args.output).expanduser().resolve()
    system = platform.system()
    arch = normalized_arch(platform.machine())
    versions = [v.strip() for v in args.pythons.split(",") if v.strip()] or [""]
    extra_packages = [p.strip() for p in args.packages.split(",") if p.strip()]

    # offline-bundle.toml is the superset, and it stands alone: it says what
    # the share will hold without consulting any profile. The flags below
    # remain overrides for a one-off build.
    from seedling import bundle as bundle_mod, profile as profile_mod
    declared: bundle_mod.Bundle | None = None
    bundle_path = None
    if args.bundle is None:
        bundle_path = bundle_mod.find(REPO_ROOT)
    elif args.bundle:
        bundle_path = Path(args.bundle).expanduser()
    if bundle_path is not None:
        try:
            declared = bundle_mod.load(bundle_path)
        except bundle_mod.BundleError as e:
            warn(f"{bundle_path}: {e}")
            info("Fix it, or pass --bundle= to build without it.")
            return 2

    # --profile is the pre-bundle way to stock the wheel set: with no
    # offline-bundle.toml, a profile is still the best statement of what a
    # fleet needs. With one, the superset is already declared, so a profile
    # is something to CHECK against it, never something to grow it -- a
    # superset assembled from the profile it judges can never say no.
    profile_packages: list[str] = []
    profile_tools: list[str] = []
    legacy_profile = None
    if args.profile is None and declared is None:
        # seedling-profile.toml is the pre-rename name, still picked up so a
        # bundle built from an un-renamed copy keeps covering its profile.
        legacy_profile = next(
            (REPO_ROOT / name for name in ("profile.toml",
                                           "seedling-profile.toml")
             if (REPO_ROOT / name).is_file()), None)
    elif args.profile:
        legacy_profile = Path(args.profile).expanduser()

    check_paths = [Path(p).expanduser() for p in (args.check_profiles or [])]
    if legacy_profile is not None and declared is not None:
        # Both given: the declaration wins on contents, and the profile joins
        # the ones being validated rather than silently widening the bundle.
        check_paths.append(legacy_profile)
        legacy_profile = None

    if legacy_profile is not None:
        try:
            loaded = profile_mod.load(legacy_profile)
        except profile_mod.ProfileError as e:
            warn(f"{legacy_profile}: {e}")
            info("Fix the profile, or pass --profile= to build without it.")
            return 2
        profile_packages = loaded.package_set()
        profile_tools = loaded.tool_set()

    profiles: list[profile_mod.Profile] = []
    for path in check_paths:
        try:
            profiles.append(profile_mod.load(path))
        except profile_mod.ProfileError as e:
            warn(f"{path}: {e}")
            return 2

    # Checked against the DECLARATION before anything is downloaded: with the
    # superset stated outright, every axis is judged here -- packages, tools,
    # interpreters, editor, repo extras. Reality is checked again after the
    # build, since a declaration can promise what a download failed to deliver.
    if declared is not None and profiles:
        intent = bundle_mod.Inventory.from_bundle(declared)
        blocking: list[str] = []
        for path, prof in zip(check_paths, profiles):
            for problem in bundle_mod.check_profile(prof, intent):
                blocking.append(f"{Path(path).name}: {problem}")
        if blocking:
            print()
            warn("These profiles can't be satisfied by the bundle as declared:")
            for line in blocking:
                print(f"  - {line}")
            info("Nothing was downloaded. Fix offline-bundle.toml (or the "
                 "profile) and re-run.")
            return 2

    extra_tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    if declared is not None:
        extra_tools += declared.tools
        extra_packages += declared.packages
        if not args.pythons and declared.pythons:
            versions = list(declared.pythons)
        if declared.mingit:
            args.mingit = True
        if not declared.vscode:
            args.no_vscode = True
    conda_tools = list(dict.fromkeys(extra_tools + profile_tools))

    packages = REQUIRED_PACKAGES + [
        p for p in extra_packages + profile_packages
        if p not in REQUIRED_PACKAGES]
    # De-duplicate while preserving order (a profile and --packages may
    # legitimately name the same thing).
    packages = list(dict.fromkeys(packages))

    # --verify-only: check a bundle that already exists (typically one already
    # copied to its share) and exit. Nothing is downloaded or written.
    if args.verify_only:
        print(colors.bold("seedling offline bundle -- preflight check"))
        print(f"  Bundle: {output}")
        seedling_copy = output / "seedling"
        if not seedling_copy.is_dir():
            warn(f"No bundle found at {output} (expected a seedling/ folder).")
            return 2
        exe_name = "uv.exe" if system == "Windows" else "uv"
        step(1, "Verify the bundle installs offline")
        return 0 if verify_bundle(output, seedling_copy,
                                  seedling_copy / "vendor" / "uv" / exe_name,
                                  packages) else 1

    print(colors.bold("seedling offline bundle builder"))
    print("Builds a folder you carry to an air-gapped machine and install from")
    print("with no internet. Run this on a connected machine. Full guide: "
          "docs/OFFLINE.md")
    print()
    print(f"  Building on : {system} / {arch}")
    print("  " + colors.warn(
        "The bundle targets THIS platform. Build on the same OS/arch as your "
        "offline machines."))
    # A spec that names its target platform is checked against the machine
    # doing the building. Getting this wrong produces a bundle that builds
    # cleanly and then can't install anywhere it's carried -- the failure this
    # warning has always described, now caught instead of narrated.
    if declared is not None and declared.platform:
        want = declared.platform.strip().lower()
        have = f"{system}/{arch}".lower()
        if want != have:
            print()
            warn(f"offline-bundle.toml targets {declared.platform}, but this "
                 f"machine is {system}/{arch}.")
            info("Build on that platform, or change `platform` in the spec. "
                 "Wheels, uv, the interpreters and the editor are all "
                 "platform-specific.")
            return 2
    print(f"  Output      : {output}")
    # --deploy-root, else the spec's, else the output folder itself. The spec
    # is where a share's real path belongs: it doesn't change between builds,
    # and retyping it on every rebuild is how a bundle ends up with a
    # global.conf pointing at someone's scratch directory.
    deploy_root = (args.deploy_root or (declared.deploy_root if declared else None)
                   or str(output)).rstrip("/\\")
    print(f"  Deploy path : {deploy_root}  (edit global.conf if this changes)")
    floor = seedling_python_floor()
    floor_note = (f"  (seedling itself needs >={'.'.join(str(p) for p in floor)})"
                  if floor else "")
    print(f"  Python      : {', '.join(v or 'newest' for v in versions)}{floor_note}")
    print(f"  Wheels      : {', '.join(packages)}")
    if conda_tools:
        print(f"  Conda tools : {', '.join(conda_tools)}  (via micromamba)")
    if bundle_path is not None and declared is not None:
        print(f"  Bundle spec : {bundle_path}")
    for path in check_paths:
        print(f"  Checking    : {path}  (validated, never folded in)")
    if profile_packages:
        print(f"  Profile     : {legacy_profile}  (contributed "
              f"{len(set(profile_packages))} package(s))")
    print(f"  VS Code     : {'skipped (--no-vscode)' if args.no_vscode else 'yes (~300MB, with extensions)'}")
    if system == "Windows":
        print(f"  MinGit      : {'yes (--mingit)' if args.mingit else 'no (pass --mingit to include it)'}")

    # Fail BEFORE downloading anything: an interpreter set that can't run
    # seedling produces a bundle that builds cleanly here and only breaks on the
    # air-gapped side, after it's been carried to the share.
    version_error = check_python_versions(versions, floor)
    if version_error:
        print()
        warn(version_error)
        return 2

    # What this bundle will contain, licence-wise. Computed from the same
    # settings the editor steps below actually use, so the notice can't drift
    # from what gets staged.
    from seedling.commands import vscode_cmd
    try:
        editor_flavor = vscode_cmd.flavor()
    except vscode_cmd.UnknownFlavor as e:
        print()
        warn(str(e))
        info("Refusing to guess: picking the wrong build here decides what "
             "licence terms this bundle carries.")
        return 2
    components = planned_components(
        vscode=not args.no_vscode,
        mingit=(system == "Windows" and args.mingit),
        flavor=editor_flavor,
        gallery_overridden=bool(vscode_cmd.gallery_for(editor_flavor)),
        conda=bool(conda_tools),
    )

    if args.dry_run:
        third_party_gate(components, accepted=args.accept_third_party_terms,
                         informational=True)
        print()
        print(colors.header("Dry run -- nothing downloaded. Re-run without "
                            "--dry-run to build."))
        return 0

    if not third_party_gate(components,
                            accepted=args.accept_third_party_terms):
        return 2

    print()
    if not ask("Ready to build the bundle here?", default=True, auto=auto):
        print("Aborted; nothing was written.")
        return 0

    output.mkdir(parents=True, exist_ok=True)
    python_builds = output / "python-builds"
    wheels = output / "wheels"
    # uv's download cache lives in the system temp dir, NOT inside the bundle --
    # otherwise it would be copied to the share. Reused across runs to speed
    # re-builds.
    cache = Path(tempfile.gettempdir()) / "seedling-offline-cache"

    # 1. Stage the repo copy (everything else lands relative to it).
    step(1, "Stage the seedling source")
    info("A copy of this repo is what your users actually install from; the "
         "downloads below fill in its vendor/ folder and its siblings.")
    seedling_copy = stage_repo(output)
    vendor = seedling_copy / "vendor"

    # 2. uv (required -- nothing else can be resolved without it).
    step(2, "uv binary (required)")
    info("seedling never assumes uv is installed; it ships this exact binary "
         "in vendor/uv/ and runs it directly.")
    uv_exe = None
    if ask("Download uv now?", default=True, auto=auto):
        uv_exe = build_uv(vendor / "uv", system, arch)
    if uv_exe is None:
        warn("Without uv, the interpreter mirror and wheels can't be built.")
        if not (vendor / "uv").exists():
            warn("Fix the uv step and re-run to finish the bundle.")

    # 3. Python interpreter mirror (required for a working default env).
    step(3, "Python interpreters (SEEDLING_PYTHON_MIRROR)")
    info("`seed python` downloads CPython from the internet; offline it reads "
         "these mirrored archives instead.")
    mirrored_versions: list[str] = []
    if uv_exe and ask("Mirror the Python interpreter archive(s) now?",
                      default=True, auto=auto):
        mirrored_versions = build_python_mirror(uv_exe, versions, python_builds,
                                                cache)
    elif not uv_exe:
        warn("Skipped -- needs uv (step 2).")
    mirror_ok = bool(mirrored_versions)

    # 4. Wheel index (required -- hatchling builds seed-cli).
    step(4, "Python packages (SEEDLING_PACKAGE_INDEX)")
    info("Every package install (incl. building seed-cli with hatchling, and "
         "each new venv) resolves from this wheel folder offline.")
    wheels_ok = False
    if uv_exe and ask("Download the wheels now?", default=True, auto=auto):
        # Target EVERY interpreter we mirrored, so abi/platform wheels match
        # each of them; fall back to the explicit --python list if the mirror
        # step was skipped, and to no pin at all if neither is known.
        py_for_wheels = mirrored_versions or [v for v in versions if v]
        wheels_ok = build_wheels(uv_exe, packages, wheels, py_for_wheels, cache)
    elif not uv_exe:
        warn("Skipped -- needs uv (step 2).")

    # 5. conda-forge tools (optional -- vendors micromamba + a conda channel).
    step(5, "conda-forge tools (SEEDLING_CONDA_CHANNEL, optional)")
    conda_ok = False
    conda_pkg_count = 0
    conda_channel_dir = output / "conda-channel"
    if not conda_tools:
        info("No conda-forge tools requested (--tools, or a profile's [tools]). "
             "Skipped.")
    elif ask(f"Bundle {len(conda_tools)} conda-forge tool(s) now? "
             f"({', '.join(conda_tools)})", default=True, auto=auto):
        info("Vendors micromamba and builds a conda channel into the bundle so "
             "`seed forge-install` runs with no internet on the target machine.")
        conda_ok, conda_pkg_count = build_conda_channel(
            vendor / "micromamba", conda_channel_dir, conda_tools)

    # 6. MinGit (optional, Windows).
    step(6, "git for Windows (optional)")
    info("Only needed if your offline machines have no system git and you use "
         "`seed repo-clone` or URL-based `seed update-commands`.")
    if system == "Windows":
        # Off unless asked for: most fleets already have git. --mingit flips the
        # default, which is also what makes this step reachable under --yes.
        if ask("Download portable MinGit into vendor/git/?",
               default=args.mingit, auto=auto):
            build_mingit(vendor / "git")
    else:
        info("Building on a non-Windows host; MinGit is Windows-only. Skipped.")

    # 7. VS Code + extensions (optional, automated -- the heavy one).
    step(7, "VS Code + extensions (optional, ~300MB)")
    info("Pre-seeds the portable VS Code and the default extensions (Python, "
         "Jupyter, ruff) into vendor/vscode/, so offline machines get the "
         "editor with no marketplace access. Everything else works without it.")
    vscode_wanted = False
    vscode_ok = False
    if args.no_vscode:
        info("Skipped (--no-vscode).")
    elif ask("Download VS Code + extensions now? (~300MB)",
             default=True, auto=auto):
        vscode_wanted = True
        # NB: staging dir must NOT be dot-prefixed -- the VS Code CLI fails
        # extension signature verification under a `.`-leading path component.
        vscode_ok = build_vscode(vendor / "vscode", output / "vscode-staging")

    # 8. Corporate CA certs (optional, user-supplied).
    step(8, "Corporate CA certificates (optional)")
    if ask("Create a vendor/certs/ folder for your CA bundle?",
           default=False, auto=auto):
        (vendor / "certs").mkdir(parents=True, exist_ok=True)
        info(f"Drop your .pem/.crt files into {vendor / 'certs'} -- the "
             "installer trusts them everywhere (uv, git, downloads).")
    else:
        info("Skip unless a TLS-inspecting proxy re-signs HTTPS on your network.")

    # 9. global.conf.
    step(9, "Write global.conf")
    conf_values = {
        "SEEDLING_REPO_URL": f"{deploy_root}\\seedling" if system == "Windows"
        else f"{deploy_root}/seedling",
        "SEEDLING_PYTHON_MIRROR": f"{deploy_root}\\python-builds"
        if system == "Windows" else f"{deploy_root}/python-builds",
        "SEEDLING_PACKAGE_INDEX": f"{deploy_root}\\wheels" if system == "Windows"
        else f"{deploy_root}/wheels",
    }
    if conda_ok:
        # Point forge-install at the bundled channel; the local-channel path in
        # conda_tool then installs from it offline.
        conf_values["SEEDLING_CONDA_CHANNEL"] = (
            f"{deploy_root}\\conda-channel" if system == "Windows"
            else f"{deploy_root}/conda-channel")
    write_conf(seedling_copy / "global.conf", conf_values)
    ok(f"Wrote {seedling_copy / 'global.conf'} pointing at {deploy_root}.")
    for k, v in conf_values.items():
        info(f"  {k}={v}")

    # 9. Preflight: prove the bundle installs before it leaves this machine.
    step(10, "Verify the bundle installs offline")
    info("Installs from the bundle with the network refused and a cold cache, "
         "so a missing wheel or interpreter surfaces HERE rather than in the "
         "air-gapped room.")
    verified = None
    if args.no_verify:
        info("Skipped (--no-verify).")
    elif uv_exe is None:
        warn("Skipped -- needs uv (step 2).")
    elif ask("Run the preflight check now?", default=True, auto=auto):
        verified = verify_bundle(output, seedling_copy, uv_exe, packages)

    # Every profile against what ACTUALLY landed, not what was declared. This
    # is the check that catches a `pip download` that failed for one package,
    # a tool the channel couldn't solve, or an editor step that was skipped --
    # none of which the pre-build gate can see, and all of which otherwise
    # surface as a failed install on the far side of the air gap.
    profiles_ok = True
    if profiles:
        step(11, "Check every profile against the finished bundle")
        real = bundle_mod.Inventory.discover(output)
        for path, prof in zip(check_paths, profiles):
            problems = bundle_mod.check_profile(prof, real)
            if not problems:
                ok(f"{Path(path).name}: applies cleanly against this bundle.")
                continue
            profiles_ok = False
            warn(f"{Path(path).name}: {len(problems)} thing(s) missing:")
            for problem in problems:
                print(f"    - {problem}")
        if not profiles_ok:
            info("Users on the air-gapped side would hit these. Add what's "
                 "missing to offline-bundle.toml and re-run.")

    # 10. Manifest: what actually landed, and under what terms. Written from
    # the real outcomes above, so a partial build produces an honest record
    # rather than a description of what was intended.
    step(12, "Record what was staged (MANIFEST.json)")
    staged = {
        "uv": uv_exe is not None,
        "python-build-standalone": mirror_ok,
        "python-packages": wheels_ok,
        "mingit": (vendor / "git").exists(),
        "vscode": vscode_ok and editor_flavor != "vscodium",
        "vscode-extensions": vscode_ok and editor_flavor != "vscodium",
        "vscodium": vscode_ok and editor_flavor == "vscodium",
        "openvsx-extensions": vscode_ok and editor_flavor == "vscodium",
        "micromamba": conda_ok,
        "conda-forge-tools": conda_ok,
        "python-build-standalone:version": ", ".join(mirrored_versions) or None,
        "conda-forge-tools:version": (", ".join(conda_tools)
                                      if conda_ok else None),
    }
    manifest_path = write_manifest(output, components, staged=staged)
    ok(f"Wrote {manifest_path}")
    info("Hand this to whoever asks what the bundle contains -- it lists "
         "every component, its source, and its licence.")

    # 11. Archive (optional): one file instead of a folder tree to carry
    # across the air gap. Never fatal -- the folder on disk is already a
    # complete, usable bundle on its own.
    archive_path = None
    if args.archive:
        archive_fmt = resolve_archive_format(args.archive, system)
        step(13, f"Archive the bundle ({archive_fmt})")
        info("Packing the whole bundle into one file -- this can take a "
             "while for a large bundle (VS Code alone is ~300MB).")
        archive_path = archive_bundle(output, archive_fmt)
        if archive_path is not None:
            size_mb = archive_path.stat().st_size / (1024 * 1024)
            ok(f"Wrote {archive_path}  ({size_mb:.0f} MB)")

    # Summary.
    print()
    print(colors.header("Done. Bundle assembled at:"))
    print(f"  {output}")
    print()
    def layout(rel: str, note: str, state: str = "") -> None:
        """One aligned `<path>  <- <what it is>  <state>` row."""
        print(f"  {output}{os.sep}{rel.ljust(24)}<- {note}"
              + (f"  {state}" if state else ""))

    print("Layout:")
    layout("MANIFEST.json", "what was staged, and under what licence")
    layout(f"seedling{os.sep}", "users run install.cmd from here")
    layout(f"python-builds{os.sep}", "SEEDLING_PYTHON_MIRROR",
           "(populated)" if mirror_ok else colors.warn("(empty -- redo step 3)"))
    layout(f"wheels{os.sep}", "SEEDLING_PACKAGE_INDEX",
           # "incomplete", not "empty": with several interpreters mirrored, one
           # failed pass leaves real wheels behind but an unusable bundle.
           "(populated)" if wheels_ok
           else colors.warn("(incomplete -- redo step 4)"))
    if conda_tools:
        layout(f"conda-channel{os.sep}", "SEEDLING_CONDA_CHANNEL",
               f"({conda_pkg_count} pkgs)" if conda_ok
               else colors.warn("(missing -- redo step 5)"))
    if vscode_wanted:
        layout(f"seedling{os.sep}vendor{os.sep}vscode{os.sep}", "pre-seeded VS Code",
               "(populated)" if vscode_ok
               else colors.warn("(missing -- redo step 6)"))
    print()
    print()
    if verified is True:
        print(colors.ok("Preflight: this bundle was installed offline here, "
                        "successfully."))
    elif verified is False:
        print(colors.warn(
            "Preflight FAILED (details above). Fix the steps it named and "
            "re-check with:"))
        print(f"  build-offline{'.cmd' if system == 'Windows' else '.sh'} "
              f"--verify-only -o {output}")
    else:
        print(colors.warn(
            "Preflight was not run, so nothing has confirmed this bundle "
            "installs. Check it with:"))
        print(f"  build-offline{'.cmd' if system == 'Windows' else '.sh'} "
              f"--verify-only -o {output}")

    print()
    print("Next steps:")
    if archive_path is not None:
        print(f"  1. Copy {archive_path.name} to {deploy_root} on your "
              "target/share -- one file, instead of the whole folder tree.")
        print(f"  2. Extract it there (it unpacks to one {output.name}{os.sep} "
              "folder, same layout as the build).")
        print("  3. On an offline machine, run install.cmd from the extracted "
              "seedling/ folder.")
        print("  4. It reads global.conf and installs entirely from the bundle.")
        print("     (After extracting on the share, you can re-run "
              "--verify-only against THAT copy to prove the transfer -- "
              "archive included -- was complete.)")
    else:
        print(f"  1. Copy the whole {output.name}{os.sep} folder to {deploy_root} on "
              "your target/share.")
        print("  2. On an offline machine, run install.cmd from the copied "
              "seedling/ folder.")
        print("  3. It reads global.conf and installs entirely from the bundle.")
        print("     (After copying, you can re-run --verify-only against the copy "
              "to prove the transfer was complete.)")
    if deploy_root == str(output):
        warn("Deploy path = the build path. If you move the folder, update the "
             "three paths in seedling/global.conf (or re-run with "
             "--deploy-root).")
    # A bundle that can't satisfy its own profiles is a failed build, even
    # though every download succeeded: carrying it in would hand the failure
    # to users who can't fix it from there.
    return 0 if profiles_ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(130)
