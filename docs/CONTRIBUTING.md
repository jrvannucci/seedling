---
orphan: true
---

# Contributing to seedling

This guide is for people working on seedling **itself** — changing the `seed`
commands, the installers, or the shell integration. For using seedling, see
[Using seedling](GUIDE.md) and the [command reference](COMMANDS.md); for
deploying it to other people, see the [deployment guide](DEPLOYMENT.md) and
[OFFLINE.md](OFFLINE.md).

---

## The edit → update loop

seedling installs from a private copy of its source at `~/seedling/system/src`
and never touches that copy except through `seed update-commands` (see
[The update model](GUIDE.md#the-update-model)). That would normally make
iterating awkward — but installing from a **local checkout** wires the loop up
for you.

When you run the installer from inside a checkout of this repo, seedling records
that checkout directory as the `update_source` setting. `seed update-commands`
then re-copies from your working tree, so the loop is:

1. Install once from your checkout:
   - **macOS/Linux:** `sh ./install.cmd`
   - **Windows:** `install.cmd`
2. Edit the source in your checkout (or `git pull`).
3. Run `seed update-commands`. Your changes are copied into the install and
   `seed-cli` is reinstalled from them — no re-running the installer.
4. Open a new terminal (or re-source the printed `seed.sh`/`seed.ps1`) to pick
   up any change to the `seed` shell function itself.

`seed update-commands` re-copies the whole tree **minus `.git` and `vendor/`**,
and overwrites `~/seedling/system/src` wholesale — so edit in your checkout, not
in the installed copy (edits there don't survive an update).

> An explicit `SEEDLING_REPO` (env, one run) or `SEEDLING_REPO_URL`
> (`seedling.conf`) still wins over the checkout directory if you'd rather
> updates come from a URL — see below.

---

## Tracking a branch: `--from-branch`

When `update_source` is a **git URL** (your fork, or a self-hosted host), update
from a specific branch or tag instead of the remote's default branch:

```
seed update-commands --from-branch dev
```

This adds `--branch <name>` to the shallow clone, so it works for either a
branch or a tag — handy for tracking a `dev`/`staging` line or pinning a release.
It only applies to git-URL sources; with a directory/share `update_source` (or
none) it's ignored with a note, since a directory has no branches.

To point an install at a fork's URL in the first place, set it at install time
(`SEEDLING_REPO=https://github.com/you/seedling.git`) or afterward with
`seed config set update_source <git-url>`.

---

## Source layout

```
README.md
seedling.conf         deployment config: install/update source URL (or directory) + install-time settings
install.cmd           generic installer entry point: batch on Windows, `sh ./install.cmd` on macOS/Linux
uninstall.cmd         generic uninstaller entry point (same dual-platform trick)
build-offline.cmd     builds an offline distribution bundle (dual-platform launcher; NOT a seed command)
installers/
  install.sh          the real POSIX installer (also what the curl one-liner runs)
  install.ps1         the real Windows installer (also what the irm one-liner runs)
  uninstall.sh / uninstall.ps1   full removal, including the shell hook (same end state as `seed purge`)
  build_offline.py    the offline bundle builder (downloads uv + interpreters + wheels, writes seedling.conf)
  build_offline.sh    POSIX launcher for build-offline.cmd (finds Python, runs build_offline.py)
docs/
  DOCUMENTATION.md    the documentation map (routes to the two tracks below)
  GUIDE.md            using seedling: install, layout, updates, troubleshooting
  COMMANDS.md         every command and flag
  DESIGN.md           why deletion is defensive, logging, download verification
  DEPLOYMENT.md       deploying to others: seedling.conf, shared roots, admin teardown
  OFFLINE.md          fully-offline / air-gapped deployment guide
  LICENSING.md        redistribution posture; what is downloaded, under what terms
  CONTRIBUTING.md     this guide
tests/
  conftest.py         sandbox fixtures (throwaway home, stub uv, env isolation)
  test_*.py           unit + CLI + offline/installer/shell-template integration tests
src/
  pyproject.toml      the python package definition (`uv tool install` targets this folder)
  seedling/
    cli.py            argparse dispatcher
    paths.py          single source of truth for the ~/seedling folder layout
    config.py         JSON config (default base, default venv, update source, etc.) + `seed config`'s KNOWN_KEYS
    confirm.py        shared -y / --preview / --non-interactive handling for destructive commands
    runlog.py         tees stdout/stderr into ~/seedling/system/logs/, one file per day
    download.py       SHA-256-verifying download helper (MinGit, VS Code)
    uv_tool.py        locates + invokes the sandboxed uv binary, tags its output `[uv]`
    git_tool.py       locates git, bootstraps portable MinGit on Windows, tags streamed output `[git]`
    fsutil.py         retrying, cwd-aware directory deletion (see "Why deletion is so defensive")
    colors.py         minimal ANSI color helper (NO_COLOR/non-tty aware)
    commands/         one module per `seed` command (python, venv, activate, repo,
                      vscode, kill, update, summary, health-check, config, remove, purge, ...)
    shell/
      seed.sh.template   copied to ~/seedling/system/shell/seed.sh at install time
      seed.ps1.template  copied to ~/seedling/system/shell/seed.ps1 at install time
```

---

## Running the tests

`uvx pytest` from the repo root runs the whole suite — uv supplies pytest, and
`tests/conftest.py` puts `src/` on the import path, so nothing needs installing
first. Design guarantees the suite enforces:

- **Never touches your real `~/seedling`** — every test rebinds seedling's
  paths to a throwaway directory, and the machine-wide process killer is
  disabled for the whole run.
- **Fully offline** — installer runs use a stub `uv` that logs its
  invocations; the offline-index tests hand-craft a local wheel and prove
  both directions (a package in the wheels folder installs; one that
  isn't fails fast with the internet index disabled); downloads are
  exercised over `file://` URLs.
- Real `git`, `bash`, and `powershell` are used where present (git file
  protocol, installer end-to-end, shell-function behavior) and those
  tests skip cleanly on machines without them.

`uvx ruff check .` must also pass — it runs in CI, config is in `ruff.toml` at
the repo root (deliberately there, not in `src/pyproject.toml`, so it covers
`tests/` and `installers/` too).

---

## Releasing

The version lives in **one** place: `__version__` in
`src/seedling/__init__.py`. `src/pyproject.toml` reads it from there
(`dynamic = ["version"]`), so the built distribution, `seed --version`, and the
`seed help` footer can never disagree. A test enforces that pyproject stays
dynamic — don't add a literal `version =` back.

Keep [`CHANGELOG.md`](https://github.com/cryocliff/seedling/blob/main/CHANGELOG.md)
current as you go: add a line under
`## [Unreleased]` in the same commit as the change, while you still remember
why it mattered. Write for someone deploying seedling, not for someone reading
the diff.

To cut a release:

1. Bump `__version__` in `src/seedling/__init__.py`.
2. Rename `## [Unreleased]` to the new version with today's date, and open a
   fresh empty `## [Unreleased]` above it.
3. Commit, then tag: `git tag -a v0.2.0 -m "v0.2.0"`.

This matters more than it looks. `seed update-commands` pulls from a share or a
git URL, so an install can sit at a different version than the source it was
built from — the changelog is how a user finds out what an update changed.

---

## License

seedling is [Apache-2.0](https://github.com/cryocliff/seedling/blob/main/LICENSE).
Contributions are accepted under the same license (inbound = outbound, per
Apache-2.0 section 5) — by opening a pull request you agree your contribution
is licensed under Apache-2.0. Please don't add third-party runtime
dependencies: seedling deliberately ships on the standard library alone, which
is what keeps its licensing and its "nothing pre-installed" promise simple
(see [THIRD-PARTY-NOTICES](https://github.com/cryocliff/seedling/blob/main/THIRD-PARTY-NOTICES.md)).
