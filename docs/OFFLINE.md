# Running seedling on an offline network

seedling was designed so that an organization on an isolated network — no
github.com, no pypi.org, no internet at all — can still install it, use it,
and keep it updated. This page lists **every component that normally comes
from the internet**, when it's needed, and what to provide instead.

The audience here is whoever prepares the deployment (a shared drive or a
self-hosted git server). End users on the offline network never deal with
any of this — they run `install.cmd` from the share and everything works.

---

## The short version

> **In a hurry?** For the common share-only case, skip the manual steps: run
> **`build-offline.cmd`** (`sh ./build-offline.cmd` on macOS/Linux) on a
> connected machine. It downloads uv, the Python interpreter archives, all the
> wheels, and (optionally) VS Code + its extensions, then writes a matching
> `seedling.conf` — see
> [Putting it together](#putting-it-together-preparing-the-share). The rest of
> this page explains what it's doing and covers the cases it leaves to you
> (self-hosted indexes, corporate CAs).

Everything is driven by **editing [`seedling.conf`](../seedling.conf)** in the
copy of the repo you distribute (plus dropping a few binaries in `vendor/`) —
your users never set environment variables or change anything on their
machines. Find the scenario that matches your network and set only what it
lists:

**You have a self-hosted git server and internal mirrors** — GitHub
Enterprise / GitLab, plus Artifactory / Nexus / devpi:

| Set | To |
|---|---|
| `SEEDLING_REPO_URL` | your seedling repo's git URL |
| `SEEDLING_PYTHON_MIRROR` | your `python-build-standalone` mirror |
| `SEEDLING_PACKAGE_INDEX` | your internal package index (must also serve `hatchling`, used to build seed-cli) |
| `vendor/uv/` | the `uv` binary (it won't be on your package index) |

**You have only a shared network drive** — no git server, no internal index,
just a file share everyone can read:

| Set | To |
|---|---|
| `SEEDLING_REPO_URL` | a **folder** on the share holding a copy of this repo |
| `SEEDLING_PYTHON_MIRROR` | a **folder** of `python-build-standalone` archives |
| `SEEDLING_PACKAGE_INDEX` | a **folder** of wheels (must include `hatchling`) |
| `vendor/uv/` | the `uv` binary |
| `vendor/git/` | MinGit — Windows only, if there's no system git |

Full walkthrough: [Variant: nothing but a shared drive](#variant-nothing-but-a-shared-drive).

**You have internet, but pip/interpreter downloads are blocked or must stay
internal** — only the package (and maybe Python) sources are restricted:

| Set | To |
|---|---|
| `SEEDLING_REPO_URL` | leave unset — installs from public GitHub |
| `SEEDLING_PACKAGE_INDEX` | your internal index or wheels folder |
| `SEEDLING_PYTHON_MIRROR` | only if interpreter downloads are blocked too |

**Your network re-signs HTTPS with a corporate CA** — a TLS-inspecting proxy
(can combine with any scenario above):

| Set | To |
|---|---|
| `SEEDLING_NATIVE_TLS=true` | trust the OS certificate store — **or** — |
| `vendor/certs/` | your CA's `.pem`/`.crt` files (bundled and trusted automatically) |

Details: [HTTPS and corporate certificate authorities](#https-and-corporate-certificate-authorities).

**Optional in any scenario** — via the [`vendor/` convention](#the-vendor-convention):

| Set | To |
|---|---|
| `vendor/vscode/` | a pre-seeded portable VS Code (ships the editor offline) |
| `vendor/git/` | MinGit — git on Windows with no system install |

The conf values are recorded in seedling's settings at install time and applied
automatically to every command afterward (view or change them later with `seed
config`). Everything that *isn't* a download — venvs, activation, config,
logging, previews, removal, directory-based updates — already works with zero
network access. The [component-by-component reference](#what-seedling-downloads-and-when)
below backs each scenario, and [Putting it together](#putting-it-together-preparing-the-share)
is a start-to-finish walkthrough.

---

## The `vendor/` convention

Binaries that can't come from a URL/directory setting are handled by a
single convention: a **`vendor/` folder inside the copy of the repo you
distribute**. The installer copies whatever it finds there into place
*before* any download step runs (each of which skips itself when its
target already exists) — presence equals intent, no wrapper scripts, no
configuration:

Every payload is a folder whose contents go to the destination:

```
vendor/uv/         (uv.exe or uv, uvx too if present) -> ~/seedling/system/bin/
vendor/git/        (an extracted MinGit)              -> ~/seedling/extensions/git/
vendor/vscode/     (a pre-seeded portable VS Code)    -> ~/seedling/extensions/vscode/
vendor/certs/      (corporate CA .pem/.crt files)     -> bundled into
                    ~/seedling/system/certs/ca-bundle.pem and trusted everywhere
```

Reinstalls never overwrite binaries already in place, `vendor/` is
excluded from seedling's private source copy and from updates (a
pre-seeded VS Code would otherwise bloat `system/src` by hundreds of MB),
and the folder is gitignored — it exists only on distribution media.

---

## What seedling downloads, and when

| Download | From | When it happens |
|---|---|---|
| seedling source | github.com (default) | Install; `seed update-commands` |
| `uv` binary | astral.sh | Install (skipped if already present) |
| CPython interpreters | github.com (python-build-standalone releases) | `seed python`; the installer's default-environment setup; first `uv tool install` if no Python exists on the machine |
| Python packages (incl. `hatchling` to build seed-cli, and the default venv packages `ipython`/`ruff`) | pypi.org | Install; `seed venv`; `seed install`; `seed update-commands` |
| MinGit (Windows only) | github.com (git-for-windows releases) | First `seed repo-clone` if no git is found |
| VS Code + extensions | update.code.visualstudio.com / marketplace.visualstudio.com | First `seed vscode` / `seed repo-vscode` |

---

## 1. seedling's own source — built-in support

Put a copy of this repo on a network share (say `S:\tools\seedling`), edit
[`seedling.conf`](../seedling.conf) in that copy, and users install by
running `install.cmd` from it (or with
`SEEDLING_REPO=S:\tools\seedling` from anywhere). The installer records the
share as `update_source`, so `seed update-commands` re-copies from it —
**no git involved anywhere** in this flow. To ship an update, replace the
contents of the share.

A self-hosted git server (GitHub Enterprise, GitLab, Gitea) works the same
way with a URL instead of a path; updates then do a fresh shallow clone,
which requires git on user machines (see #5).

---

## 2. The `uv` binary

The installers normally download uv from `astral.sh` — but they **skip that
step entirely if uv is already in place**:

- Windows: `~\seedling\system\bin\uv.exe`
- macOS/Linux: `~/seedling/system/bin/uv`

So the offline recipe is: download uv's standalone binary once (from
[github.com/astral-sh/uv/releases](https://github.com/astral-sh/uv/releases),
on a connected machine) and drop it into `vendor/uv/` in your repo copy —
the installer places it automatically. Pin one uv version for the whole organization and update it deliberately —
that also pins which Python versions "newest" resolves to.

---

## 3. Python interpreters

`seed python` (and `uv tool install`, when no usable Python exists on the
machine) downloads CPython builds from the
[python-build-standalone](https://github.com/astral-sh/python-build-standalone)
GitHub releases. To redirect this:

1. Mirror the release archives you need onto an internal web server or
   file share (only the platforms/versions you actually use — one
   `cpython-<version>-windows-x86_64-none` archive is ~30 MB).
2. Set **`SEEDLING_PYTHON_MIRROR`** in `seedling.conf` to that location —
   a URL, or just the share path (`S:\tools\python-builds`); seedling
   converts paths to the `file://` form uv needs.

The installer applies it to its own default-environment setup and records
it as the `python_mirror` setting, which every later `seed python` applies
automatically.

---

## 4. Python packages

`seed venv` (default packages), `seed install`, and building seed-cli
itself all resolve packages from PyPI. Redirect this by setting
**`SEEDLING_PACKAGE_INDEX`** in `seedling.conf` to either:

- an **index URL** (any pip-compatible index: Artifactory, Nexus, devpi),
  or
- a **plain directory of wheels** (e.g. a network share folder). seedling
  then generates a uv configuration declaring that directory as the one
  and only package source, with the internet index disabled entirely — a
  package that isn't in the folder fails cleanly instead of silently
  reaching for pypi.org.

Like the mirror, it's applied during install itself (building seed-cli
needs it) and recorded as the `package_index` setting for every later
command. The index/directory must contain at minimum:

- **`hatchling`** (and its dependencies `packaging`, `pathspec`,
  `pluggy`, `trove-classifiers`) — uv needs it to **build seed-cli from
  source** during install and every `seed update-commands`.
- **the default venv packages** (`ipython`, `ruff`, `ipykernel`, `pip`, and their dependencies)
  for every new venv. If your organization prefers a different set, change
  `SEEDLING_VENV_DEFAULT_PACKAGES` in `seedling.conf` and stock those
  instead.
- Whatever your users actually `seed install`.

### Populating a wheel directory

seedling ships the builder for this folder so you don't need a separate pip
setup on the connected machine. From a machine with internet (or reach to your
internal index):

```
seed download-whl hatchling ipython ruff ipykernel pip pandas
```

downloads each package **and every transitive dependency** as wheels into
`./wheelhouse`. Feed a list you already maintain with
`seed download-requirements requirements.txt` instead. Copy the resulting
folder to the share and set `SEEDLING_PACKAGE_INDEX` (or `seed config set
package_index`) to it.

Two things to keep in mind for a share-only deployment:

- **Match the target platform.** Wheels default to the platform you run the
  command on. If the connected machine differs from the fleet, build for the
  target explicitly — every `pip download` flag passes through:
  `seed download-whl pandas --only-binary=:all: --platform win_amd64
  --python-version 312`.
- **A missing transitive dependency fails resolution outright** offline (the
  internet index is disabled), so build the wheel set from a clean list and
  test it by creating a venv on a disconnected machine.

If you already have an internal index URL configured, `download-whl` uses it
automatically (as `--index-url`) — handy for staging a share from an
Artifactory/Nexus mirror.

---

## 5. git (optional)

git is needed for exactly two things, both avoidable:

- **`seed repo-clone`** — cloning your internal repos. If your git host is
  on the internal network, users need a git client: extract
  [MinGit](https://github.com/git-for-windows/git/releases) (Windows) into
  `vendor/git/` in your repo copy — the installer places it at
  `~\seedling\extensions\git\`, which seedling checks right after PATH
  and never re-downloads from — or deploy git through your normal
  software channel. [`build-offline.cmd`](#the-easy-way-build-offlinecmd) can
  fetch it for you: it asks during the walkthrough, and `--mingit` turns it on
  (which is also what includes it under `--yes`).
- **URL-based `seed update-commands`** — only if your `update_source` is a
  git URL. A directory `update_source` (the network-share flow above)
  needs no git at all.

If neither applies, skip this component entirely.

---

## 6. VS Code (optional)

`seed vscode` downloads VS Code from Microsoft's update API and extensions
from the marketplace — neither has a supported mirror. Three options:

- **Let the builder do it** (easiest): [`build-offline.cmd`](#putting-it-together-preparing-the-share)
  downloads VS Code + the default extensions and drops them into `vendor/vscode/`
  for you. Skip that step with `--no-vscode` if you don't want it.
- **Pre-seed it by hand**: run `seed vscode` once on a connected machine, then
  copy the resulting `~/seedling/extensions/vscode/` folder into `vendor/vscode/`
  in your repo copy — the installer places it on each machine, and seedling
  detects the existing install and never re-downloads. VS Code is fully
  portable in this layout — settings and extensions travel with the folder.
- **Skip it**: everything else in seedling works without VS Code; users
  bring whatever editor your organization deploys.

Additional extensions on an offline network must be installed from `.vsix`
files (`code --install-extension foo.vsix`), downloadable from the
marketplace website on a connected machine.

---

## The default environment setup

A standard install ends by installing the newest Python and creating the
auto-activated `dev` venv. Offline, this works **only if #3 and #4 are in
place** (it needs an interpreter archive and the `ipython`/`ruff`
packages), and the VS Code part only works pre-seeded (#6) — otherwise set
`SEEDLING_AUTO_VSCODE="false"` alongside it. If none of it is ready yet, set
`SEEDLING_AUTO_SETUP="false"` in your distributed `seedling.conf` — the install then finishes bare but working,
and the setup can be run later per-machine:

```
seed python && seed venv dev && seed config set default_venv dev
```

A failed auto-setup is never fatal either way — seedling itself still
installs; users just see a warning with those same commands.

---

## Putting it together: preparing the share

### The easy way: `build-offline.cmd`

The repo ships a builder that assembles the entire bundle for you. On a
**connected** machine, from a checkout of this repo:

```
build-offline.cmd                 (Windows)
sh ./build-offline.cmd            (macOS/Linux)
```

It walks you through every component below, asking before it downloads each
(or pass `--yes` to build the whole thing unattended), and produces a ready
folder:

```
offline-bundle/
  seedling/          <- repo copy, with vendor/uv + vendor/vscode filled in and seedling.conf written
  python-builds/     <- the exact interpreter archive your shipped uv wants
  wheels/            <- hatchling + the default venv packages (+ any --packages you add)
```

It also pre-seeds portable **VS Code and its default extensions** into
`vendor/vscode/` (the ~300MB step — skip it with `--no-vscode`). Copy the folder
to your share and you're done — the generated `seedling.conf` already points at
the three paths. Useful flags:

| Flag | Purpose |
|---|---|
| `--yes` | Build unattended, taking the default answer for every step |
| `--python 3.12,3.11` | Which interpreter version(s) to mirror (default: newest) |
| `--packages pandas,polars` | Extra wheels to stock beyond the defaults |
| `--no-vscode` | Skip the VS Code + extensions download (the ~300MB step) |
| `--mingit` | Also bundle portable MinGit (Windows; off by default) |
| `--deploy-root S:\tools` | Bake the final share path into `seedling.conf` |
| `--dry-run` | Show the plan and exit without downloading |

It is **not** a `seed` command — it prepares the distribution, so it runs from
the checkout before seedling is installed anywhere. It needs Python 3.9+ and
internet on the build machine, and targets the platform you run it on (build on
the same OS/arch as your offline machines).

uv, the interpreters, the wheels, and VS Code + extensions are all automatic.
Two things are opt-in: **MinGit** is off unless you pass `--mingit` (most fleets
already have git — see [#5](#5-git-optional)), and **corporate CA
certs** are yours to supply (see the CA section). Note that under `--yes` every
step takes its default, so MinGit is skipped unless you pass `--mingit` too.

### By hand

If you'd rather assemble it yourself (or need VS Code pre-seeded), the same
layout on a connected machine is:

```
S:\tools\seedling\                     <- a copy of this repo
S:\tools\seedling\vendor\uv\           <- pinned uv binary (placed automatically)
S:\tools\seedling\vendor\git\          <- (optional) extracted MinGit
S:\tools\seedling\vendor\vscode\       <- (optional) pre-seeded portable VS Code
S:\tools\python-builds\                <- python-build-standalone archives
S:\tools\wheels\                       <- wheels: hatchling + the default venv packages + your org's packages
```

And in `S:\tools\seedling\seedling.conf` — the **only file anyone edits**:

```
SEEDLING_REPO_URL="S:\tools\seedling"
SEEDLING_PYTHON_MIRROR="S:\tools\python-builds"
SEEDLING_PACKAGE_INDEX="S:\tools\wheels"
```

Then a user runs `S:\tools\seedling\install.cmd` and gets the full
experience — newest mirrored Python, `dev` venv with your default
packages auto-activated, and `seed update-commands` flowing from the share
— without their machine ever attempting to reach the internet, and without
setting a single environment variable.

---

## HTTPS and corporate certificate authorities

If your internal mirror/index/git host serves HTTPS signed by a corporate
CA, plain installs fail certificate verification. Two independent fixes,
both zero-touch for users:

- **Ship the CA with the repo**: drop the `.pem`/`.crt` files into
  `vendor/certs/`. The installer concatenates them into
  `~/seedling/system/certs/ca-bundle.pem`, records it as the `ca_cert`
  setting, and every seedling command then trusts it automatically —
  uv downloads (`SSL_CERT_FILE`), git clones (`GIT_SSL_CAINFO`), and
  seedling's own downloads all included. Unlike the binary payloads, the
  bundle is **rebuilt on every install**, so certificate rotation
  propagates with a plain reinstall.
- **Use the OS trust store**: if IT already installs the corporate CA
  machine-wide via policy, set `SEEDLING_NATIVE_TLS="true"` in
  `seedling.conf` instead — recorded as the `native_tls` setting and
  applied to uv as `UV_NATIVE_TLS`.

`seed health-check` verifies the recorded bundle still exists, and explicitly
set `SSL_CERT_FILE`/`UV_NATIVE_TLS` environment variables always win over
the settings.

---

## Variant: nothing but a shared drive

An organization whose only common infrastructure is a **file share between
machines** — no internal web servers, no git host, no index server — can
still run everything. Each server-shaped component above has a plain-files
equivalent:

| Component | Share-only equivalent |
|---|---|
| seedling source + updates | Already file-based (#1) — the ideal case |
| Python interpreter mirror | `SEEDLING_PYTHON_MIRROR="S:\tools\python-builds"` — a share folder of archives; seedling handles the `file://` conversion |
| Package index | `SEEDLING_PACKAGE_INDEX="S:\tools\wheels"` — a **directory of wheels** on the share; the internet index is disabled automatically. Populate it on a connected machine with [`seed download-whl`](#populating-a-wheel-directory) (include `hatchling`, the default venv packages, and all transitive deps for your platform) |
| git hosting | git needs no server: **bare repositories on the share** (`git init --bare S:/repos/project.git`) are full remotes — `seed repo-clone S:/repos/project.git`, push, and pull all work over git's file protocol |
| VS Code | Pre-seeded portable folder in `vendor/vscode/`, as above (#6) |

Practical notes for this setup: since all users are on the same platform
(typical for VM fleets), the wheel directory stays small and single-arch;
a missing transitive dependency fails resolution outright rather than
falling back, so test the wheel set by creating a venv from a clean
machine; and file-protocol git remotes rely on share permissions for
access control.

---

## Known degradations offline

- **Download checksum lookups** (used for MinGit and VS Code metadata)
  aren't reachable — irrelevant in practice, since those downloads don't
  happen offline; anything pre-seeded was verified when you fetched it.
- **`seed python` "newest"** means the newest your pinned uv knows about
  and your mirror stocks — update the uv binary and mirror together.
- The conf values translate into uv's own knobs under the hood
  (`UV_PYTHON_INSTALL_MIRROR`, `UV_DEFAULT_INDEX`, or a generated
  `system/config/uv.toml`). A power user who sets those `UV_*` environment
  variables explicitly still wins over the config — useful for one-off
  experiments, never required.
