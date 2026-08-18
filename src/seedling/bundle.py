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
class BundleRepo:
    """A repo the bundle carries, and every extra any profile may select from
    it. Declared here (not derived) because resolving a repo's optional
    dependencies means cloning it, which only the connected machine can do."""
    url: str
    extras: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        # Deliberately the same derivation `seed repo-clone` uses, so the name
        # a profile refers to and the name this declares can't diverge.
        from .commands import repo_cmd
        return repo_cmd._derive_name(self.url)


@dataclass
class Bundle:
    path: Path | None = None
    platform: str | None = None
    deploy_root: str | None = None
    pythons: list[str] = field(default_factory=list)
    # THE package set, not an addition to one: every distribution any profile
    # may name, plus whatever users should be able to `seed install` later.
    packages: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    repos: list[BundleRepo] = field(default_factory=list)
    editor_flavor: str = "microsoft"
    editor_extensions: list[str] = field(default_factory=list)
    extension_gallery: str | None = None
    vscode: bool = True
    mingit: bool = False


def parse(text: str, path: Path | None = None) -> Bundle:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise BundleError(f"invalid TOML: {e}") from e

    schema = raw.get("schema", SCHEMA)
    _require(isinstance(schema, int) and schema <= SCHEMA,
             f"schema {schema!r} is newer than this seedling understands "
             f"(supported: {SCHEMA}). Update seedling first.")

    known = {"schema", "platform", "deploy_root", "pythons", "packages",
             "tools", "editor", "git", "repo"}
    unknown = sorted(set(raw) - known)
    _require(not unknown,
             f"unknown key(s): {', '.join(unknown)}. Known keys: "
             f"{', '.join(sorted(known))}")

    b = Bundle(path=path)
    b.platform = _opt_str(raw.get("platform"), "platform")
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

    git = raw.get("git", {})
    _require(isinstance(git, dict), "[git] must be a table")
    unknown = sorted(set(git) - {"mingit"})
    _require(not unknown, f"[git]: unknown key(s): {', '.join(unknown)}")
    mingit = git.get("mingit", False)
    _require(isinstance(mingit, bool), "[git] mingit must be true or false")
    b.mingit = mingit

    repos = raw.get("repo", [])
    _require(isinstance(repos, list), "[[repo]] must be a list of tables")
    for entry in repos:
        _require(isinstance(entry, dict), "each [[repo]] must be a table")
        unknown = sorted(set(entry) - {"url", "extras"})
        _require(not unknown, f"[[repo]]: unknown key(s): {', '.join(unknown)}")
        url = entry.get("url")
        _require(isinstance(url, str) and url.strip(),
                 "every [[repo]] needs a non-empty url")
        b.repos.append(BundleRepo(
            url=url.strip(),
            extras=_str_list(entry.get("extras", []),
                             f"repo {url!r}: extras")))
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
    repos: dict[str, set[str]] = field(default_factory=dict)   # name -> extras
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
        for repo in bundle.repos:
            inv.repos[repo.name] = set(repo.extras)
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

        # A bundle carries its own declaration, which is where repo extras
        # live: nothing on disk records which extras a wheelhouse was
        # resolved for.
        declared = find(root / "seedling")
        if declared:
            try:
                for repo in load(declared).repos:
                    inv.repos[repo.name] = set(repo.extras)
            except BundleError:
                pass
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
    room."""
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

    for repo in prof.repos:
        from .commands import repo_cmd
        name = repo_cmd._derive_name(repo.url)
        if name not in inv.repos:
            problems.append(
                f"repo {name!r}: not declared in the bundle, so its "
                f"dependencies aren't in the wheelhouse")
            continue
        wanted = {e for t in repo.targets for e in t.extras}
        missing = sorted(wanted - inv.repos[name])
        if missing:
            problems.append(
                f"repo {name!r}: extras {', '.join(missing)} aren't declared "
                f"in the bundle, so their dependencies aren't in the "
                f"wheelhouse")

    return problems
