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

## [0.6.0] — 2026-07-19

### Added

- **`seed summary --json`** — the same facts `seed summary` shows, as
  machine-readable data instead of a rendered screen, for scripts, CI, and
  coding assistants that otherwise have to guess where things live. Every
  venv reports a `python_executable`: the absolute, platform-resolved path
  to its own interpreter. The object carries a `schema` number (currently
  `1`) so readers can tell when a field changes meaning. Size fields stay
  `null` unless `--sizes` is passed, since walking the tree is the slow
  part. Text output is unchanged.

## [0.5.0] — 2026-07-19

### Changed

- **Remove commands no longer force-close your processes up front.** Every
  removal (`remove-venv`, `remove-venv-all`, `remove-python`, `remove-repo`,
  `remove-user`, `purge`) now escalates only as far as it must: delete; if
  something is locked, name the process holding it and close *only* that;
  fall back to force-closing all Python/VS Code processes only if that wasn't
  enough. Previously the last step ran unconditionally and first, so removing
  a throwaway venv would close an unrelated editor window — with unsaved work
  in it — before establishing that anything was wrong. In the common case
  nothing is closed at all.

  Blockers are identified with the Windows **Restart Manager**, the API
  installers use to report which applications are using a file. That's
  authoritative rather than a guess, and it fixes matching in both directions:
  an unrelated system Python is left alone, while a process named nothing like
  Python — a PyQt/PySide app's `QtWebEngineProcess.exe`, or a bundled
  `node`/`ffmpeg` — is caught, because it lives inside the tree being deleted.
  A working-directory blocker, which the Restart Manager cannot see, falls back
  to a scoped search. Reached through stdlib `ctypes`, so no new dependency.

  None of this runs on macOS or Linux, where deleting a file with open handles
  succeeds anyway — those platforms were being made to force-close user
  processes for no benefit at all.

- **`seed kill-processes` is now scoped by default too.** With no arguments it
  closes only seedling's own processes; `--system` is the machine-wide sweep,
  and a bare process name still targets that name. "Something of mine is stuck"
  shouldn't close a colleague's editor or an unrelated long-running job.

  `seed kill-processes all` was the previous spelling of the machine-wide
  sweep and **still means machine-wide**, with a note pointing at `--system`.
  It is deliberately not re-pointed at the new narrow mode, since that would
  silently change what an existing script does.

## [0.4.0] — 2026-07-19

### Added

- **Destructive commands now warn when a cloned repo holds work that exists
  nowhere else.** `seed purge`, `seed remove-repo` and `seed remove-user`
  check each repo for uncommitted changes, untracked files and unpushed
  commits, and name the repos at risk *before* the confirmation prompt — and
  before the process kill that closes VS Code. Previously `purge` said only
  "you have some cloned repos", which can't distinguish a throwaway clone from
  three days of unsaved work.

  It reports rather than blocks: passing `-y` still proceeds (scripted
  teardowns keep working), but the warning is printed, so it lands in the
  terminal and the run log. `--preview` shows it too. `--keep-repos` and
  `seed purge-and-reinstall` don't warn, because they move repos to safety
  instead of deleting them. Unsaved editor buffers can't be detected, and a
  branch with no remote can't be checked for unpushed commits; the warning
  says so rather than implying deletion is now safe.

- **The offline bundle builder now proves the bundle installs, before it
  leaves the build machine.** Every step previously reported only whether a
  download *succeeded*, which is a different question from whether the result
  would install air-gapped — and the difference normally surfaced in the
  air-gapped room, after sign-off. A new preflight step installs each mirrored
  interpreter from the bundle, creates a venv on each and installs the default
  packages from the bundled wheels, then builds `seed-cli` from the bundled
  source. It runs with the network refused and a **cold uv cache**, so a wheel
  the bundle is missing can't be satisfied from the build's own warm cache.
- `build-offline.cmd --verify-only -o <bundle>` runs that check against an
  existing bundle without building anything, and exits 0/non-zero so it can
  gate a deployment pipeline. Run it on the copy that reached your share to
  prove the transfer was complete. `--no-verify` skips the check during a
  build; an unverified bundle now says so in the summary rather than reading
  as confirmed.

## [0.3.2] — 2026-07-18

### Fixed

- **The offline bundle stocked wheels for only one interpreter.** When
  `build-offline.cmd` mirrored several Python versions, the wheel step resolved
  the package set for the first one only, so creating a venv on any other
  mirrored interpreter failed offline — the headline packages are
  version-agnostic, but their compiled dependencies (`pyzmq`, `tornado`,
  `debugpy`, `psutil`, and anything from `--packages`) are not. It now resolves
  once per mirrored interpreter into the same flat wheel folder, and reports
  which interpreter failed rather than counting a partial result as success.
  This combination was made more likely by 0.3.0, whose new floor check
  actively suggests `--python 3.12,3.9`.
- **Re-running the bundle builder silently shipped stale source.** An existing
  `offline-bundle/seedling/` was reused verbatim, so editing the repo and
  rebuilding produced a bundle that looked freshly built — `seedling.conf` was
  rewritten on top — around the *first* build's code. The repo copy is now
  refreshed every run; the expensive `vendor/` payloads are preserved, so
  rebuilds stay cheap.

## [0.3.1] — 2026-07-18

### Fixed

- `build-offline.cmd` now actually enforces its Python 3.12+ requirement on
  Windows. The requirement was only probed by the POSIX launcher; the Windows
  batch path ran `py -3` with no version check, so an older interpreter got an
  obscure failure instead of the documented message. The check now lives in
  `build_offline.py` itself, so it covers both launchers and direct
  `python installers/build_offline.py` invocation, and it makes clear that this
  is the interpreter that *builds* the bundle — unrelated to the Python
  versions the bundle ships for your users.

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
