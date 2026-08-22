# Entry points — the files you run directly

Everything else in this reference is a `seed` subcommand, which needs seedling
to already be installed. These four files are the other kind: you run them
*directly*, and three of the four exist precisely for the moments when `seed`
isn't available — before the first install, or after something broke it.

| File | What it's for |
|---|---|
| [`GET_STARTED/install.cmd`](#get_startedinstallcmd) | Install seedling from a copy of the repo |
| [`GET_STARTED/uninstall.cmd`](#get_starteduninstallcmd) | Remove it when `seed purge` can't run |
| [`GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd`](#get_started_offline_bundleoffline-bundlercmd) | Build an air-gapped bundle on a connected machine |
| [the one-line installers](#the-one-line-installers) | Install with no copy of the repo at all |

## One file, every platform

All three `.cmd` files use the same trick, and it's worth understanding once
because it explains their odd first line:

```
:; exec sh "$(dirname "$0")/../installers/install.sh" # POSIX shells take this line...
```

A POSIX shell reads `:;` as a no-op and then `exec`s the real shell script.
`cmd.exe` reads the same line as a **label** and skips it, falling through to
the batch body below. So one file works on Windows, macOS and Linux with no
per-platform instructions — you double-click it or you `sh` it.

The trailing comment is load-bearing: it swallows the carriage return of the
CRLF line ending, which a POSIX shell would otherwise try to execute.

---

## `GET_STARTED/install.cmd`

Installs seedling from the copy of the repo it sits in.

```
.\GET_STARTED\install.cmd          # Windows -- double-clicking also works
sh ./GET_STARTED/install.cmd       # macOS / Linux
```

**What it does.** On Windows it launches `installers\install.ps1` with
`-ExecutionPolicy Bypass` scoped to that single run — a batch file isn't
subject to PowerShell's execution policy, which is the whole reason this
wrapper exists. Your system policy is not changed. On macOS and Linux line 1
hands off to `installers/install.sh` instead.

Either way the real installer then reads
[`GET_STARTED/global.conf`](../DEPLOYMENT.md#deployment-configuration-globalconf),
lays out `~/seedling`, installs uv, builds `seed-cli` from a private copy of
the source, writes the shell hook, and — unless told otherwise — installs
Python and creates the auto-activating `dev` venv.

**After a successful run on Windows** it opens a *new* PowerShell window with
a short welcome banner and leaves it open. That isn't decoration: `seed` is a
shell function defined in your `$PROFILE`, and the window `install.cmd` ran in
is plain `cmd.exe` (with `-NoProfile` besides), so `seed` could never work
there. The fresh window loads your profile, so it works immediately.

**On failure it pauses** before closing, so a double-clicked install that
fails is readable instead of vanishing.

**Environment overrides**, each winning over the conf for one run:

| Variable | Effect |
|---|---|
| `SEEDLING_REPO` | Install from this git URL or directory instead |
| `SEEDLING_HOME` | Install to somewhere other than `~/seedling` |
| `SEEDLING_PROFILE` | Apply this [profile](../PROFILES.md) (a file, or a folder of them) |
| `SEEDLING_AUTO_SETUP` | `false` skips the ready-made Python and `dev` venv |
| `SEEDLING_AUTO_VSCODE` | `false` skips the VS Code download |
| `SEEDLING_CUSTOM_COMMANDS` | Path to a [custom commands](../CUSTOM-COMMANDS.md) file |
| `SEEDLING_VSCODE_CONFIG_DIR` | Folder of `settings.json`/`keybindings.json` to seed |

Any arguments you pass are forwarded to the underlying installer.

---

## `GET_STARTED/uninstall.cmd`

Removes `~/seedling` and the shell-hook line from your shell profile.

```
.\GET_STARTED\uninstall.cmd
sh ./GET_STARTED/uninstall.cmd
```

**Prefer [`seed purge`](lifecycle.md#seed-purge--y---preview---non-interactive).**
It is more thorough, it knows its own install location, and it supports
`--preview`. This file is the **fallback for when `seed` itself is broken** and
can't run at all — a half-finished install, a corrupted `seed-cli`, a shell
hook that never loaded.

It resolves the install location exactly the way the installer did:
`SEEDLING_HOME` if set, else `SEEDLING_HOME_DIR` from `global.conf` (with `~`
and `{user}` expanded), else the default. That matters on relocated and
shared multi-user installs, where a hardcoded `~/seedling` would delete the
wrong thing — or nothing.

It pauses on failure, same as the installer.

---

## `GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd`

Assembles a complete offline bundle on a **connected** machine, to carry to an
air-gapped network.

```
.\GET_STARTED_OFFLINE_BUNDLE\offline-bundler.cmd
sh ./GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd
```

**No arguments.** Everything it needs is declared in `offline-bundle.toml`
beside it — what the share will hold, and every build setting that used to be
a flag. See
[what the share contains](../OFFLINE.md#offline-bundletoml--what-the-share-contains).

**It is not a `seed` command**, deliberately: it prepares the distribution
*before* seedling is installed anywhere, so it can't depend on seedling being
installed. It needs Python 3.12+ on the build machine — the same floor
seedling itself requires, since it imports seedling's own modules to read the
spec and validate profiles.

Flags remain available for one-off builds (`--dry-run`, `--verify-only`,
`--bundle`, `--check-profile`, `--output`, and the rest); the
[offline guide](../OFFLINE.md#the-easy-way-get_started_offline_bundleoffline-bundlercmd) lists them.

The POSIX half lives in `offline-bundler.sh` next to it, which finds a usable
Python 3.12+ and runs `installers/build_offline.py`.

---

## The one-line installers

With no copy of the repo at all, the shell installers can be piped straight
from a URL. This is what the README's one-liners do:

**macOS / Linux**
```sh
curl -fsSL https://raw.githubusercontent.com/jrvannucci/seedling/main/installers/install.sh | sh
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/jrvannucci/seedling/main/installers/install.ps1 | iex
```

They are the same scripts `install.cmd` runs locally — the `.cmd` file only
picks which one and handles the execution policy. Piped, there is no local
`global.conf` to read, so the built-in defaults apply and any configuration
has to come from the environment:

```sh
curl -fsSL .../install.sh | SEEDLING_PROFILE=./team.toml sh
```

---

## Where each one lives

```
GET_STARTED/
├── install.cmd                     -> installers/install.ps1  or  install.sh
├── uninstall.cmd                   -> installers/uninstall.ps1 or uninstall.sh
└── global.conf                        what all of them read
GET_STARTED_OFFLINE_BUNDLE/
├── offline-bundler.cmd             -> offline-bundler.sh -> installers/build_offline.py
├── offline-bundler.sh
└── offline-bundle.toml                what the bundle will contain
installers/
├── install.sh / install.ps1           the real installers
├── uninstall.sh / uninstall.ps1       the real uninstallers
└── build_offline.py                   the real bundle builder
```

The `.cmd` files are launchers; the files under `installers/` do the work and
can be run directly if you prefer.
