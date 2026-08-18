"""
`seed download-whls` / `seed download-requirements` -- build an offline wheel
bundle on a connected machine that can then feed an air-gapped install --
and `seed upload-whls`, which pushes one into an internal index instead.

Both shell out to `uvx pip download` (uv has no `pip download` of its own, so
pip is run as an ephemeral uv tool -- nothing is installed permanently). The
result is a flat directory of `.whl` files (plus any source archives) that is
exactly what seedling's `package_index` setting consumes on the offline side:

    (connected)  seed download-whls pandas
    (copy the ./wheelhouse folder to the offline machine or a share)
    (offline)    seed config set package_index <that-folder>
                 seed install pandas

Every `pip download` flag passes straight through, so cross-platform bundles
(`--platform`, `--python-version`, `--only-binary=:all:`) and `--no-deps` all
work without seedling needing to know about them.

`upload-whls` is the mirror image, for the networks where the air gap has a
door: an internal PyPI that users CAN reach, which just doesn't have the
packages yet. Resolve the set on a connected machine, publish it once, and
every user installs from the index they already have -- no share to mount and
no directory index to configure. It runs `uvx twine upload`, the same
ephemeral-tool pattern, so nothing is installed permanently here either.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import colors, config, uv_tool

# pip's conventional name for a flat directory of wheels. Landed in the current
# directory (not ~/seedling) because a bundle is meant to be carried OFF this
# machine to a share or the air-gapped target.
DEFAULT_DEST = "wheelhouse"


def _has_own_dest(tokens: list[str]) -> bool:
    """True if the user already specified where to put the wheels, so we don't
    override them with the default."""
    for tok in tokens:
        if tok in ("-d", "--dest") or tok.startswith("--dest="):
            return True
    return False


def _index_and_cert_args() -> list[str]:
    """Translate seedling's `package_index` / `ca_cert` settings into the pip
    flags that honor them, so a configured corporate index or private CA is
    used automatically -- users never set PIP_* environment variables. Placed
    before the user's own tokens so an explicit `--index-url` still wins."""
    out: list[str] = []
    index = config.get("package_index")
    if index:
        index = str(index)
        if "://" in index:
            out += ["--index-url", index]
        else:
            # A plain directory of wheels: download (copy) from it with the
            # internet index disabled, mirroring the offline install path.
            out += ["--no-index", "--find-links", index]
    ca = config.get("ca_cert")
    if ca:
        ca_path = Path(str(ca)).expanduser()
        if ca_path.is_file():
            out += ["--cert", str(ca_path)]
    return out


def _download(tokens: list[str]) -> int:
    """Run `uvx pip download` with `tokens` (specifiers/flags the user gave),
    injecting a default destination when they didn't pick one, then report
    what landed and how to use it offline."""
    dest: Path | None = None
    if not _has_own_dest(tokens):
        dest = Path(DEFAULT_DEST).resolve()
        dest.mkdir(parents=True, exist_ok=True)
        tokens = ["--dest", str(dest), *tokens]

    uv_tool.run([
        "tool", "run", "--from", "pip", "pip", "download",
        *_index_and_cert_args(), *tokens,
    ])

    if dest is not None:
        _report(dest)
    return 0


def _report(dest: Path) -> None:
    wheels = list(dest.glob("*.whl"))
    others = [p for p in dest.iterdir() if p.is_file() and p.suffix != ".whl"]
    count = f"{len(wheels)} wheel" + ("" if len(wheels) == 1 else "s")
    if others:
        count += (f" (+{len(others)} source archive"
                  + ("" if len(others) == 1 else "s") + ")")
    print()
    print(colors.ok(f"Downloaded {count} into {dest}"))
    print("To install these on an offline machine:")
    print("  1. Copy this folder to the target machine or a shared drive.")
    print(f"  2. seed config set package_index {dest}")
    print("  3. seed install <package>   # now resolves from the folder, offline")


def run_whl(args) -> int:
    tokens = getattr(args, "args", None) or []
    if not tokens:
        print("Usage: seed download-whls <package> [<package> ...] [pip download flags]")
        print("Downloads each package AND all its dependencies as wheels "
              "(default: ./wheelhouse) for an offline install.")
        return 1
    return _download(tokens)


def run_requirements(args) -> int:
    tokens = getattr(args, "args", None) or []
    if not tokens:
        print("Usage: seed download-requirements <requirements.txt> [pip download flags]")
        print("Downloads every pinned package AND its dependencies as wheels "
              "(default: ./wheelhouse) for an offline install.")
        return 1
    req_file, rest = tokens[0], tokens[1:]
    if not Path(req_file).is_file():
        print(f"error: requirements file not found: {req_file}")
        return 1
    return _download(["-r", req_file, *rest])


# ---------------------------------------------------------------------------
# upload -- the other direction: a wheelhouse into an internal index
# ---------------------------------------------------------------------------

def _take_repository_url(tokens: list[str]) -> tuple[str | None, list[str]]:
    """Pull `--repository-url URL` (or `=URL`) out of the passthrough tokens,
    returning it and what's left for twine. Handled here rather than by
    argparse because this command's tokens are a REMAINDER -- which would
    otherwise swallow the directory positional."""
    url, rest, i = None, [], 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--repository-url" and i + 1 < len(tokens):
            url, i = tokens[i + 1], i + 2
            continue
        if tok.startswith("--repository-url="):
            url, i = tok.split("=", 1)[1], i + 1
            continue
        rest.append(tok)
        i += 1
    return url, rest


def _distributions(directory: Path) -> list[Path]:
    """Everything twine can publish from a wheelhouse. Sorted so the output
    order is stable and a partial upload is easy to resume by eye."""
    found = [p for p in sorted(directory.iterdir())
             if p.is_file() and (p.name.endswith(".whl")
                                 or p.name.endswith(".tar.gz")
                                 or p.name.endswith(".zip"))]
    return found


def run_upload(args) -> int:
    tokens = getattr(args, "args", None) or []
    flag_url, tokens = _take_repository_url(tokens)
    directory = next((tok for tok in tokens if not tok.startswith("-")), None)
    if not directory:
        print("Usage: seed upload-whls <dir> [--repository-url URL] "
              "[twine upload flags]")
        print("Publishes every wheel in <dir> to your internal package index.")
        return 1
    passthrough = [tok for tok in tokens if tok != directory]

    source = Path(directory).expanduser()
    if not source.is_dir():
        print(f"error: not a directory: {source}")
        return 1
    dists = _distributions(source)
    if not dists:
        print(f"Nothing to upload: no .whl or source archives in {source}")
        return 1

    url = flag_url or config.get("package_upload_url")
    url = str(url) if url else None
    token = config.get("package_upload_token")
    token = str(token) if token else None
    if not url:
        print("No upload URL configured. Set the one for your organization:")
        print("  seed config set package_upload_url "
              "https://pypi.corp.example/api/pypi/pypi-local/")
        print("...or pass it for one run:  --repository-url <url>")
        print("Note this is the UPLOAD endpoint, which is usually not the "
              "same URL as package_index.")
        return 1

    command = ["tool", "run", "--from", "twine", "twine", "upload",
               "--repository-url", url]
    ca = config.get("ca_cert")
    if ca:
        ca_path = Path(str(ca)).expanduser()
        if ca_path.is_file():
            # Same corporate-CA story as every other network call seedling
            # makes: an internal index behind a re-signing proxy is exactly
            # where this command is used.
            command += ["--cert", str(ca_path)]
    command += [*passthrough, *[str(p) for p in dists]]

    # The token goes through the environment, never argv: a command line is
    # visible to `ps`, lands in shell history, and is echoed into seedling's
    # own command log. twine's own env contract, so nothing bespoke to learn.
    env = None
    if token:
        env = {"TWINE_USERNAME": "__token__", "TWINE_PASSWORD": token}
    elif not os.environ.get("TWINE_PASSWORD"):
        print(colors.dim(
            "No package_upload_token set; twine will use TWINE_USERNAME/"
            "TWINE_PASSWORD or ~/.pypirc, and prompt if it finds neither."))

    print(f"Uploading {len(dists)} distribution(s) from {source}")
    print(f"  -> {url}")
    result = uv_tool.run(command, check=False, env=env)
    if result.returncode != 0:
        print(colors.warn("Upload failed (twine's output is above)."))
        print("Common causes: a token without write permission, the wrong "
              "repository URL, or a distribution that already exists in the "
              "index (twine refuses to overwrite by default).")
        return 1
    print()
    print(colors.ok(f"Published {len(dists)} distribution(s) to {url}"))
    print("On the target machines nothing changes: package_index already "
          "points at this index, so `seed install` resolves the new packages.")
    return 0
