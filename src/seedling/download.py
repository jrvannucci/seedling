"""
Shared, checksum-verifying download helper for everything seedling pulls
off the network itself (MinGit, VS Code). Publishers expose SHA-256 digests
for these artifacts (GitHub release asset digests, VS Code's update API);
verifying them catches both corrupted transfers and tampered-with files
before anything gets extracted or executed.

Verification policy:
  - a checksum is available and matches   -> proceed silently
  - a checksum is available and MISMATCHES -> delete the file, raise
    (never extract/run something that fails verification)
  - no checksum could be obtained          -> download anyway, but say so
    (some sources may be unreachable/changed; refusing outright would
    break installs on networks that block the metadata endpoint)
"""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import urllib.request
from pathlib import Path

from . import colors


class ChecksumMismatch(RuntimeError):
    pass


def extract_tar(archive: Path, dest: Path) -> None:
    """Extract a tarball into `dest` with an explicit member filter.

    Python 3.14 makes the 'data' filter the default for extractall(), and
    3.12/3.13 emit a DeprecationWarning about that change. Passing it
    explicitly pins ONE behavior across every interpreter seedling supports,
    on our schedule rather than an interpreter upgrade's -- and it refuses
    members that would write outside `dest` (absolute paths, `..`, links
    escaping the tree).

    The `filter=` argument was backported to 3.9.17 / 3.10.12 / 3.11.4, so on
    an older patch release of those lines it isn't accepted; `tarfile.data_filter`
    is the feature probe. There we fall back to the unfiltered call, which is
    exactly what those interpreters do today.

    (Zip archives need no equivalent: ZipFile.extractall already sanitizes
    member paths, stripping drive letters, leading separators and `..`.)"""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as t:
        if hasattr(tarfile, "data_filter"):
            t.extractall(dest, filter="data")
        else:  # pragma: no cover -- pre-backport 3.9/3.10/3.11 patch releases
            t.extractall(dest)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path, *, expected_sha256: str | None = None,
          label: str = "file",
          on_progress=None) -> None:
    """Download `url` to `dest`, verifying its SHA-256 when one is known.
    `expected_sha256` accepts bare hex or the 'sha256:<hex>' form GitHub's
    API uses. Raises ChecksumMismatch (and removes the file) on mismatch.

    `on_progress(done_bytes, total_bytes)` is called after every chunk;
    `total_bytes` is 0 when the server sent no Content-Length. Callbacks are
    expected to do their own throttling."""
    req = urllib.request.Request(url, headers={"User-Agent": "seedling"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as f:
        if on_progress is None:
            shutil.copyfileobj(resp, f)
        else:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                on_progress(done, total)

    if not expected_sha256:
        print(colors.warn(
            f"warning: no published checksum was available for {label}; "
            "skipping verification."))
        return

    expected = expected_sha256.lower().removeprefix("sha256:")
    actual = sha256_of(dest)
    if actual != expected:
        dest.unlink(missing_ok=True)
        raise ChecksumMismatch(
            f"SHA-256 verification FAILED for {label}.\n"
            f"  expected: {expected}\n"
            f"  actual:   {actual}\n"
            f"The download was deleted. This can mean a corrupted transfer, "
            f"a proxy rewriting the file, or tampering -- try again on a "
            f"trusted network."
        )
    print(f"Verified SHA-256 checksum for {label}.")
