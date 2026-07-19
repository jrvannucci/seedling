# Changelog

All notable changes to seedling are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) — while seedling is
pre-1.0, a minor bump may carry a breaking command rename.

The version lives in `src/seedling/__init__.py` and nowhere else; `seed
--version` prints it. See [CONTRIBUTING](docs/CONTRIBUTING.md#releasing) for
what a release involves.

## [Unreleased]

Nothing yet.

## [0.3.0] — 2026-07-18

### Removed

- **Breaking: dropped support for Python 3.9, 3.10, and 3.11.** seedling now
  requires **Python 3.12 or newer**. `uv` refuses the install outright on an
  older interpreter, with a clear resolver error, rather than failing
  halfway. This is about the interpreter `seed-cli` itself runs on — seedling
  can still install and manage any Python version for you, so `seed python 3.9`
  and 3.9 venvs are unaffected.
- `build-offline.cmd` now also needs Python 3.12+ on the machine you build the
  bundle on (it imports seedling's own modules).

### Added

- `build-offline.cmd` now validates `--python` against seedling's own
  `requires-python` **before downloading anything**, and refuses to build a
  bundle where no mirrored interpreter could run `seed-cli`. That combination
  previously built cleanly and only failed after the bundle reached the
  air-gapped machine. Mirroring older interpreters alongside a supported one is
  still fine — they're what your users' venvs are built from.

### Changed

- CI now tests **every supported Python from the floor upward** — 3.12, 3.13,
  and 3.14 — on both Windows and Linux, instead of only the ends of the range.
- Tar extraction dropped its compatibility branch for interpreters predating
  the `filter=` backport; it now always passes `filter="data"`.

## [0.2.0] — 2026-07-18

The version string sat at `0.1.0` through all of early development, so this
first tracked release aggregates the work built up to that point. Entries are
reconstructed from git history; releases from here on are recorded as they
land.

### Added

- **Offline / air-gapped deployment.** Everything is driven by editing
  `seedling.conf` in the repo copy you distribute, plus `vendor/` payloads for
  the uv binary, portable MinGit, VS Code, and corporate CA certificates. See
  [docs/OFFLINE.md](docs/OFFLINE.md).
- **`build-offline.cmd`** — a guided builder that assembles a complete
  air-gapped bundle (uv, Python interpreter mirror, wheel index, VS Code +
  extensions) on a connected machine. `--yes` builds it unattended; `--dry-run`
  shows the plan; `--no-vscode` and `--mingit` control the optional steps.
- **`seed download-whl` / `seed download-requirements`** — build a flat
  wheelhouse to carry to an air-gapped machine.
- **Multi-user shared-root installs** and the `admin-*` command family for
  managing them.
- **Command logging and `seed logs-viewer`** — a master-detail HTML view of
  past runs, including installer output, with date-range filtering.
- **`seed health-check`** — one-shot check of the whole install.
- **`seed venv-default`**, **`seed repo-cd`**, and automatic VS Code setup with
  a default extension and settings kit.
- **`seed -V` / `seed --version`.**
- **CI** across Windows and Linux on Python 3.9, 3.12, and 3.13, plus a ruff
  lint job.

### Changed

- **Breaking: commands were renamed into consistent families** (`remove-*`,
  `admin-*`, `python-*`, `venv-*`, `repo-*`). Older single-word names are gone.
- seedling no longer requires `pip`, and keeps uv's cache inside its own folder
  rather than the user's home.
- Installer parallelizes the VS Code download behind a live status bar.
- Logs are plain text end to end, so they can be shipped to a log server as-is.
- Tar extraction is pinned to the `data` filter, so behavior no longer depends
  on the running interpreter (Python 3.14 changes the default; 3.12/3.13 warn).
- The version has a single source of truth, `src/seedling/__init__.py`;
  `pyproject.toml` derives from it.
- Documentation moved to a Sphinx site.

### Fixed

- `seed update-commands` could brick the install on Windows, where uv had to
  delete the tool venv whose `python.exe` was the running `seed-cli`; the live
  copies are now renamed aside first, with rollback on failure.
- `seed update-commands` now refreshes the generated shell integration, so an
  update reaches `seed.ps1` / `seed.sh` too.
- `seed purge` handles every install method, and no longer half-fails on
  read-only `.git` objects or on deleting its own running executable.
- Auto-deactivate when a venv disappears.
- CRLF handling so the polyglot `.cmd` entry points work under bash.
- The offline bundle builder no longer reports success when the VS Code step
  failed, and no longer strands a ~300MB staging tree inside the bundle if it
  is interrupted.
- MinGit can now be included in an unattended (`--yes`) bundle build, via
  `--mingit`.

## [0.1.0]

Initial development. Never tagged or released as a distinct version — the
string stayed at `0.1.0` while the work above was built. See the git history
for detail.
