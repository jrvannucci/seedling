# Using seedling

Everything you need to install seedling, work in it day to day, keep it
updated, and remove it again. This is the end-user guide: it assumes
seedling is being installed on your own machine with its default settings.

- Every command and flag in detail → **[Command reference](COMMANDS.md)**
- Rolling seedling out to other people → **[Deployment guide](DEPLOYMENT.md)**
- Why it behaves the way it does → **[Design and safety](DESIGN.md)**

---

## Contents

- [How installation works](#how-installation-works)
- [The folder layout](#the-folder-layout)
- [Why `seed` is a shell function](#why-seed-is-a-shell-function)
- [Help output & color](#help-output--color)
- [The update model](#the-update-model)
- [Uninstalling](#uninstalling)
- [Troubleshooting](#troubleshooting)
- [Known limits](#known-limits)

---

## How installation works

Nothing needs to be pre-installed to install seedling itself — not Python,
not uv, not git. Installing from a **git URL** (origins 1 and 4 below) does
clone with git under the hood: on Windows the installer bootstraps a portable
copy (MinGit) into `~/seedling/extensions/git` automatically if none is
found, so even a stock box needs nothing; on macOS/Linux git must already be
present (there's no official portable build to bootstrap there). Installing
from a **local checkout** or a **directory/share** (origins 2 and 3) uses no
git at all. Separately, `seed repo-clone` (a feature *of* seedling, used
after it's installed) needs git the same way — reusing that same
auto-bootstrapped portable copy on Windows; see
[`seed repo-clone`](commands/repos.md#seed-repo-clone-git-url) for details.

### Where an install comes from

Whichever origin you use is saved as the `update_source` setting, so
`seed update-commands` keeps pointing back at it. Origins 1 and 2 need no
configuration; 3 and 4 are set once in
[`global.conf`](DEPLOYMENT.md#deployment-configuration-globalconf) so your
users pass no flags of their own.

| Origin | Set up | Install with |
|---|---|---|
| **Public GitHub** (default) | nothing | the `curl` / `irm` one-liner |
| **Local checkout** | nothing | `install.cmd` from inside the repo folder — the checkout itself becomes the update source, which is the loop the [contributor guide](CONTRIBUTING.md) builds on |
| **Directory / network share** | `SEEDLING_REPO_URL` = a **folder** holding a copy of the repo | `install.cmd`; see the [offline guide](OFFLINE.md) for a disconnected network |
| **Self-hosted git** | `SEEDLING_REPO_URL` = the **git URL** | `install.cmd`, or the one-liner with `SEEDLING_REPO` set |

### One-line install

```sh
curl -fsSL https://raw.githubusercontent.com/jrvannucci/seedling/main/installers/install.sh | sh
```
```powershell
irm https://raw.githubusercontent.com/jrvannucci/seedling/main/installers/install.ps1 | iex
```

By default the installers clone from
`https://github.com/jrvannucci/seedling.git` (the `DEFAULT_SEEDLING_REPO` /
`$DefaultSeedlingRepo` value near the top of `installers/install.sh` / `installers/install.ps1`).

### Local checkout install

If you have a local copy of this project (e.g. an unzipped download), run
the installer from inside it:

- **macOS/Linux:** `sh ./install.cmd` (or `installers/install.sh` directly)
- **Windows:** `install.cmd` (double-clicking it also works)

This records the checkout directory as `update_source`, so later
`seed update-commands` re-copies from that same checkout. Developing seedling
itself? The **[contributor guide](CONTRIBUTING.md)** covers the
edit → update loop; see also [The update model](#the-update-model).

### Installing from a different source, for one run

`SEEDLING_REPO` accepts a git URL (a fork, or a self-hosted GitHub/GitLab
on another network) or a plain directory path (e.g. a network drive
holding a copy of this repo — no git hosting needed at all). When it's a
directory, the installer copies from it instead of cloning. Either way
the source is recorded as the `update_source` setting so
`seed update-commands` keeps working from it too.

```sh
SEEDLING_REPO=https://github.com/someone/fork.git sh ./install.cmd
SEEDLING_REPO=/mnt/share/seedling sh ./install.cmd
```
```powershell
$env:SEEDLING_REPO = "https://github.com/someone/fork.git"; .\install.cmd
$env:SEEDLING_REPO = "S:\shared\seedling"; .\install.cmd
```

### What the installer actually does

It locates the source (a repo folder it's run from, else a shallow clone or a
copy of the directory you pointed it at), lays out `~/seedling/`, and copies
the source into `system/src` **minus any `.git`** — no git checkout lives
inside seedling, and the origin is recorded as `update_source` instead. That
private copy, not wherever you downloaded from, is what `seed-cli` is built
and run from; see [the update model](#the-update-model).

It then installs `uv` into `system/bin`, builds `seed-cli` from the copied
source, writes the shell hook, and — unless `SEEDLING_AUTO_SETUP=false` —
installs the newest Python and creates the auto-activating `dev` venv. A
`vendor/` folder in the source (uv, portable git, a pre-seeded editor for an
offline install) is placed into its runtime locations at this point rather
than downloaded.

Everything it writes is under `~/seedling` and the one shell-profile line
that loads the hook. Nothing goes to the registry, `%APPDATA%`, or
`~/.local`.

### Windows execution policy

Running `.\installers\install.ps1` directly, with no flags, fails with an
`is not digitally signed` error — that's Windows' default PowerShell policy
blocking unsigned local scripts, not a bug in the script. Three ways around
it:

- Use `install.cmd` instead — it launches `installers\install.ps1` with
  `-ExecutionPolicy Bypass` scoped to that single run only. It does not change your system-wide policy.
- Use the `irm | iex` one-liner — piping into `Invoke-Expression` never
  saves a local script file, so there's nothing for the policy to block.
- Run manually: `powershell -ExecutionPolicy Bypass -File .\installers\install.ps1`

**After a successful `install.cmd` run**, it opens a brand-new, ordinary
PowerShell window (profile loads normally, so `seed` is available right
away) with a short welcome banner listing the first few commands to try,
and leaves it open at an interactive prompt. This isn't just a convenience:
`install.cmd` itself runs in plain `cmd.exe`, and even drives `installers\install.ps1`
with `-NoProfile`, so there's no window at any point in that original
invocation where `seed` — a PowerShell function defined in `$PROFILE` —
could actually work. On failure, this window is skipped and the original
`cmd.exe` window instead pauses on the error so you can read it.

---

## The folder layout

```
~/seedling/
├── system/                    everything seedling needs to run itself,
│   │                          kept out of the way of what you actually use
│   ├── bin/                      uv, and the seed-cli shim
│   ├── tool/                     the isolated uv-managed venv seed-cli runs in
│   ├── src/                      seedling's own source -- see "update model"
│   ├── config/
│   │   └── settings.json         seedling's own config -- see `seed config`
│   ├── logs/
│   │   └── seed-YYYY-MM-DD.log   every command + its output, one file per day
│   ├── cache/
│   │   └── uv/                   uv's package/interpreter download cache --
│   │                             kept in here instead of ~/.cache / %LOCALAPPDATA%
│   ├── conda/                    micromamba root: conda-forge tool envs and
│   │                             their PATH launchers (`seed forge-install`)
│   ├── shims/                    launchers for PyPI apps (`seed tool-install`)
│   ├── certs/
│   │   └── ca-bundle.pem         corporate CA bundle, only on org installs
│   │                             that ship one in vendor/certs/ (see OFFLINE.md)
│   └── shell/
│       ├── seed.sh                sourced by bash/zsh
│       └── seed.ps1                dot-sourced by PowerShell
├── python/
│   ├── base/
│   │   ├── 312/                   (nothing here directly -- see alias below)
│   │   ├── 312.alias.json         points "312" -> the real versioned dir uv made
│   │   └── cpython-3.12.x-.../    the actual interpreter uv installed
│   └── venvs/
│       └── <name>/                one folder per `seed venv <name>`
├── extensions/
│   ├── vscode/
│   │   └── app/                   portable VS Code
│   │       └── data/               portable-mode settings + extensions, all local
│   ├── spyder-config/             Spyder's own settings, kept in here rather
│   │                              than ~/.config or %APPDATA%
│   └── apps/
│       └── <name>/                one uv-managed env per `seed tool-install`
└── repo/
    └── <name>/                    one folder per `seed repo-clone <url>`
```

Only `system/` holds seedling's own internals; `python/`, `extensions/`,
and `repo/` are the folders you'd actually browse into.

**Why the `.alias.json` files exist:** `uv python install 3.12` creates a
directory named after the exact resolved version and platform (e.g.
`cpython-3.12.4-linux-x86_64-gnu`), not a short `312`. seedling writes a
small JSON pointer file (`312.alias.json`) instead of relying on a symlink,
because creating symlinks requires elevated privileges on Windows by
default. `seed venv`/anything else that resolves a base tag reads this file
first.

---

## Why `seed` is a shell function

`seed activate <name>` and `seed deactivate` need to change environment
variables (`PATH`, `VIRTUAL_ENV`, your prompt) in **your current terminal
session**. A subprocess can never do that to its parent shell — this is the
same reason `conda activate` and `source venv/bin/activate` work the way
they do, rather than being plain executables.

So the installer writes `seed` as a shell **function** (bash/zsh) or
PowerShell function, not just a path to a binary:

- `seed activate <name>` → calls `seed-cli activate <name> --print-path`
  (a hidden flag) to get the venv's activation script path, then **sources**
  that script directly into the current shell.
- `seed deactivate` → calls the `deactivate` function that a venv's own
  activation script defines (bash: via `declare -f`/`command -v`;
  PowerShell: via `Get-Command`), if one exists in the current shell.
- `seed repo-cd [name]` → same trick as activate: the CLI resolves the
  repo's path (`--print-path`), and the function `cd`s the current shell
  there.
- **After every command**, the function checks whether the venv this shell
  has active still exists — if a `remove-venv`/`remove-venv-all`/
  `remove-python`/`remove-user`/`purge` just deleted it, the shell
  deactivates it automatically (printing `(deactivated: the venv this
  shell had active no longer exists)`) instead of leaving a dangling
  prompt pointing at a folder that's gone.
- After `seed purge`/`seed remove-user`, the function also waits for the
  invisible self-deletion helper and prints the final confirmation — see
  [Why deletion is so defensive](DESIGN.md#why-deletion-is-so-defensive).
- Every other subcommand is forwarded straight through to the real
  `seed-cli` binary as a normal subprocess.

If you invoke `seed-cli activate <name>` or `seed-cli deactivate` directly
(bypassing the shell function — e.g. by calling the binary path explicitly),
you'll get a message explaining that this only works through the `seed`
shell function, since a subprocess has no way to affect your shell.

---

## Help output & color

`seed help` groups commands the way you'd look for one rather than
alphabetically, and `seed help --admin` reveals the elevated shared-root
family. Color is on when the output is a terminal and off when it's piped or
redirected, so captured logs stay plain text; `NO_COLOR=1` turns it off
everywhere.

## The update model

seedling is deliberately designed so that **nothing updates the `seed`
command without you explicitly asking it to.**

This section is entirely about the `seed` command's own code. If what's out
of date is your *environment* instead — venvs, packages, or repos drifting
from an organization's [deployment profile](PROFILES.md) — that's
[`seed apply`](commands/status.md#seed-apply-profile---preview---force), a
separate command covered on its own page. Neither updates the other.

The installer doesn't install `seed-cli` from wherever you ran it from — it
clones/copies the source into `~/seedling/system/src` first, and installs
from *that* private copy. Concretely:

- Deleting, moving, or renaming your original download or clone does
  nothing to your working `seed` install — it already has its own copy.
- New commits landing on the GitHub repo you installed from have zero
  effect on your install until you act.
- The only command that ever touches `~/seedling/system/src` (and
  therefore what `seed` does) after the initial install is
  `seed update-commands`.

This means re-running the original `curl | sh` one-liner is not how you
update seedling day-to-day — `seed update-commands` is.

`~/seedling/system/src` is a plain copy of the source — deliberately NOT
a git checkout (no `.git` folder lives inside seedling). Instead, the
installer records where the source came from in the `update_source`
setting, and `seed update-commands` re-fetches from there: a fresh shallow
`git clone` for a URL, a re-copy for a directory path (see `seed config`).
The update covers the shell side too — the rendered `seed` function in
`~/seedling/system/shell/` is rebuilt from the refreshed templates.

If no source is recorded, it just reinstalls from whatever's currently in
`~/seedling/system/src`, so it doubles as a "repair" command if you've
hand-edited something. Note that updating *overwrites* the private copy —
hand-edits there don't survive an update (edit and reinstall from a real
checkout instead if you're developing seedling itself).

After refreshing, it also re-reads the now-current `global.conf` and
reports (never applies) any *setting* it would now seed differently than
what's actually configured — see
[`seed update-commands`](commands/lifecycle.md#seed-update-commands) for the
full explanation. Settings are otherwise seeded once, at install time,
and never re-applied on their own.

The installers accept the same flexibility up front: `SEEDLING_REPO` may
be a git URL *or* a directory containing a copy of this repo. When it's a
directory, the installer copies from it and records it as `update_source`
automatically, so machines on networks without github.com stay updatable.

Installing from a **local checkout** (running the installer from inside the
repo) records that checkout directory as `update_source`, so
`seed update-commands` re-copies from your working tree — the basis of the
edit → update loop for anyone **developing seedling itself**, covered in the
[contributor guide](CONTRIBUTING.md). (Set `SEEDLING_REPO`/`SEEDLING_REPO_URL`
to a URL at install time to re-clone from a remote instead.)

---

## Uninstalling

**The normal way to uninstall is `seed purge`.** It removes the `seed`
shell hook from your profile **and** deletes the whole install directory,
for a full clean removal — and because it runs from inside seedling, it
already knows its own install location (including `{user}` multi-user and
custom `SEEDLING_HOME_DIR` layouts), handles the Windows self-deletion of
its own running executable, and prints the right reinstall instructions
afterward. It needs nothing but a working `seed`, and no leftover installer
files.

```
seed purge
```

To wipe and immediately rebuild instead of just removing, use
[`seed purge-and-reinstall`](commands/lifecycle.md#seed-purge-and-reinstall--y) — it purges and
then reinstalls from the recorded source, preserving your cloned repos.

Two narrower / fallback options:

- `seed remove-user` — removes everything *seedling manages* (Python
  installs, venvs, VS Code, cloned repos, uv, its own source) but **leaves
  the `seed` shell hook** in your profile, so a later reinstall picks back
  up cleanly.
- `uninstall.cmd` (Windows) / `sh ./uninstall.cmd` (macOS/Linux) — the
  **standalone fallback for when `seed` itself is broken** and `seed purge`
  can't run. Run from your copy of the repo; it needs no working seed-cli
  (pure shell/PowerShell). It resolves the install location the same way
  the installer did — `SEEDLING_HOME` env override, else `global.conf`'s
  `SEEDLING_HOME_DIR` with `~`/`{user}` expansion — so relocated and
  shared-root installs are targeted correctly. (For removing *other* users'
  installs on a shared machine, that's the elevated
  [`admin-*` family](DEPLOYMENT.md#admin-commands-shared-root-teardown) instead.)

If you have *neither* a working `seed` *nor* the repo, you can pipe the
uninstaller straight from GitHub — the same one-liner shape as the
installer (pipe the underlying `installers/uninstall.*`, not `uninstall.cmd`):

```sh
curl -fsSL https://raw.githubusercontent.com/jrvannucci/seedling/main/installers/uninstall.sh | sh
```
```powershell
irm https://raw.githubusercontent.com/jrvannucci/seedling/main/installers/uninstall.ps1 | iex
```

Piped like this there's no local `global.conf` to read, so it targets the
**default `~/seedling`**. For a relocated or `{user}` install, tell it where
to look with `SEEDLING_HOME`:

```sh
curl -fsSL .../installers/uninstall.sh | SEEDLING_HOME="/opt/seedling/alice" sh
```
```powershell
$env:SEEDLING_HOME = "D:\seedling\alice"; irm .../installers/uninstall.ps1 | iex
```

---

## Troubleshooting

**"is not digitally signed. You cannot run this script on the current
system"** — see [Windows execution policy](#windows-execution-policy).

**`iex : Cannot bind argument to parameter 'Path' because it is null`**
when running the `irm ... | iex` one-liner — you're running a stale cached
copy of the install script; re-fetch it (or download the repo and run
`install.cmd` instead).

**`seed: command not found` after installing** — open a new terminal (the
shell hook only takes effect in new shells), or manually run
`. ~/seedling/system/shell/seed.sh` (bash/zsh) /
`. ~/seedling/system/shell/seed.ps1` (PowerShell) in your current one.

**`No base Python found`** when running `seed venv` — install one first
with `seed python <version>`.

**`uv was not found in ~/seedling/system/bin or on PATH`** — re-run the
installer; this means the uv bootstrap step didn't complete.

**A venv or VS Code window is stuck / won't close** — `seed kill-processes`
(or `seed kill-processes <name>` targeting a specific process name)
force-closes it, after confirmation. `--system` widens the sweep to every
Python/VS Code process on the machine, not just seedling's own — see
[known limits](#known-limits) below. Every `remove-*` command and
`seed purge` also do this automatically before deleting anything.

**`git isn't installed, and seedling can't bundle a portable copy on
<macOS/Linux>`** — install git through your OS's package manager (the error
message tells you the exact command for your platform) and try again. On
Windows this shouldn't happen — seedling downloads a portable copy
automatically — but if it does (e.g. GitHub API rate-limiting), the error
message includes a manual download link and the exact folder to extract it
into.

---

## Known limits

- `seed vscode`/`seed vscode-repo` on macOS unpack the official `.app` bundle
  and launch its embedded CLI binary; this is the least-tested of the
  three platforms.
- `seed python` version resolution assumes CPython (uv's default); PyPy and
  other implementations aren't wired up.
- `seed kill-processes --system` is machine-wide rather than
  seedling-scoped, by design — see
  [the command reference](commands/lifecycle.md#seed-kill-processes-name---system--y---preview---non-interactive).
- `seed repo-clone`/`repo-install` need git; only Windows is auto-bootstrapped
  (via portable MinGit) — macOS/Linux still need system git already present,
  since neither has an equivalent official portable build.
- `seed repo-install` only recognizes `pyproject.toml` and
  `requirements.txt` — repos using other dependency files (e.g. Poetry's
  `poetry.lock` without a PEP 621 `pyproject.toml` section, or Pipenv) may
  need manual installation.
- The installers assume `curl`/`wget` (POSIX) or PowerShell's
  `Invoke-RestMethod` are available, which is true by default on
  effectively every macOS/Linux/Windows 10+ machine.
