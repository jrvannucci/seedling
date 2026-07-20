#!/usr/bin/env python3
"""
build_offline.py -- assemble a self-contained, air-gapped seedling bundle.

Run this on a CONNECTED machine (it needs the internet). It downloads every
piece an offline install needs, lays them out the way seedling expects, writes
a matching seedling.conf, and walks you through each step -- asking before it
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
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
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
from seedling import colors, download  # noqa: E402

UV_LATEST_URL = "https://github.com/astral-sh/uv/releases/latest/download/{asset}"
PBS_RELEASE_BASE = ("https://github.com/astral-sh/python-build-standalone"
                    "/releases/download")
GIT_WIN_LATEST_API = "https://api.github.com/repos/git-for-windows/git/releases/latest"

# What the offline package index MUST contain (see docs/OFFLINE.md #4):
#   hatchling  -- uv builds seed-cli from source with it, at install AND every
#                 `seed update-commands`; without it the install can't finish.
#   the default venv packages -- created in every new venv.
# Extra packages your users will `seed install` get appended with --packages.
REQUIRED_PACKAGES = ["hatchling", "ipython", "ruff", "ipykernel", "pip"]

SRC_PYPROJECT = REPO_ROOT / "src" / "pyproject.toml"


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
def _uv_env(*, cache: Path, extra: dict | None = None) -> dict:
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = str(cache)
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
    `uvx pip download` -- the same mechanism as `seed download-whl`.

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
    seedling.conf, and get a bundle that looked freshly built around stale
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
    """Set KEY="value" entries in a seedling.conf, replacing existing lines and
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
             r"S:\tools). seedling.conf is written with paths under it. "
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
    args = parser.parse_args(argv)

    auto = args.yes
    output = Path(args.output).expanduser().resolve()
    system = platform.system()
    arch = normalized_arch(platform.machine())
    versions = [v.strip() for v in args.pythons.split(",") if v.strip()] or [""]
    extra_packages = [p.strip() for p in args.packages.split(",") if p.strip()]
    packages = REQUIRED_PACKAGES + [p for p in extra_packages
                                    if p not in REQUIRED_PACKAGES]

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
    print(f"  Output      : {output}")
    deploy_root = (args.deploy_root or str(output)).rstrip("/\\")
    print(f"  Deploy path : {deploy_root}  (edit seedling.conf if this changes)")
    floor = seedling_python_floor()
    floor_note = (f"  (seedling itself needs >={'.'.join(str(p) for p in floor)})"
                  if floor else "")
    print(f"  Python      : {', '.join(v or 'newest' for v in versions)}{floor_note}")
    print(f"  Wheels      : {', '.join(packages)}")
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

    if args.dry_run:
        print()
        print(colors.header("Dry run -- nothing downloaded. Re-run without "
                            "--dry-run to build."))
        return 0

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

    # 5. MinGit (optional, Windows).
    step(5, "git for Windows (optional)")
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

    # 6. VS Code + extensions (optional, automated -- the heavy one).
    step(6, "VS Code + extensions (optional, ~300MB)")
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

    # 7. Corporate CA certs (optional, user-supplied).
    step(7, "Corporate CA certificates (optional)")
    if ask("Create a vendor/certs/ folder for your CA bundle?",
           default=False, auto=auto):
        (vendor / "certs").mkdir(parents=True, exist_ok=True)
        info(f"Drop your .pem/.crt files into {vendor / 'certs'} -- the "
             "installer trusts them everywhere (uv, git, downloads).")
    else:
        info("Skip unless a TLS-inspecting proxy re-signs HTTPS on your network.")

    # 8. seedling.conf.
    step(8, "Write seedling.conf")
    conf_values = {
        "SEEDLING_REPO_URL": f"{deploy_root}\\seedling" if system == "Windows"
        else f"{deploy_root}/seedling",
        "SEEDLING_PYTHON_MIRROR": f"{deploy_root}\\python-builds"
        if system == "Windows" else f"{deploy_root}/python-builds",
        "SEEDLING_PACKAGE_INDEX": f"{deploy_root}\\wheels" if system == "Windows"
        else f"{deploy_root}/wheels",
    }
    write_conf(seedling_copy / "seedling.conf", conf_values)
    ok(f"Wrote {seedling_copy / 'seedling.conf'} pointing at {deploy_root}.")
    for k, v in conf_values.items():
        info(f"  {k}={v}")

    # 9. Preflight: prove the bundle installs before it leaves this machine.
    step(9, "Verify the bundle installs offline")
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
    layout(f"seedling{os.sep}", "users run install.cmd from here")
    layout(f"python-builds{os.sep}", "SEEDLING_PYTHON_MIRROR",
           "(populated)" if mirror_ok else colors.warn("(empty -- redo step 3)"))
    layout(f"wheels{os.sep}", "SEEDLING_PACKAGE_INDEX",
           # "incomplete", not "empty": with several interpreters mirrored, one
           # failed pass leaves real wheels behind but an unusable bundle.
           "(populated)" if wheels_ok
           else colors.warn("(incomplete -- redo step 4)"))
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
    print(f"  1. Copy the whole {output.name}{os.sep} folder to {deploy_root} on "
          "your target/share.")
    print("  2. On an offline machine, run install.cmd from the copied "
          "seedling/ folder.")
    print("  3. It reads seedling.conf and installs entirely from the bundle.")
    print("     (After copying, you can re-run --verify-only against the copy "
          "to prove the transfer was complete.)")
    if deploy_root == str(output):
        warn("Deploy path = the build path. If you move the folder, update the "
             "three paths in seedling/seedling.conf (or re-run with "
             "--deploy-root).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(130)
