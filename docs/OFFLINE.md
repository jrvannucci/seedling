# Running seedling on an offline network

An organization on an isolated network — no github.com, no pypi.org, no
internet at all — can still install seedling, use it, and keep it updated.
One person prepares a bundle on a connected machine; everyone else runs
`GET_STARTED/install.cmd` from a share and gets a complete Python setup.

> This is part two of the deployment track. The
> **[deployment guide](DEPLOYMENT.md)** covers the settings themselves —
> `global.conf`, shared-machine installs, admin teardown, and what a security
> review will ask. This page covers the one problem an isolated network adds:
> where each downloaded component comes from instead.

---

## The workflow

![The offline bundle drawn as a superset: everything that crosses the air gap sits inside one box, deployment profiles are nested inside it as subsets, a profile naming a package the bundle lacks is drawn outside with the crossing struck through, and global.conf sits outside pointing in.](diagrams/bundle-superset.svg)

**Three files, then one command.** In the copy of seedling you distribute:

```
GET_STARTED_OFFLINE_BUNDLE/offline-bundle.toml    what the share will HOLD
installation-profile/*.toml            what each user ends up WITH, and who gets it
global.conf                            where every machine LOOKS for it
```

On a **connected** machine:

```
offline-bundler.cmd            (Windows -- double-clicking works)
sh ./GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd       (macOS/Linux)
```

No arguments: everything the build needs is in the spec. It validates every
profile against the bundle *before* downloading anything, stages uv, the
interpreters, the wheels, the conda channel and the editor, writes a
`global.conf` pointing at the share, and proves the result installs by doing
an offline install of it.

Then **copy the folder to the share** and re-check the copy that arrived:

```
GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd --verify-only -o "S:	ools"
```

Users run `GET_STARTED/install.cmd` from `S:	ools\seedling\`. Same command for
everyone; each person gets the profiles distributed to them.

Afterwards: edit a profile on the share, users run `seed update-commands`
then `seed apply`. A profile written later, from inside, is checked with
[`seed profile-check`](commands/status.md#seed-profile-check-profile---bundle-path)
before anyone applies it.

## Building the bundle

### `offline-bundle.toml` — what the share contains

The bundle's own config file: a standalone declaration of everything the
share will hold. It lives in `GET_STARTED_OFFLINE_BUNDLE/` beside the
launcher; the bundler reads it by
default.

**It knows nothing about profiles, on purpose.** The dependency runs one way
— profiles conform to the bundle, never the reverse. A superset assembled
from the profiles it ships could never refuse one: it would grow to fit
whatever was asked, and "will this profile work here?" would answer itself.
Declared outright, it's a contract, and a profile that wants more is wrong
before anyone carries it inside.

```toml
# offline-bundle.toml -- everything that will exist on the share.
schema = 1

# The platforms this bundle serves. The wheelhouse covers all of them, so one
# share can serve a mixed fleet. Building on a platform this doesn't list is
# an error.
platforms = ["Windows/x86_64", "Linux/x86_64"]

pythons = ["3.12", "3.11"]

# THE package set: every distribution any profile may name, plus whatever
# users should be able to `seed install` later, when nobody can reach PyPI
# to add one more thing.
packages = ["pandas", "numpy", "scipy", "polars", "httpx", "pytest", "spyder"]

# conda-forge CLI tools -- vendors micromamba and builds a channel.
tools = ["ripgrep", "pandoc"]

[editor]
flavor = "microsoft"          # or "vscodium"
extensions = ["ms-python.python", "charliermarsh.ruff"]
# stage = false               # build a bundle with no editor at all

[git]
mingit = true

```

**Repos are not declared here.** A profile's `[[repo]]` entries are cloned
from a git host on the closed network, which the connected build machine
can't reach — so it can neither vendor them nor resolve their dependencies.
Whatever a repo needs from the wheelhouse (including its extras' dependencies)
goes in `packages` above, named by the person who knows the repo. Nothing can
derive it, so nothing pretends to check it.

`hatchling`, `ipython`, `ruff`, `ipykernel` and `pip` are always downloaded
and never need declaring — seedling itself is built with the first, and the
rest go into every venv `seed venv` creates.

**A mixed fleet needs one wheelhouse, not two bundles.** `pip download` can
resolve for a platform it isn't running on, so the builder makes an extra pass
per declared platform, and a single flat `wheels/` ends up holding `win_amd64`
and `manylinux` wheels side by side. Each machine installs the tags it can.

What does **not** cross over is the native binaries — uv, the interpreter
archives and the editor can only be staged by a machine of that platform. So a
mixed-fleet build is one run per platform into the same output folder:

```
(on Windows)  offline-bundler.cmd
(on Linux)    sh ./GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd
```

The build prints a **coverage report** naming which platforms are complete and
which have wheels only, so a half-finished bundle says so here rather than
being discovered on the far side of the gap.

Profiles are validated against it, never folded into it:

```
GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd --check-profile profiles/research.toml \
                  --check-profile profiles/software-team.toml
```

Each named profile is checked **twice**, because a declaration and a download
fail differently:

- **Before anything is downloaded**, against what the bundle *declares* —
  every axis: packages (including exact `==` pins), interpreters, tools,
  editors, repo extras. Exit `2`, on the connected machine, where the fix
  costs nothing.
- **After the build**, against what actually *landed* — the real wheelhouse,
  interpreter mirror, conda channel and staged editor. This is what catches a
  `pip download` that failed for a single package. Exit `1`.

`--packages`/`--tools`/`--python` still override the file for a one-off
build, and `--bundle=` (empty) ignores it entirely.

> **There is no way for a profile to grow the bundle.** A superset assembled
> from the profile it judges could never refuse one, so profiles are only ever
> checked. `--check-profile` validates one that lives outside
> `installation-profile/`; everything inside that folder is checked without
> being named.

### Checking a profile from inside the air gap

The profiles that matter most are often written *later*, by someone on the
offline network. `seed profile-check` answers "will this apply here?" against
the bundle on disk:

```
seed profile-check ./new-team.toml
```

On a machine installed from a bundle it finds the share by itself
(`package_index` already points into it); otherwise pass `--bundle S:\tools`.
Exit `0` means it applies cleanly, `1` lists exactly what's missing, `2` means
the profile itself is invalid. No network, and nothing is changed.

### The easy way: `GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd`

The repo ships a builder that assembles the entire bundle for you. On a
**connected** machine, from a checkout of this repo:

```
offline-bundler.cmd                 (Windows)
sh ./GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd            (macOS/Linux)
```

It walks you through every component below, asking before it downloads each
(or pass `--yes` to build the whole thing unattended), and produces a ready
folder:

```
offline-bundle/
  MANIFEST.json      <- every component staged, its source and licence,
                        and every wheel's licence grouped by obligation
  seedling/          <- repo copy, with vendor/uv + vendor/micromamba + vendor/vscode
                        filled in and global.conf written
  python-builds/     <- the exact interpreter archive your shipped uv wants
  wheels/            <- hatchling + the default venv packages, plus offline-bundle.toml's
                        `packages` (or --packages / a profile, when there's no spec),
                        resolved once per mirrored interpreter
  conda-channel/     <- only when tools are asked for -- offline-bundle.toml's `tools`,
                        --tools, or a profile's [tools] when there's no spec: a conda
                        channel of conda-forge CLI tools, for `seed forge-install`
```

Declare `tools = [...]` in `offline-bundle.toml` (or pass `--tools
ripgrep,pandoc`, or — with no bundle spec — declare them in your profile) and
the builder vendors **micromamba** and a **conda channel** into the bundle and
points `SEEDLING_CONDA_CHANNEL` at it, so `seed forge-install` (and any tools a
profile declares, via `seed apply`) work offline from the one bundle.

**Python applications** (`seed tool-install`, and `seed spyder`, which uses it)
resolve from the same `wheels/` folder as everything else — they're ordinary
PyPI packages, so `package_index` applies to them just as it does to
`seed install`. Add them to the wheel set with `--packages spyder` and
`seed tool-install spyder` then works with no internet. There's no separate
artifact to carry: unlike conda-forge tools, applications need no channel of
their own.

It also pre-seeds portable **VS Code and its default extensions** into
`vendor/vscode/` (the ~300MB step — skip it with `--no-vscode`). Copy the folder
to your share and you're done — the generated `global.conf` already points at
the three paths. Useful flags:

| Flag | Purpose |
|---|---|
| `-o`/`--output S:\tools\offline-bundle` | Where to assemble the bundle (default: `./offline-bundle`) |
| `--yes` | Build unattended, taking the default answer for every step |
| `--python 3.12,3.11` | Which interpreter version(s) to mirror (default: newest). At least one must satisfy seedling's own `requires-python`; older ones alongside it are fine, and are there for your users' venvs |
| `--packages pandas,polars` | Extra wheels to stock beyond the defaults |
| `--tools ripgrep,pandoc` | conda-forge command-line tools to bundle (see [#5](#component-reference)) — a profile's `[tools]` are included automatically, this is for anything beyond that |
| `--no-vscode` | Skip the VS Code + extensions download (the ~300MB step) |
| `--mingit` | Also bundle portable MinGit (Windows). Normally set as `[git] mingit = true` in the spec |
| `--bundle PATH` | The `offline-bundle.toml` declaring what the share contains. Defaults to the one in `GET_STARTED_OFFLINE_BUNDLE/`; `--bundle=` (empty) ignores it |
| `--check-profile PATH` | Validate a profile against the bundle, before and after building, without adding anything to it. Repeatable — one bundle commonly serves several teams |
| `--verify-only` | Don't build — just run the preflight check against the bundle at `-o` and exit (0 = it installs). Use it on the copy that reached your share |
| `--no-verify` | Skip the preflight check at the end of a build |
| `--deploy-root S:\tools` | Bake the final share path into `global.conf` (defaults to the spec's `deploy_root`) |
| `--accept-third-party-terms` | Acknowledge redistribution rights for the restricted components (VS Code, Marketplace extensions). Deliberately **not** covered by `--yes` |
| `--archive [zip/tar/tar.gz]` | Also pack the finished bundle into one archive file to carry across the gap. Bare `--archive` picks zip on Windows, tar.gz elsewhere |
| `--dry-run` | Show the plan and exit without downloading |

It is **not** a `seed` command — it prepares the distribution, so it runs from
the checkout before seedling is installed anywhere. It needs Python 3.12+ and
internet on the build machine. The **wheels** cover every platform in
`platforms`; **uv, the interpreters and the editor** come from the machine you
run it on, so a mixed fleet means one run per platform into the same output
folder.

uv, the interpreters, the wheels, and VS Code + extensions are all automatic.
Two things are opt-in: **MinGit** is off unless `[git] mingit = true` (most fleets
already have git — see [#6](#component-reference)), and **corporate CA
certs** are yours to supply (see the CA section). Note that under `--yes` every
step takes its default, so MinGit is skipped unless the spec asks for it.

### Proving the bundle works, before it leaves

Every download step reports whether it *succeeded*. That is not the same
question as **would this bundle install with no internet** — and the gap is
expensive, because it's normally discovered in the air-gapped room, after
sign-off.

So the builder finishes by installing from the bundle it just made, on the
build machine, with the network refused:

```
[10] Verify the bundle installs offline
    Python 3.12: interpreter + 4 package(s) install offline.
    seed-cli builds offline on Python 3.12 (hatchling resolved from the bundle).
    Preflight passed: this bundle installs with no internet.
```

It installs each mirrored interpreter from `python-builds/`, creates a venv on
each and installs the default packages from `wheels/`, then builds `seed-cli`
from the bundled source — the step that needs `hatchling` and that actually
blocks an install. Two details make it a real test rather than a formality: it
uses a **cold uv cache** (the build just warmed the normal one, which would
happily satisfy an install from a wheel the bundle is *missing*), and it scrubs
inherited `UV_*`/`PIP_*` variables so nothing can quietly reach the internet.

Run it any time against an existing bundle — **including the copy on your
share**, which is the only way to prove the transfer was complete:

```
GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd --verify-only -o S:\tools\offline-bundle
```

It exits 0 when the bundle installs, non-zero otherwise, so it drops into a
deployment pipeline as a gate. `--no-verify` skips the check during a build.

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

And in `S:\tools\seedling\global.conf` — the **only file anyone edits**:

```
SEEDLING_REPO_URL="S:\tools\seedling"
SEEDLING_PYTHON_MIRROR="S:\tools\python-builds"
SEEDLING_PACKAGE_INDEX="S:\tools\wheels"
```

Then a user runs `S:\tools\seedling\GET_STARTED\install.cmd` and gets the full
experience — newest mirrored Python, `dev` venv with your default
packages auto-activated, and `seed update-commands` flowing from the share
— without their machine ever attempting to reach the internet, and without
setting a single environment variable.

---

## Which scenario is yours


> **In a hurry?** For the common share-only case, skip the manual steps: run
> **`GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd`** (`sh ./GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd` on macOS/Linux) on a
> connected machine. It downloads uv, the Python interpreter archives, all the
> wheels, and (optionally) VS Code + its extensions, then writes a matching
> `global.conf` — see
> [Putting it together](#building-the-bundle). The rest of
> this page explains what it's doing and covers the cases it leaves to you
> (self-hosted indexes, corporate CAs).

Everything is driven by **editing [`global.conf`](../GET_STARTED/global.conf)** in the
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
network access. The [component-by-component reference](#component-reference)
below backs each scenario, and [Putting it together](#building-the-bundle)
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
vendor/micromamba/ (the micromamba binary)             -> ~/seedling/system/bin/
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

## What the bundle is licensed under

The build writes a `MANIFEST.json` naming every component, its source, its
licence, and whether it was staged. The wheel set is reported per package —
resolved from each wheel's own metadata, grouped by obligation — so the file
answers a review rather than deferring to one.

Check it yourself at any point, on either side of the gap:

```
seed whl-licenses S:	ools\wheels
```

```
  copyleft               1   recipients get source and the same rights; matters when distributing outside your organization
  copyleft-weak          2   publish changes if you MODIFY the library itself
  permissive           211   keep the copyright notice and licence text with the copy

Needs a decision (3):
  copyleft         PyQt6            6.7.0    GPL-3.0-only   License-Expression
  ...
```

`seed forge-licenses` does the same for the bundled conda channel, and
`seed venv-licenses` for what a machine ended up running. All three take
`--fail-on copyleft,unknown`, which turns a policy into an exit code you can
run before copying anything to a share.

**Copying a bundle onto a share is redistribution** — that is the act licences
actually govern, and why this is worth a look before the copy rather than
after. [LICENSING.md](LICENSING.md) covers what each family asks of you.

---

## Component reference

`GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd` stages all of this for you. This section is for the
deployments that don't use it — an internal mirror per component, or a partial
bundle — and for understanding what the bundler is doing.

| Component | Normally from | When it's needed | Point it elsewhere with |
|---|---|---|---|
| seedling's own source | github.com | Install; `seed update-commands` | `SEEDLING_REPO_URL` — a git URL **or a folder** on a share (no git needed) |
| `uv` | astral.sh | Install (skipped if already present) | `vendor/uv/` in the copy you distribute |
| Python interpreters | python-build-standalone releases | `seed python`; the installer's default setup | `SEEDLING_PYTHON_MIRROR` — a mirror URL or a folder of archives |
| Python packages | pypi.org | Install; `seed venv`; `seed install`; `seed update-commands` | `SEEDLING_PACKAGE_INDEX` — an index URL, or a folder of wheels (which disables the internet index entirely) |
| conda-forge tools | conda-forge | First `seed forge-install` (micromamba once) | `SEEDLING_CONDA_CHANNEL` — a mirror or a local channel folder |
| git (Windows) | git-for-windows releases | First `seed repo-clone`, if no system git | `vendor/git/` — only needed if the machines have no system git |
| VS Code + extensions | update.code.visualstudio.com / Marketplace | First `seed vscode` | `vendor/vscode/` — a pre-seeded portable copy |

Four things about that table are worth knowing before you rely on it.

**The package index must also serve what seedling itself needs**, not just
your users' packages: `hatchling` (uv builds `seed-cli` with it, at install
and at every `seed update-commands`) plus the default venv packages
(`ipython`, `ruff`, `ipykernel`, `pip`) and all of their transitive
dependencies. A missing transitive dependency fails resolution outright
offline — there is no index to fall back to.

**At least one mirrored interpreter must satisfy seedling's own
`requires-python`.** The mirror does two jobs: it supplies the interpreter
that builds `seed-cli`, and the base Pythons your users create venvs from.
Older versions are fine for the second — mirror as many as you like — but if
none is new enough for the first, the bundle builds cleanly here and fails
there. The bundler checks this before downloading anything and refuses to
build.

**Wheels are resolved once per interpreter and once per platform**, into one
flat folder. That's necessary rather than tidy: headline packages are
version-agnostic but their compiled dependencies aren't — `ipykernel` alone
pulls `pyzmq`, `tornado`, `debugpy` and `psutil`, each shipping separate
`cp312`/`cp313` wheels. A flat folder holding every tag is exactly what an
offline index wants, and it's what lets one wheelhouse serve a mixed fleet.

**Staging the editor is redistribution.** The official VS Code binaries and
Marketplace extensions carry terms that restrict it, so the bundler asks you
to acknowledge that before staging them (see [LICENSING.md](LICENSING.md)).
`[editor] flavor = "vscodium"` switches to the MIT-licensed build and the
openly-licensed Open VSX registry, which carry no such restriction — at the
cost of Pylance. See
[Choosing a VS Code build](DEPLOYMENT.md#which-vs-code-build).

### Populating a wheel directory by hand

```
seed download-whls hatchling ipython ruff ipykernel pip pandas
```

Wheels land in `./wheelhouse`; copy it to the share and set
`SEEDLING_PACKAGE_INDEX` to that folder. Cross-platform bundles take
`pip download`'s own flags: `--platform win_amd64 --python-version 312
--only-binary=:all:`. On a network with an internal index you can publish
them instead of sharing a folder — `seed upload-whls ./wheelhouse`.

---

## The default environment setup


A standard install ends by installing the newest Python and creating the
auto-activated `dev` venv. Offline, this works **only if #3 and #4 are in
place** (it needs an interpreter archive and the `ipython`/`ruff`
packages), and the VS Code part only works pre-seeded (#7) — otherwise set
`SEEDLING_AUTO_VSCODE="false"` alongside it. If none of it is ready yet, set
`SEEDLING_AUTO_SETUP="false"` in your distributed `global.conf` — the install then finishes bare but working,
and the setup can be run later per-machine:

```
seed python && seed venv dev && seed config set default_venv dev
```

A failed auto-setup is never fatal either way — seedling itself still
installs; users just see a warning with those same commands.

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
  `global.conf` instead — recorded as the `native_tls` setting and
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
| Package index | `SEEDLING_PACKAGE_INDEX="S:\tools\wheels"` — a **directory of wheels** on the share; the internet index is disabled automatically. Populate it on a connected machine with [`seed download-whls`](#populating-a-wheel-directory-by-hand) (include `hatchling`, the default venv packages, and all transitive deps for your platform) |
| git hosting | git needs no server: **bare repositories on the share** (`git init --bare S:/repos/project.git`) are full remotes — `seed repo-clone S:/repos/project.git`, push, and pull all work over git's file protocol |
| VS Code | Pre-seeded portable folder in `vendor/vscode/`, as above (#7) |

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
