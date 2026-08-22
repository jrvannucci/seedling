"""
`offline-bundle.toml` -- the superset an air-gapped share contains.

The third config file, and the one that answers a question the other two
can't. `global.conf` says where a machine gets things FROM; `profile.toml`
says what a group of users ends up WITH. Neither states what is actually
reachable, so until now a profile asking for something the share didn't have
failed on the air-gapped side, one user at a time, long after the bundle was
carried in.

This file states it once, standing alone, and profiles conform to IT:

    build time  -- the bundle is built from this file and nothing else.
    always      -- any profile, including one written months later by someone
                   on the air-gapped network, is checked against the bundle.

The dependency runs one way on purpose. A superset computed from the profiles
it ships can't refuse any of them -- it would grow to fit whatever was asked,
and "does this profile work here?" would answer itself. Declared outright, it
is a contract: the share holds this, and a profile that wants more is wrong
before anyone carries it inside.

The same validator runs over an `Inventory`, built two ways: from this file
(what the bundle WILL contain) or discovered from a bundle directory (what it
DOES contain). Intent and reality are then never checked by two different
code paths that can disagree.

Repos are deliberately absent. A profile's `[[repo]]` entries are cloned from
a git host on the CLOSED network, which the connected build machine cannot
reach -- so it can neither vendor them nor resolve their dependencies, and a
`[[repo]]` key here would promise a check nothing can honor. What a repo needs
from the wheelhouse goes in `packages`, named by the admin who knows it.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import profile as profile_mod

SCHEMA = 1

# The conventional filename, resolved next to global.conf.
LOCAL_NAME = "offline-bundle.toml"

# Every bundle holds these whether or not it says so: seedling itself is built
# with hatchling, and the default venv packages go into every venv `seed venv`
# creates. Declared here rather than in the builder so the validator and the
# download agree by construction -- a profile using the default packages must
# not be reported as unsatisfiable against a bundle that always carries them.
ALWAYS_PRESENT = ["hatchling", "ipython", "ruff", "ipykernel", "pip"]


# The wheel tags each supported platform installs. `pip download --platform`
# takes these, so ONE flat wheelhouse can serve a mixed fleet: the tags are
# what a target machine matches a wheel filename against.
#
# Linux lists several because a manylinux wheel is built to an older glibc and
# tagged accordingly -- a machine that accepts manylinux_2_17 also accepts
# manylinux2014 (the same ABI under its old name), and some projects publish
# only one of them.
PLATFORM_TAGS = {
    "windows/x86_64": ["win_amd64"],
    "windows/aarch64": ["win_arm64"],
    "linux/x86_64": ["manylinux2014_x86_64", "manylinux_2_17_x86_64",
                     "manylinux_2_28_x86_64"],
    "linux/aarch64": ["manylinux2014_aarch64", "manylinux_2_17_aarch64",
                      "manylinux_2_28_aarch64"],
    "darwin/x86_64": ["macosx_10_12_x86_64", "macosx_11_0_x86_64"],
    "darwin/aarch64": ["macosx_11_0_arm64", "macosx_12_0_arm64"],
}


def platform_tags(name: str) -> list[str]:
    """The `pip download --platform` values for a declared platform."""
    return PLATFORM_TAGS[name.strip().lower()]


class BundleError(ValueError):
    """A bundle declaration that cannot be built as written."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise BundleError(msg)


def canonical(name: str) -> str:
    """PEP 503 normalization -- `ruff_lsp`, `Ruff-LSP` and `ruff.lsp` all name
    the same distribution, and a wheel filename need not spell it the way a
    profile does."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def requirement_name(spec: str) -> str:
    """'pandas>=2.1' -> 'pandas'. Extras and markers dropped too: what the
    inventory holds is distributions, not specifiers."""
    for sep in ("[", "=", ">", "<", "!", "~", ";", " "):
        spec = spec.split(sep)[0]
    return canonical(spec)


def pinned_version(spec: str) -> str | None:
    """The exact version in `pandas==2.1.4`, else None. Only `==` counts: a
    range can be satisfied by whatever the wheelhouse happens to hold, but an
    exact pin either is there or the install fails."""
    m = re.match(r"^[^=<>!~\[; ]+\s*==\s*([^,;\s]+)$", spec.strip())
    return m.group(1) if m else None


@dataclass
class Bundle:
    path: Path | None = None
    # The fleet's platforms. The wheelhouse covers every one of them; the
    # platform-specific BINARIES (uv, interpreters, the editor) still come
    # from the machine that runs the build, so this is a statement about who
    # the bundle serves, checked against where it is being built.
    platforms: list[str] = field(default_factory=list)
    deploy_root: str | None = None
    pythons: list[str] = field(default_factory=list)
    # THE package set, not an addition to one: every distribution any profile
    # may name, plus whatever users should be able to `seed install` later.
    packages: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    editor_flavor: str = "microsoft"
    editor_extensions: list[str] = field(default_factory=list)
    extension_gallery: str | None = None
    vscode: bool = True
    mingit: bool = False
    # [build] -- what used to be command-line flags. They live here so the
    # whole build is one file plus one double-click, with nothing to remember
    # and nothing that differs between the admin who wrote it and the person
    # who re-runs it six months later.
    output: str | None = None
    profiles_dir: str = "installation-profile"
    # A bundle exists to be carried somewhere -- onto a share, through a
    # review, across an air gap -- and a folder of ~200k files is the wrong
    # shape for every one of those. Archiving is the default; `archive = false`
    # opts out for the case where the output folder IS the share.
    archive: str | None = "auto"
    verify: bool = True
    unattended: bool = False
    accept_third_party_terms: bool = False


def parse(text: str, path: Path | None = None) -> Bundle:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise BundleError(f"invalid TOML: {e}") from e

    schema = raw.get("schema", SCHEMA)
    _require(isinstance(schema, int) and schema <= SCHEMA,
             f"schema {schema!r} is newer than this seedling understands "
             f"(supported: {SCHEMA}). Update seedling first.")

    known = {"schema", "platforms", "deploy_root", "pythons", "packages",
             "tools", "editor", "git", "build"}
    unknown = sorted(set(raw) - known)
    _require(not unknown,
             f"unknown key(s): {', '.join(unknown)}. Known keys: "
             f"{', '.join(sorted(known))}")

    b = Bundle(path=path)
    b.platforms = _str_list(raw.get("platforms", []), "platforms")
    for name in b.platforms:
        _require(name.strip().lower() in PLATFORM_TAGS,
                 f"platforms: {name!r} isn't one seedling knows. Valid: "
                 + ", ".join(sorted(PLATFORM_TAGS)))
    b.deploy_root = _opt_str(raw.get("deploy_root"), "deploy_root")
    b.pythons = _str_list(raw.get("pythons", []), "pythons")
    b.tools = _str_list(raw.get("tools", []), "tools")
    b.packages = _str_list(raw.get("packages", []), "packages")

    editor = raw.get("editor", {})
    _require(isinstance(editor, dict), "[editor] must be a table")
    unknown = sorted(set(editor) - {"flavor", "extensions", "gallery", "stage"})
    _require(not unknown, f"[editor]: unknown key(s): {', '.join(unknown)}")
    flavor = editor.get("flavor", "microsoft")
    _require(isinstance(flavor, str) and flavor.strip().lower()
             in ("microsoft", "vscodium"),
             f"[editor] flavor must be \"microsoft\" or \"vscodium\", "
             f"not {flavor!r}")
    b.editor_flavor = flavor.strip().lower()
    b.editor_extensions = _str_list(editor.get("extensions", []),
                                    "[editor] extensions")
    b.extension_gallery = _opt_str(editor.get("gallery"), "[editor] gallery")
    stage = editor.get("stage", True)
    _require(isinstance(stage, bool), "[editor] stage must be true or false")
    b.vscode = stage

    build = raw.get("build", {})
    _require(isinstance(build, dict), "[build] must be a table")
    unknown = sorted(set(build) - {"output", "profiles", "archive", "verify",
                                   "unattended", "accept_third_party_terms"})
    _require(not unknown, f"[build]: unknown key(s): {', '.join(unknown)}")
    b.output = _opt_str(build.get("output"), "[build] output")
    b.profiles_dir = _opt_str(build.get("profiles"),
                              "[build] profiles") or b.profiles_dir
    archive = build.get("archive")
    if archive is False:
        # Explicitly off -- distinct from leaving the key out, which now
        # means "archive it, pick the format for me".
        b.archive = None
    elif archive is not None:
        if archive is True:
            archive = "auto"
        _require(isinstance(archive, str) and archive in
                 ("auto", "zip", "tar", "tar.gz"),
                 f"[build] archive must be true or one of auto/zip/tar/"
                 f"tar.gz, not {archive!r}")
        b.archive = archive
    for key, attr in (("verify", "verify"), ("unattended", "unattended"),
                      ("accept_third_party_terms", "accept_third_party_terms")):
        if key in build:
            _require(isinstance(build[key], bool),
                     f"[build] {key} must be true or false")
            setattr(b, attr, build[key])

    git = raw.get("git", {})
    _require(isinstance(git, dict), "[git] must be a table")
    unknown = sorted(set(git) - {"mingit"})
    _require(not unknown, f"[git]: unknown key(s): {', '.join(unknown)}")
    mingit = git.get("mingit", False)
    _require(isinstance(mingit, bool), "[git] mingit must be true or false")
    b.mingit = mingit

    return b


def _opt_str(value, where: str) -> str | None:
    if value is None:
        return None
    _require(isinstance(value, str) and value.strip(),
             f"{where} must be a non-empty string")
    return value.strip()


def _str_list(raw, where: str) -> list[str]:
    if isinstance(raw, str):        # a bare string is a one-element list
        raw = [raw]
    _require(isinstance(raw, list), f"{where} must be a string or a list")
    out: list[str] = []
    for item in raw:
        _require(isinstance(item, str) and item.strip(),
                 f"{where} must contain non-empty strings")
        if item.strip() not in out:
            out.append(item.strip())
    return out


def load(path: str | Path) -> Bundle:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as e:
        raise BundleError(f"could not read {path}: {e}") from e
    return parse(text, path=Path(path))


def find(root: Path) -> Path | None:
    candidate = Path(root) / LOCAL_NAME
    return candidate if candidate.is_file() else None


# ---------------------------------------------------------------------------
# Inventory -- what is (or will be) reachable
# ---------------------------------------------------------------------------

@dataclass
class Inventory:
    """What a bundle holds, in the terms a profile is written in.

    Built either from the declaration (intent, before the build) or from a
    bundle directory (reality, after it). One shape either way, so the
    validator below can't treat the two differently."""
    packages: dict[str, set[str]] = field(default_factory=dict)
    pythons: set[str] = field(default_factory=set)
    tools: set[str] = field(default_factory=set)
    vscode: bool = False
    mingit: bool = False
    source: str = "declaration"

    def has_package(self, spec: str) -> bool:
        return requirement_name(spec) in self.packages

    def has_version(self, spec: str) -> bool:
        pin = pinned_version(spec)
        if pin is None:
            return True
        return pin in self.packages.get(requirement_name(spec), set())

    @classmethod
    def from_bundle(cls, bundle: Bundle) -> Inventory:
        """What the declaration promises the share will hold.

        Nothing about any profile enters here: the superset a profile is
        judged against must not be assembled from that same profile, or it
        can never fail."""
        inv = cls(source="declaration")
        for spec in ALWAYS_PRESENT + bundle.packages:
            name = requirement_name(spec)
            inv.packages.setdefault(name, set())
            pin = pinned_version(spec)
            if pin:
                inv.packages[name].add(pin)
        inv.pythons = {v.strip() for v in bundle.pythons}
        inv.tools = {requirement_name(t.split("=")[0]) for t in bundle.tools}
        inv.vscode = bundle.vscode
        inv.mingit = bundle.mingit
        return inv

    @classmethod
    def discover(cls, root: Path) -> Inventory:
        """What a bundle on disk actually holds. Ground truth, and the only
        thing available on the air-gapped side -- where the question isn't
        "what did we mean to build" but "will this profile work here"."""
        root = Path(root)
        inv = cls(source=f"bundle at {root}")

        for whl in (root / "wheels").glob("*"):
            parsed = _dist_from_filename(whl.name)
            if parsed:
                name, version = parsed
                inv.packages.setdefault(name, set()).add(version)

        mirror = root / "python-builds"
        if mirror.is_dir():
            for archive in mirror.rglob("cpython-*.tar.*"):
                m = re.match(r"cpython-(\d+\.\d+)\.", archive.name)
                if m:
                    inv.pythons.add(m.group(1))

        for repodata in (root / "conda-channel").rglob("repodata.json"):
            try:
                data = json.loads(repodata.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for table in ("packages", "packages.conda"):
                for record in (data.get(table) or {}).values():
                    name = record.get("name")
                    if name:
                        inv.tools.add(canonical(name))

        vendor = root / "seedling" / "vendor"
        inv.vscode = (vendor / "vscode").is_dir()
        inv.mingit = (vendor / "git").is_dir()

        return inv


def _dist_from_filename(filename: str) -> tuple[str, str] | None:
    """('pandas-2.1.4-cp312-...whl') -> ('pandas', '2.1.4'). Source archives
    count too: `pip download` falls back to an sdist when no wheel exists, and
    the offline machine can still install one if it has a toolchain."""
    if filename.endswith(".whl"):
        parts = filename[: -len(".whl")].split("-")
        if len(parts) >= 2:
            return canonical(parts[0]), parts[1]
        return None
    for suffix in (".tar.gz", ".zip", ".tar.bz2"):
        if filename.endswith(suffix):
            stem = filename[: -len(suffix)]
            if "-" in stem:
                name, _, version = stem.rpartition("-")
                return canonical(name), version
            return None
    return None


# ---------------------------------------------------------------------------
# Validation -- one profile against one inventory
# ---------------------------------------------------------------------------

def check_profile(prof: profile_mod.Profile, inv: Inventory) -> list[str]:
    """Everything in `prof` that `inv` can't satisfy, as readable lines.

    Empty means the profile applies cleanly against this bundle. Reported all
    at once rather than failing on the first: an admin fixing a profile wants
    the whole list, especially when the round trip is a walk to an air-gapped
    room.

    One thing this cannot see: a profile's `[[repo]]` entries. They are cloned
    from the closed network's own git host, so their dependencies are only in
    the wheelhouse if someone listed them in `packages` -- nothing here can
    derive them."""
    problems: list[str] = []

    for version in prof.pythons:
        if inv.pythons and version.strip() not in inv.pythons:
            problems.append(
                f"Python {version}: not mirrored (bundle has: "
                f"{', '.join(sorted(inv.pythons)) or 'none'})")

    for spec in prof.package_set():
        if not inv.has_package(spec):
            problems.append(f"package {spec!r}: no distribution in the bundle")
        elif not inv.has_version(spec):
            have = ", ".join(sorted(inv.packages[requirement_name(spec)]))
            problems.append(
                f"package {spec!r}: that exact version isn't in the bundle "
                f"(it has: {have})")

    for tool in prof.tool_set():
        name = canonical(tool.split("=")[0])
        if name not in inv.tools:
            problems.append(
                f"conda-forge tool {tool!r}: not in the bundle's channel")

    for editor in prof.editors:
        if editor == "vscode" and not inv.vscode:
            problems.append(
                "editor \"vscode\": the bundle stages no editor "
                "([editor] stage = false, or --no-vscode)")
        if editor == "spyder" and "spyder" not in inv.packages:
            # Spyder is a PyPI application, so it has to be in the wheelhouse
            # like any other package -- naming it as an editor doesn't put it
            # there.
            problems.append(
                "editor \"spyder\": no spyder distribution in the bundle "
                "(add it to [packages] extra)")

    return problems


# ---------------------------------------------------------------------------
# Cross-checking the spec against global.conf
# ---------------------------------------------------------------------------

_CONF_LINE = re.compile(r'^\s*([A-Z_]+)\s*=\s*"([^"]*)"\s*$', re.M)


def read_conf(path: Path) -> dict[str, str]:
    """The KEY="value" pairs from a global.conf. Same shape the installers
    parse, deliberately: anything this reads differently from install.sh is a
    difference the admin would only discover on a user's machine."""
    try:
        return dict(_CONF_LINE.findall(Path(path).read_text(encoding="utf-8-sig")))
    except OSError:
        return {}


def check_conf(bundle: Bundle, conf: dict[str, str]) -> list[str]:
    """Where the spec and global.conf disagree about the editor.

    They describe the same deployment from two sides -- the spec says what
    gets STAGED into the bundle, the conf says what each user's machine is
    configured to USE -- so a disagreement always means one of them is wrong.
    Staging VSCodium while telling every user's settings to expect the
    Microsoft build is the expensive version of this mistake: it isn't
    visible until someone opens the editor on the far side of the air gap.
    """
    problems: list[str] = []

    flavor = (conf.get("SEEDLING_VSCODE_FLAVOR") or "").strip().lower()
    if flavor and flavor != bundle.editor_flavor:
        problems.append(
            f"editor flavor: the bundle stages {bundle.editor_flavor!r} but "
            f"global.conf sets SEEDLING_VSCODE_FLAVOR={flavor!r}")

    gallery = (conf.get("SEEDLING_EXTENSION_GALLERY") or "").strip()
    if gallery and (bundle.extension_gallery or "").strip() != gallery:
        problems.append(
            f"extension gallery: global.conf points users at {gallery}, which "
            f"the bundle's [editor] gallery doesn't match "
            f"({bundle.extension_gallery or 'unset'})")

    declared = (conf.get("SEEDLING_VSCODE_EXTENSIONS") or "").strip()
    if declared and declared.lower() != "none" and bundle.editor_extensions:
        wanted = {e.strip() for e in declared.split(",") if e.strip()}
        staged = set(bundle.editor_extensions)
        missing = sorted(wanted - staged)
        if missing:
            problems.append(
                "extensions: global.conf asks every machine to install "
                + ", ".join(missing)
                + ", which the bundle doesn't stage (offline, an extension "
                  "that wasn't staged can't be fetched)")
    return problems
