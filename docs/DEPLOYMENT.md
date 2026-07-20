# Deploying seedling in an organization

seedling was built so that one person can prepare a Python environment and
hand it to everyone else as a single command — including on networks with no
internet, no admin rights for users, and an auditor who wants to know exactly
what landed on each machine.

This page is the deployment track. It assumes you are setting seedling up
**for other people**. If you just want to use seedling yourself, read
[Using seedling](GUIDE.md) instead.

---

## Contents

- [Who this is for](#who-this-is-for)
- [Deployment configuration: `seedling.conf`](#deployment-configuration-seedlingconf)
- [Shared-machine (multi-user) installs](#shared-machine-multi-user-installs)
- [Choosing an editor build and registry](#choosing-an-editor-build-and-registry)
- [Rolling out](#rolling-out)
- [Admin commands (shared-root teardown)](#admin-commands-shared-root-teardown)
- [What a security review will ask](#what-a-security-review-will-ask)
- Fully offline / air-gapped networks → **[OFFLINE.md](OFFLINE.md)**

---

## Who this is for

The deployment features exist for environments where the ordinary "install
Python from python.org, then pip install what you need" path is blocked,
unreliable, or unauditable:

- **Disconnected or restricted networks** — no github.com, no pypi.org, or
  outbound access only through an approved mirror. Everything seedling needs
  can come from a git server, an internal index, or a plain file share. See
  [OFFLINE.md](OFFLINE.md).
- **Managed desktops** — users without administrator rights. seedling installs
  entirely inside a folder the user already owns and writes nothing to
  `%APPDATA%`, `~/.local/share`, the registry, or any system location.
- **Shared and lab machines** — one install root serving many users, each with
  a private, conflict-free copy. See
  [Shared-machine installs](#shared-machine-multi-user-installs).
- **Standardizing a team** — every person gets the same interpreter, the same
  default packages, and the same editor setup from one distributed config,
  with no per-user setup instructions to follow or get wrong.

The mechanism in all four cases is the same: you edit
[`seedling.conf`](https://github.com/cryocliff/seedling/blob/main/seedling.conf)
in the copy of the repo you distribute, and everyone who installs from that
copy inherits your settings. **Your users never set an environment variable,
pass a flag, or edit a file.**

---

### Deployment configuration: `seedling.conf`

`seedling.conf` at the repo root is the single place a deployment's paths
and install-time settings live. Every setting is listed in the file with
its default value written out, so there's no guessing what can be changed
or what the current behavior is — values left at their defaults change
nothing. Standard users installing from the internet never touch it.
Organizations replace whichever values they need in the copy of the repo
they distribute (self-hosted git host, or a folder on a network drive),
and everyone installing from that copy picks the values up with no flags
or environment variables:

- `SEEDLING_REPO_URL` (default: the public GitHub repo) — the source used
  when the installer isn't run from inside a checkout, and where
  `seed update-commands` fetches updates. A git URL or a plain directory path.
- `SEEDLING_HOME_DIR` (default: `~/seedling`) — the folder everything
  seedling manages lives in. A leading `~` means the installing user's
  home directory. A `{user}` token expands to the installing user's login
  name, so a **shared** install root gives each user a private,
  conflict-free folder: `SEEDLING_HOME_DIR="C:\seedling\{user}"` puts
  alice in `C:\seedling\alice`, bob in `C:\seedling\bob`. (The installer
  resolves the token before writing anything, and the shell integration
  exports the resolved `SEEDLING_HOME` so seed-cli finds it at runtime.)
- `SEEDLING_VENV_DEFAULT_PACKAGES` (default: `ipython,ruff,ipykernel`) —
  comma-separated packages installed into every new venv (seeds the
  `venv_default_packages` setting).
- `SEEDLING_AUTO_SETUP` (default: `true`) — after installing seedling
  itself, install the newest stable Python and create a `dev` venv (with
  the default packages) that every new shell auto-activates. Set to `false`
  for a bare install; the `SEEDLING_AUTO_SETUP` environment variable
  overrides for one run. Never fatal: if this step fails (e.g. offline),
  seedling itself is still installed and working.
- `SEEDLING_AUTO_VSCODE` (default: `true`) — also download and set up the
  portable VS Code during install, so `seed vscode` opens instantly
  instead of downloading ~130 MB on first use. Only applies when
  `SEEDLING_AUTO_SETUP` is `true`.
- `SEEDLING_PYTHON_MIRROR` (default: empty = internet) — where `seed
  python` downloads interpreter builds: a URL of an internal mirror, or a
  plain directory of python-build-standalone archives on a share. Seeds
  the `python_mirror` setting.
- `SEEDLING_PACKAGE_INDEX` (default: empty = pypi.org) — where packages
  install from: an index URL, or a plain directory of wheels on a share
  (the internet index is then disabled entirely). Seeds the
  `package_index` setting. See [OFFLINE.md](OFFLINE.md) for the full
  offline deployment guide.
- `SEEDLING_NATIVE_TLS` (default: `false` = bundled trust store) — set to
  `true` to trust the operating system's certificate store, for internal
  HTTPS hosts signed by a machine-installed corporate CA (seeds the
  `native_tls` setting). Alternatively, ship the CA itself in
  `vendor/certs/` — see [OFFLINE.md](OFFLINE.md).
- `SEEDLING_VSCODE_FLAVOR` (default: `microsoft`) — which editor build
  `seed vscode` installs: the official Visual Studio Code, or `vscodium`,
  the MIT-licensed community build. Seeds the `vscode_flavor` setting. See
  [Choosing an editor build and registry](#choosing-an-editor-build-and-registry)
  — this is a licensing choice as much as a technical one.
- `SEEDLING_EXTENSION_GALLERY` (default: empty = the flavor's own registry)
  — base URL of the extension registry, for an internal Open VSX mirror.
  Seeds the `extension_gallery` setting.
- `SEEDLING_VSCODE_EXTENSIONS` (default: empty = the flavor's starter kit)
  — comma-separated extensions installed into a fresh editor, or `none` for
  no extensions at all. Seeds the `vscode_extensions` setting.

How it's applied: both installers read `seedling.conf` at the repo root
(a piped install reads the copy inside the repo it just cloned). The
install source is always recorded as `update_source`, and other values
that differ from the public defaults are written alongside it, into
`~/seedling/system/config/settings.json` on **first install only** — an
existing settings file is never overwritten, so later `seed config set`
choices survive reinstalls. Resolution order for the install source:

1. `SEEDLING_REPO` environment variable (one-run override)
2. `SEEDLING_REPO_URL` from `seedling.conf`
3. the baked-in public default (what the piped one-liner uses)

### Shared-machine (multi-user) installs

By default seedling lives under each user's home (`~/seedling`), so
multiple users on one machine never interfere. If you'd rather put it on a
shared drive or a common folder — a lab computer, a multi-user server, or
just to keep it off roaming profiles — point `SEEDLING_HOME_DIR` at that
location with a `{user}` token so each person still gets a private,
conflict-free copy.

For example, to install every user under `C:\seedling\<their-name>`, set in
the distributed `seedling.conf`:

```
SEEDLING_HOME_DIR="C:\seedling\{user}"
```

Then when each user runs `install.cmd` from the share:

```
alice  ->  C:\seedling\alice\   (her interpreters, venvs, config, logs)
bob    ->  C:\seedling\bob\
carol  ->  C:\seedling\carol\
```

The installer resolves `{user}` to the login name before writing anything,
and bakes the resolved path into that user's shell hook — so `seed` always
targets their own folder, and `seed purge` only ever touches theirs.
Without the token, everyone would share one `C:\seedling` and collide;
with it, the shared root just holds one subfolder per user. (The default
`~/seedling` needs no token — a home directory is already per-user.)

---

## Choosing an editor build and registry

`seed vscode` installs the official Microsoft build of Visual Studio Code by
default, and its extensions come from the Microsoft Marketplace. For most
teams that is the right choice and needs no configuration.

It is worth a second look if you are **staging an offline bundle onto a
share**, because that means redistributing whatever you pick:

- The official VS Code binaries are distributed under Microsoft's
  proprietary licence — the MIT licence on `microsoft/vscode` covers the
  source, not the branded builds.
- Marketplace extensions carry their own separate Terms of Use.

Both restrict redistribution in ways an internal file share may not satisfy.
If that matters to your organization, switch to the openly-licensed stack:

```
SEEDLING_VSCODE_FLAVOR="vscodium"
```

VSCodium is the same source built without Microsoft's branding and
telemetry, under the MIT licence, and it already points at
[Open VSX](https://open-vsx.org) — an Eclipse Foundation registry whose
content is openly licensed. Nothing else needs setting: seedling picks the
matching extension set automatically.

**The tradeoff is Pylance.** It is proprietary, licensed to run only in
official Microsoft products, and therefore absent from Open VSX by design.
Without it the Python extension falls back to its bundled Jedi language
server, and completions and type checking are noticeably weaker. That is a
real cost to weigh, not a footnote — for many teams it is the deciding
factor in the other direction.

### Pointing at an internal registry

On an isolated network, mirror Open VSX internally and give seedling the
base URL — the gallery and item endpoints are derived from it:

```
SEEDLING_EXTENSION_GALLERY="https://openvsx.mycompany.com/vscode"
```

Setting this on the **`microsoft` flavor** rewrites `product.json` inside
the official build — that is, it modifies a proprietary binary, which is a
licensing question of its own. Prefer `vscodium`, which needs no patching.

### Standardizing the extension set

```
SEEDLING_VSCODE_EXTENSIONS="ms-python.python,charliermarsh.ruff"
```

Empty means the starter kit for the chosen flavor. `"none"` installs
nothing at all — useful when your users get their editor from somewhere else
and only want seedling's Python management.

All three are ordinary settings, so a user can override them locally with
`seed config set` unless you have reason to re-deploy instead.

---

## Rolling out

A workable order for a first deployment:

1. **Pick the install source.** A git URL if you have a self-hosted git
   server; a folder on a share if you don't. This becomes
   `SEEDLING_REPO_URL`, and it is also where `seed update-commands` will
   fetch from later — so put it somewhere durable.
2. **Decide where installs live.** `SEEDLING_HOME_DIR`. Use the `{user}`
   token if several people share one root.
3. **Point package and interpreter downloads at your mirrors** if the
   internet is blocked — `SEEDLING_PACKAGE_INDEX` and
   `SEEDLING_PYTHON_MIRROR`. On a fully disconnected network, run
   `build-offline.cmd` to assemble the whole bundle in one step; see
   [OFFLINE.md](OFFLINE.md).
4. **Set the default environment.** `SEEDLING_VENV_DEFAULT_PACKAGES` decides
   what every new venv starts with — this is where you standardize a team's
   toolchain. `SEEDLING_AUTO_VSCODE` decides whether the portable editor is
   staged during install rather than downloaded on first use.
5. **Prove it on a clean machine** that matches your users' — same OS, same
   lack of admin rights, same network restrictions. The offline guide has a
   [verification procedure](OFFLINE.md#proving-the-bundle-works-before-it-leaves)
   for this.
6. **Distribute.** Users run the one-liner, or double-click `install.cmd` from
   the share on Windows. Nothing else is required of them.
7. **Verify after the fact.** `seed health-check` confirms an install is
   sound; `seed summary` prints everything installed, and `--json` makes that
   machine-readable if you want to collect it across a fleet.

---

## Admin commands (shared-root teardown)

The ordinary `seed purge` / `remove-user` are strictly per-user -- they can
only touch the caller's own folder, by design. For a **shared-root install**
(`SEEDLING_HOME_DIR="<root>/{user}"`), tearing down *other* users needs an
elevated, ownership-seizing operation. That's the `admin-*` family.

These commands are **hidden from normal help** -- `seed help` won't list
them. Reveal them with:

```
seed help --admin
```

Every one of them:

- **Requires elevation** (Administrator on Windows, root on POSIX) and
  refuses with instructions otherwise -- a normal user cannot delete
  another user's files, and shouldn't be able to.
- **Only works on a shared-root install** -- it reads the `shared_root`
  setting recorded at install time when the `{user}` token was used. On a
  plain `~/seedling` it refuses (there are no sibling users to manage). seedling knows its own
  install type from this setting: `seed summary` shows "install type:
  multi-user (shared root: ...)" vs "single-user", and the admin pointer in
  `seed help` only appears on a multi-user install.
- **Takes ownership before deleting** (`takeown` + `icacls` on Windows; root
  already bypasses ownership on POSIX), so user-owned, read-only, and
  runtime-generated files (`__pycache__`, a user's own `pip` installs) don't
  block the teardown -- the gap that install-time permissions can never
  fully close.
- Supports `--preview`, `-y`, and `--non-interactive` like the ordinary
  destructive commands.

| Command | Removes |
|---|---|
| `admin-purge-all-users` | every user's install under the shared root, plus every user's shell hook |
| `admin-remove-user <user>` | one user's entire seedling home |
| `admin-remove-venv <user> <name>` | one user's single venv |
| `admin-remove-venv-all <user>` | all of one user's venvs |
| `admin-remove-python <user> <tag>` | one user's base Python and the venvs built on it |
| `admin-remove-repo <user> <name>` | one user's cloned repo |

Example -- an administrator decommissioning a shared lab machine whose users
live under `C:\seedling\<name>`:

```
# In an Administrator PowerShell:
seed help --admin                     # see the family
seed admin-purge-all-users --preview  # list exactly what would go
seed admin-purge-all-users            # take ownership + remove everyone, confirm first
```

Or cleaning up after one departed user:

```
seed admin-remove-user alice          # removes C:\seedling\alice entirely
```

---
## What a security review will ask

The questions that come up in a review, and where the answer is documented:

| Question | Answer |
|---|---|
| What does it write outside its own folder? | The shell hook line in the user's profile. Nothing else — no registry, no `%APPDATA%`, no system paths. See [the folder layout](GUIDE.md#the-folder-layout). |
| Does it need administrator rights? | No. Only the [`admin-*` family](#admin-commands-shared-root-teardown) does, and only for cross-user teardown. |
| Where does code come from? | Whatever you set in `seedling.conf`. Pointed at internal mirrors, it never contacts github.com or pypi.org — see [OFFLINE.md](OFFLINE.md). |
| Are downloads verified? | Yes — SHA-256 against the publisher's checksum, with an explicit warning when no checksum can be obtained. See [Download verification](DESIGN.md#download-verification). |
| Is there an audit trail? | Every command is logged, one plain-text file per day, under `system/logs/`. See [Command logging](DESIGN.md#command-logging). |
| Can it be removed completely? | `seed purge` deletes the install directory and the shell hook. `admin-purge-all-users` does it for every user under a shared root. Both support `--preview` to show exactly what would go, first. |
| What happens to user data on removal? | Destructive commands check cloned repos for work that exists nowhere else and name it before prompting. See [Unsaved work in cloned repos](DESIGN.md#unsaved-work-in-cloned-repos). |
| Can it run unattended in CI or a deployment script? | Yes — `--non-interactive` and `-y`. See [Non-interactive mode](DESIGN.md#non-interactive-mode--previews). |

The reasoning behind these behaviors is in **[Design and safety](DESIGN.md)**.
