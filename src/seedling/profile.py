"""
Deployment profiles: one declarative file describing the environment an
organization wants its users to end up with.

`seedling.conf` answers "where does seedling get things from" and is read by
the shell installers. A profile answers "what should be set up once seedling
works" -- interpreters, venvs and their packages, repos to clone, settings --
and is read only here, by Python. That split is deliberate: install.sh and
install.ps1 stay dumb (they bootstrap seed-cli and then call `seed apply`),
so no structured format has to be parsed twice in two shell dialects.

TOML rather than JSON because this is a hand-edited admin file and TOML has
comments; `tomllib` is stdlib on the 3.12 floor seedling already requires, so
reading it costs no dependency.

Validation is strict and fails the whole profile rather than skipping bad
entries. A profile is distributed to a fleet: a typo that silently drops a
venv would be discovered by users, one at a time, long after the admin moved
on -- the same reasoning that makes an unknown vscode_flavor fatal.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import config

# Bumped only when an older seed-cli could MISREAD a newer profile. Additive
# keys don't need it; changed meanings do.
SCHEMA = 1

# Keys `seed apply` may write via [config]. Deliberately a subset of
# config.KNOWN_KEYS: the install-source and TLS settings belong to
# seedling.conf (they must be right *before* seed-cli runs), and letting a
# profile rewrite them would give two sources of truth for the same value.
SETTABLE_KEYS = {
    "default_base",
    "default_venv",
    "venv_default_packages",
    "vscode_flavor",
    "extension_gallery",
    "vscode_extensions",
}


class ProfileError(ValueError):
    """A profile that cannot be applied as written."""


@dataclass
class Venv:
    name: str
    python: str | None = None
    packages: list[str] = field(default_factory=list)
    default: bool = False
    # None means "inherit venv_default_packages", matching `seed venv`.
    # False is an explicit "this venv gets only what it lists".
    default_packages: bool | None = None


@dataclass
class Repo:
    url: str
    # The venvs this repo is installed into, in declared order. Empty means
    # clone only -- there is no separate "install?" flag, because `install`
    # names its targets outright and an empty list of targets IS "don't".
    venvs: list[str] = field(default_factory=list)


@dataclass
class Profile:
    path: Path | None = None
    pythons: list[str] = field(default_factory=list)
    venvs: list[Venv] = field(default_factory=list)
    repos: list[Repo] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    # Which bundled editor this deployment standardizes on ("vscode",
    # "spyder"). None means the profile doesn't say, and `seed apply`
    # Which bundled editors this deployment standardizes on. Empty means the
    # profile doesn't say, and `seed apply` installs none -- the install-time
    # SEEDLING_AUTO_VSCODE setting keeps deciding that, so a profile written
    # before this existed behaves exactly as before.
    #
    # Plural because the underlying system genuinely supports several at once:
    # the editors live in separate trees with separate commands, and nothing
    # about `seed vscode` and `seed spyder` conflicts. A mixed team -- engineers
    # on VS Code, analysts on Spyder -- is the case this exists for.
    editors: list[str] = field(default_factory=list)
    settings: dict = field(default_factory=dict)

    def tool_set(self) -> list[str]:
        """The conda-forge tools this profile declares, de-duplicated. Used by
        the offline bundler to build the bundled conda channel, and by
        `seed apply` to install them -- one source of truth, like packages."""
        return list(dict.fromkeys(self.tools))

    def package_set(self) -> list[str]:
        """Every package any venv in this profile needs, de-duplicated and
        sorted. Used by the offline bundler so the wheel set is derived from
        the profile instead of being maintained by hand alongside it."""
        seen: set[str] = set()
        for venv in self.venvs:
            seen.update(venv.packages)
        inherited = self.settings.get("venv_default_packages")
        if inherited is None:
            inherited = config.default_of("venv_default_packages") or []
        if any(v.default_packages is not False for v in self.venvs):
            seen.update(inherited)
        return sorted(seen)


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ProfileError(msg)


def _str_list(raw, where: str) -> list[str]:
    _require(isinstance(raw, list), f"{where} must be a list")
    out = []
    for item in raw:
        _require(isinstance(item, str) and item.strip(),
                 f"{where} must contain non-empty strings")
        out.append(item.strip())
    return out


def _repo_venvs(value, url: str) -> list[str]:
    """Read a `[[repo]] install` value into the venvs to install into.

        install = "analysis"      -- that venv
        install = ["dev", "ml"]   -- each of them, in that order
        (key omitted)             -- clone only

    `install` is a list of venvs and nothing else. Neither bool is accepted,
    though both once were:

    `true` meant "the profile's default venv", which left where a fleet's
    repo landed to a setting written elsewhere in the file -- change the
    default venv and the repo silently moves with it. Naming the venv is
    barely longer to write and says what will actually happen.

    `false` was a second way to spell what an absent key already says. Two
    spellings of "no" invite the question of whether they differ, and a key
    whose value can be a venv name or a boolean is a key that has to be read
    twice. Omitting it is the one way. String-or-list mirrors `editor`.
    """
    if value is None:                        # the key isn't there at all
        return []
    _require(value is not True,
             f"repo {url!r}: install = true no longer says where to install "
             f"-- name the venv instead: install = \"dev\", or "
             f"install = [\"dev\", \"analysis\"] for several")
    _require(value is not False,
             f"repo {url!r}: install = false is no longer accepted -- leave "
             f"the install key out to clone without installing")
    if isinstance(value, str):
        value = [value]
    _require(isinstance(value, list),
             f"repo {url!r}: install must be a venv name or a list of venv "
             f"names")
    _require(bool(value),
             f"repo {url!r}: install = [] names no venv -- leave the install "
             f"key out to clone without installing")
    targets: list[str] = []
    for item in value:
        _require(isinstance(item, str) and item.strip(),
                 f"repo {url!r}: every venv named by install must be a "
                 f"non-empty string")
        name = item.strip()
        if name not in targets:
            targets.append(name)
    return targets


def parse(text: str, *, path: Path | None = None) -> Profile:
    """Parse and validate profile TOML. Raises ProfileError with a message
    naming the offending key -- an admin fixing a fleet-wide file needs to
    know which line is wrong, not that "the profile is invalid"."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ProfileError(f"not valid TOML: {e}") from e

    schema = raw.get("schema", SCHEMA)
    _require(isinstance(schema, int), "schema must be an integer")
    _require(schema <= SCHEMA,
             f"profile declares schema {schema}, but this seedling "
             f"understands up to {SCHEMA}. Update seedling first "
             f"(`seed update-commands`).")

    profile = Profile(path=path)
    profile.pythons = _str_list(raw.get("python", []), "python")

    venvs = raw.get("venv", [])
    _require(isinstance(venvs, list), "[[venv]] must be a list of tables")
    names: set[str] = set()
    for entry in venvs:
        _require(isinstance(entry, dict), "each [[venv]] must be a table")
        name = entry.get("name")
        _require(isinstance(name, str) and name.strip(),
                 "every [[venv]] needs a non-empty name")
        name = name.strip()
        _require(name not in names, f"duplicate venv name {name!r}")
        names.add(name)
        python = entry.get("python")
        _require(python is None or (isinstance(python, str) and python.strip()),
                 f"venv {name!r}: python must be a base tag like \"312\"")
        default_packages = entry.get("default_packages")
        _require(default_packages is None or isinstance(default_packages, bool),
                 f"venv {name!r}: default_packages must be true or false")
        default = entry.get("default", False)
        _require(isinstance(default, bool),
                 f"venv {name!r}: default must be true or false")
        profile.venvs.append(Venv(
            name=name,
            python=python.strip() if isinstance(python, str) else None,
            packages=_str_list(entry.get("packages", []),
                               f"venv {name!r}: packages"),
            default=default,
            default_packages=default_packages,
        ))

    defaults = [v.name for v in profile.venvs if v.default]
    _require(len(defaults) <= 1,
             f"only one venv may be default, but {len(defaults)} are: "
             f"{', '.join(defaults)}")

    repos = raw.get("repo", [])
    _require(isinstance(repos, list), "[[repo]] must be a list of tables")
    for entry in repos:
        _require(isinstance(entry, dict), "each [[repo]] must be a table")
        url = entry.get("url")
        _require(isinstance(url, str) and url.strip(),
                 "every [[repo]] needs a non-empty url")
        url = url.strip()
        targets = _repo_venvs(entry.get("install"), url)
        # A named venv must be one the profile declares. Otherwise the repo
        # lands nowhere on every machine in the fleet, and the admin hears
        # about it one user at a time -- the same reasoning as `default_venv`.
        for target in targets:
            _require(target in names,
                     f"repo {url!r}: install names venv {target!r}, which "
                     f"this profile doesn't declare")
        profile.repos.append(Repo(url=url, venvs=targets))

    profile.tools = _str_list(raw.get("tools", []), "tools")

    # `editor = "spyder"` -- the bundled editor this deployment standardizes
    # on. Validated against the editor registry rather than a list written
    # out here, so registering an editor makes it profile-selectable without
    # a second place to update. Unknown values are fatal for the same reason
    # an unknown vscode_flavor is: a typo would otherwise silently deploy a
    # different editor than the one the fleet was told it would get.
    # `editor = "spyder"` or `editor = ["vscode", "spyder"]`. Both shapes are
    # accepted and normalized to a list -- the same tolerance `extensions_for`
    # already applies to vscode_extensions, and it keeps profiles written
    # against the single-value form working unchanged.
    #
    # Validated against the editor registry rather than a list spelled out
    # here, so registering an editor makes it profile-selectable with no
    # second place to update. Unknown values are fatal for the same reason an
    # unknown vscode_flavor is: a typo would otherwise silently deploy a
    # different editor than the fleet was told it would get.
    declared = raw.get("editor")
    if declared is not None:
        from .commands import editors as _editors_registry
        # ensure_registered(), not REGISTRY directly: a profile can be loaded
        # by something that never imports the editor modules (the offline
        # bundler does exactly that), and an empty registry would reject
        # every valid editor.
        known = sorted(_editors_registry.ensure_registered())
        if isinstance(declared, str):
            declared = [declared]
        _require(isinstance(declared, list),
                 "editor must be a string or a list of strings")
        _require(bool(declared), "editor must name at least one editor")
        seen: list[str] = []
        for entry in declared:
            _require(isinstance(entry, str) and entry.strip(),
                     "every editor must be a non-empty string")
            name = entry.strip().lower()
            _require(name in known,
                     f"editor = {name!r} is not a bundled editor. "
                     f"Valid values: {', '.join(known)}.")
            if name not in seen:
                seen.append(name)
        profile.editors = seen

    settings = raw.get("config", {})
    _require(isinstance(settings, dict), "[config] must be a table")
    for key, value in settings.items():
        _require(key in SETTABLE_KEYS,
                 f"[config] {key!r} cannot be set from a profile. "
                 f"Settable here: {', '.join(sorted(SETTABLE_KEYS))}. "
                 f"Install-time settings belong in seedling.conf.")
        profile.settings[key] = value

    # A default venv must exist in the profile, or the setting points at
    # nothing and new shells fail to activate on every machine in the fleet.
    declared = profile.settings.get("default_venv")
    if declared is not None:
        _require(any(v.name == declared for v in profile.venvs),
                 f"[config] default_venv = {declared!r} names no venv in "
                 f"this profile")
    return profile


def load(path: Path) -> Profile:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as e:
        raise ProfileError(f"could not read {path}: {e}") from e
    return parse(text, path=Path(path))


def find(explicit: str | None = None) -> Path | None:
    """Resolve which profile to apply: an explicit path, else the one
    recorded at install time, else a conventional file in the current
    directory. Returns None when there is nothing to apply."""
    if explicit:
        return Path(explicit).expanduser()
    recorded = config.get("profile")
    if recorded:
        candidate = Path(str(recorded)).expanduser()
        if candidate.is_file():
            return candidate
    local = Path.cwd() / "seedling-profile.toml"
    return local if local.is_file() else None
