"""
What licence is every package under, and which ones need a decision?

seedling's whole offline story is redistribution: a bundle copies wheels onto
a share, and copying is the act licences actually govern. The bundle manifest
has always named the licence of every component it stages -- uv, VS Code, the
interpreters, MinGit -- with one exception it papered over:

    "component": "python-packages",
    "license":   "per package -- see the wheel set"

One line standing in for two hundred distributions, asserting they're all
permissive without having looked. On a profile that installs Spyder that
assertion is simply wrong: PyQt6 is GPL-3.0-only.

This module answers it from metadata already on disk. No network (the machine
that needs this most has none), and no dependency (a wheel is a zip and its
METADATA is RFC 822 -- both stdlib), so seedling's "no third-party runtime
dependencies" claim survives.

Three sources, three shapes, one report:

    wheelhouse      <name>-<version>-*.whl        -> */METADATA in the zip
    venv            site-packages/*.dist-info/    -> METADATA on disk
    conda channel   <subdir>/repodata.json        -> each record's "license"
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from email.parser import BytesParser, Parser
from pathlib import Path

# Families, most restrictive first -- the order IS the logic. AGPL contains
# "GPL" and LGPL contains "GPL", so a looser pattern tested earlier would
# swallow both and report the wrong obligation.
FAMILIES: list[tuple[str, str]] = [
    ("copyleft-network", r"\bAGPL|Affero"),
    ("copyleft-weak", r"\bLGPL|Lesser General|\bMPL\b|Mozilla Public|\bEPL\b"
                      r"|Eclipse Public|\bCDDL\b"),
    ("copyleft", r"\bGPL|General Public License"),
    ("proprietary", r"proprietary|all rights reserved|Business Source"
                    r"|Elastic License|commercial"),
    ("public-domain", r"public domain|\bCC0\b|Unlicense|\bWTFPL\b"),
    ("permissive", r"\bMIT\b|\bBSD\b|Apache|\bISC\b|Python Software Foundation"
                   r"|\bPSF\b|\bZlib\b|\bHPND\b|Historical Permission"),
]

# How much attention each family deserves, most first. Deliberately NOT the
# order above: that one is dictated by pattern overlap (LGPL contains "GPL",
# so it has to be tested first), which would otherwise rank weak copyleft as
# more serious than GPL. Matching order and severity order are different
# questions, and conflating them is how a report buries the thing that
# matters under the thing that doesn't.
SEVERITY = [
    "proprietary",        # may forbid the copy outright
    "copyleft-network",   # AGPL: internal services count as distribution
    "copyleft",           # GPL: source obligation when distributing outward
    "copyleft-weak",      # LGPL/MPL: only if you modify the library
    "unknown",            # not a risk, an unanswered question
    "unclassified",
    "public-domain",
    "permissive",
]

# What each family asks of whoever copies the bundle onto a share. Kept here
# rather than in the printer because the manifest reports it too, and two
# copies of a licence summary is how they end up disagreeing.
OBLIGATIONS = {
    "permissive": "keep the copyright notice and licence text with the copy",
    "public-domain": "none",
    "copyleft-weak": "publish changes if you MODIFY the library itself",
    "copyleft": "recipients get source and the same rights; matters when "
                "distributing outside your organization",
    "copyleft-network": "as copyleft, and network users count as recipients",
    "proprietary": "redistribution may be forbidden outright -- read the terms",
    "unknown": "nobody declared one; resolve it by hand",
    "unclassified": "a licence seedling doesn't recognize -- read it before "
                    "redistributing",
}

# Everything except these wants a human to look at it once.
ROUTINE = {"permissive", "public-domain"}


@dataclass
class PackageLicence:
    name: str
    version: str
    licence: str | None
    source: str          # where the answer came from, so a claim can be weighed
    family: str
    files: list[str] = field(default_factory=list)

    @property
    def routine(self) -> bool:
        return self.family in ROUTINE

    def as_dict(self) -> dict:
        return {"name": self.name, "version": self.version,
                "license": self.licence, "family": self.family,
                "source": self.source, "license_files": self.files}


def family_of(text: str | None) -> str:
    if not text or not text.strip():
        return "unknown"
    for name, pattern in FAMILIES:
        if re.search(pattern, text, re.I):
            return name
    return "unclassified"


def resolve(headers) -> tuple[str | None, str]:
    """The licence and where it came from, best source first.

    `License-Expression` is PEP 639: SPDX, unambiguous, machine-comparable.
    The classifier is a coarser claim. The free-text `License` field is
    whatever the author typed ("BSD", "Apache 2.0", or occasionally the
    entire licence) -- usable, but it's why `source` is reported alongside.
    """
    expression = headers.get("License-Expression")
    if expression and expression.strip():
        return expression.strip(), "License-Expression"

    classifiers = [c for c in (headers.get_all("Classifier") or [])
                   if c.startswith("License ::")]
    if classifiers:
        # "License :: OSI Approved :: BSD License" -> "BSD License"
        return classifiers[0].split("::")[-1].strip(), "classifier"

    free = (headers.get("License") or "").strip()
    if free:
        first = free.splitlines()[0].strip()
        # Some projects paste the whole licence into this field; the first
        # line of it still identifies the licence, but say which it was.
        if len(free) > 200:
            return first, "License field (full text)"
        return first, "License field"
    return None, "none"


def _licence_files(headers, extra: list[str] | None = None) -> list[str]:
    declared = [f.strip() for f in (headers.get_all("License-File") or [])]
    return declared or (extra or [])


def _from_metadata(headers, files: list[str] | None = None) -> PackageLicence:
    licence, source = resolve(headers)
    return PackageLicence(
        name=headers.get("Name") or "?",
        version=headers.get("Version") or "?",
        licence=licence,
        source=source,
        family=family_of(licence),
        files=_licence_files(headers, files),
    )


# ---------------------------------------------------------------------------
# the three sources
# ---------------------------------------------------------------------------

def scan_wheelhouse(directory: Path) -> list[PackageLicence]:
    """Every `.whl` in a flat directory, read without installing anything.

    The admin's question -- what is about to go on the share -- answered on
    the connected machine, before a single package is installed anywhere."""
    out: list[PackageLicence] = []
    for wheel in sorted(Path(directory).glob("*.whl")):
        try:
            with zipfile.ZipFile(wheel) as zf:
                names = zf.namelist()
                meta = next((n for n in names
                             if n.endswith(".dist-info/METADATA")), None)
                if meta is None:
                    out.append(_unreadable(wheel, "no METADATA in the wheel"))
                    continue
                headers = BytesParser().parsebytes(zf.read(meta), headersonly=True)
                licence_files = [n for n in names
                                 if ".dist-info/" in n and _looks_like_licence(n)]
                out.append(_from_metadata(headers, licence_files))
        except (OSError, zipfile.BadZipFile, KeyError) as e:
            out.append(_unreadable(wheel, str(e)))
    return out


def scan_venv(site_packages: Path) -> list[PackageLicence]:
    """Every installed distribution in a site-packages directory."""
    out: list[PackageLicence] = []
    for info in sorted(Path(site_packages).glob("*.dist-info")):
        metadata = info / "METADATA"
        if not metadata.is_file():
            continue
        try:
            headers = Parser().parsestr(
                metadata.read_text(encoding="utf-8", errors="replace"),
                headersonly=True)
        except OSError:
            continue
        found = [str(p.relative_to(site_packages)).replace("\\", "/")
                 for p in info.rglob("*") if p.is_file() and _looks_like_licence(p.name)]
        out.append(_from_metadata(headers, found))
    return out


def scan_conda_channel(directory: Path) -> list[PackageLicence]:
    """Every package in a bundled conda channel, from its repodata.

    Read from repodata.json rather than the archives: a `.conda` is
    zstd-compressed, which the stdlib can't open, and the licence is in the
    index anyway."""
    seen: dict[tuple[str, str], PackageLicence] = {}
    for repodata in sorted(Path(directory).rglob("repodata.json")):
        try:
            data = json.loads(repodata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for table in ("packages", "packages.conda"):
            for record in (data.get(table) or {}).values():
                name = record.get("name")
                if not name:
                    continue
                licence = record.get("license")
                key = (name, record.get("version") or "?")
                # One package can appear in several subdirs (noarch + win-64);
                # they carry the same licence, so first one wins.
                seen.setdefault(key, PackageLicence(
                    name=name, version=key[1], licence=licence,
                    source="repodata" if licence else "none",
                    family=family_of(licence)))
    return [seen[k] for k in sorted(seen)]


def _looks_like_licence(name: str) -> bool:
    stem = Path(name).name.upper()
    return stem.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE"))


def _unreadable(path: Path, why: str) -> PackageLicence:
    return PackageLicence(name=path.stem.split("-")[0], version="?",
                          licence=None, source=f"unreadable: {why}",
                          family="unknown")


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def summarize(packages: list[PackageLicence]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in packages:
        counts[p.family] = counts.get(p.family, 0) + 1
    # Most-serious first, so the thing to worry about is never buried under
    # the 157 permissive ones.
    return {f: counts[f] for f in SEVERITY if f in counts}


def needs_attention(packages: list[PackageLicence]) -> list[PackageLicence]:
    """Everything that isn't routine, most restrictive first."""
    rank = {f: i for i, f in enumerate(SEVERITY)}
    return sorted((p for p in packages if not p.routine),
                  key=lambda p: (rank.get(p.family, 99), p.name.lower()))


def as_manifest_entry(packages: list[PackageLicence], *, limit: int = 25) -> dict:
    """The shape the bundle manifest embeds: the summary a reviewer reads,
    the exceptions they act on, and a full count so the sample is honest."""
    attention = needs_attention(packages)
    entry = {
        "total": len(packages),
        "summary": summarize(packages),
        "attention": [p.as_dict() for p in attention[:limit]],
    }
    if len(attention) > limit:
        entry["attention_truncated"] = len(attention) - limit
    return entry
