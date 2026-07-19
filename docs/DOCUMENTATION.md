# seedling — full documentation

seedling is a single `seed` command that wraps [`uv`](https://astral.sh/uv)
and keeps every Python interpreter, virtual environment, VS Code install,
and cloned repo it manages inside one folder: `~/seedling`. Nothing it does
touches your system Python, `%APPDATA%`, `~/.vscode`, or any of the other
places these tools normally scatter files into.

This document covers every command and behavior as currently implemented.
For a shorter quickstart, see the
[README](https://github.com/cryocliff/seedling#readme).

---

## Contents

- [How installation works](#how-installation-works)
- Running on an offline network -> see [OFFLINE.md](OFFLINE.md)
- [The folder layout](#the-folder-layout)
- [Why `seed` is a shell function](#why-seed-is-a-shell-function)
- [Why deletion is so defensive](#why-deletion-is-so-defensive)
- [Help output & color](#help-output--color)
- [Command logging](#command-logging)
- [Non-interactive mode & previews](#non-interactive-mode--previews)
- [Download verification](#download-verification)
- [Command reference](#command-reference)
- [Admin commands (shared-root teardown)](#admin-commands-shared-root-teardown)
- [The update model](#the-update-model)
- [Uninstalling](#uninstalling)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing) — working on seedling itself -> see [CONTRIBUTING.md](CONTRIBUTING.md)
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
[`seed repo-clone`](#seed-repo-clone-git-url) for details.

### The four ways to install

There are four install origins. Whichever one you use is saved as the
`update_source` setting, so `seed update-commands` (and `seed purge`'s
"reinstall later" hint) keeps pointing back at it. **The thing that differs
between them is what you configure up front** — origins 1 and 2 need nothing;
origins 3 and 4 are set once in
[`seedling.conf`](#deployment-configuration-seedlingconf) so your users don't
have to.

**1. Public GitHub** — the default, for anyone on the open internet
- *Configure:* nothing.
- *Install:* the `curl` / `irm` one-liners → see [One-line install](#one-line-install).
- *Recorded as:* the public repo URL.

**2. Local checkout** — install from a copy of this repo you already have
- *Configure:* nothing.
- *Install:* run `install.cmd` from inside the repo folder → see [Local checkout install](#local-checkout-install).
- *Recorded as:* the checkout **directory** itself, so `seed update-commands` re-copies from that working tree. (An explicit `SEEDLING_REPO`/`SEEDLING_REPO_URL` override records a URL instead.) Developing seedling? The [contributor guide](CONTRIBUTING.md) builds the edit → update loop on this.

**3. Directory / network share** — for machines with no GitHub access at all
- *Configure:* set `SEEDLING_REPO_URL` to a **folder** holding a copy of this repo, in [`seedling.conf`](#deployment-configuration-seedlingconf).
- *Install:* run `install.cmd`; your users pass no flags of their own.
- *Recorded as:* that directory.
- *More:* [Deployment configuration](#deployment-configuration-seedlingconf) — and, for a fully disconnected network, the [offline guide](OFFLINE.md).

**4. Self-hosted git** — a private GitHub Enterprise / GitLab / fork URL
- *Configure:* set `SEEDLING_REPO_URL` to the **git URL**, in [`seedling.conf`](#deployment-configuration-seedlingconf).
- *Install:* run `install.cmd` (or the one-liner with `SEEDLING_REPO` set).
- *Recorded as:* that URL.
- *More:* [Deployment configuration](#deployment-configuration-seedlingconf).

Origins 3 and 4 are the organization-deployment story: set the source **once**
in the [`seedling.conf`](#deployment-configuration-seedlingconf) you
distribute, and everyone installs with no flags or environment variables at
all. To install from a different source for a **single run** without editing
anything, set the `SEEDLING_REPO` environment variable instead — see
[Installing from a different source, for one run](#installing-from-a-different-source-for-one-run).

### One-line install

```sh
curl -fsSL https://raw.githubusercontent.com/cryocliff/seedling/main/installers/install.sh | sh
```
```powershell
irm https://raw.githubusercontent.com/cryocliff/seedling/main/installers/install.ps1 | iex
```

By default the installers clone from
`https://github.com/cryocliff/seedling.git` (the `DEFAULT_SEEDLING_REPO` /
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

### What the installer actually does, step by step

1. **Locates the source.** If run from inside a copy of this repo (it
   checks for `src/pyproject.toml`), it uses that. Otherwise it clones the
   resolved source via `git clone --depth 1`, or copies it if it's a
   directory path.
2. **Lays out `~/seedling/`** — `system/bin/`, `system/config/`,
   `system/shell/`, `python/base/`, `python/venvs/`, `extensions/`, `repo/`.
3. **Copies the source into `~/seedling/system/src`** — minus any `.git`
   folder: no git checkout lives inside seedling, and the origin is
   recorded in the `update_source` setting instead. This copy, not the
   original download/clone location, is what `seed-cli` actually gets
   installed from. See [The update model](#the-update-model).
   Any `vendor/` folder in the source (offline binaries: uv, portable
   git, pre-seeded VS Code — see [OFFLINE.md](OFFLINE.md)) is placed into
   its runtime locations at this point, and excluded from the copy.
4. **Installs `uv` into `~/seedling/system/bin`**, using uv's own official
   installer with `UV_INSTALL_DIR` redirected there and
   `UV_NO_MODIFY_PATH=1` set (seedling manages its own PATH/shell
   integration rather than letting uv touch your global PATH). Skipped if
   `~/seedling/system/bin/uv` already exists.
5. **Installs `~/seedling/system/src/src` as an isolated uv tool**, via
   `uv tool install --force --reinstall`, with `UV_TOOL_DIR` and
   `UV_TOOL_BIN_DIR` redirected into `~/seedling/system/tool` and
   `~/seedling/system/bin`. uv will fetch its own private Python
   interpreter for this if none is available — you still never need Python
   pre-installed. This produces the `seed-cli` binary/shim. `--reinstall`
   forces uv to bypass its build cache, which matters every time
   `seed update-commands` runs this same step later.
6. **Sets up the default environment** (unless `SEEDLING_AUTO_SETUP` is
   `no`, or a `dev` venv already exists from a previous install): installs
   the newest stable Python, creates a `dev` venv with the default
   packages, and records `dev` as the `default_venv` that new shells
   auto-activate — unless a different `default_venv` was already chosen.
   Also downloads the portable VS Code (unless `SEEDLING_AUTO_VSCODE` is
   `no`, or it's already present) so `seed vscode` opens instantly.
7. **Writes the shell integration.** Copies `seed.sh.template` /
   `seed.ps1.template` into `~/seedling/system/shell/seed.sh` (or `.ps1`),
   with the real `~/seedling` path substituted in, then appends a line to
   your shell profile (`.zshrc`, `.bashrc`, `.profile`, or `$PROFILE`) that
   sources it — only if that line isn't already present.

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
│   └── vscode/
│       └── app/                   portable VS Code
│           └── data/               portable-mode settings + extensions, all local
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
  [Why deletion is so defensive](#why-deletion-is-so-defensive).
- Every other subcommand is forwarded straight through to the real
  `seed-cli` binary as a normal subprocess.

If you invoke `seed-cli activate <name>` or `seed-cli deactivate` directly
(bypassing the shell function — e.g. by calling the binary path explicitly),
you'll get a message explaining that this only works through the `seed`
shell function, since a subprocess has no way to affect your shell.

---

## Why deletion is so defensive

Every command that deletes a directory (`remove-venv(-all)`, `remove-python`,
`remove-repo`, `remove-user`, `purge`) routes through a shared helper
(`robust_rmtree`) that works around four real causes of "file in use" /
permission-denied failures, rather than just calling
`shutil.rmtree(path, ignore_errors=True)` and hoping:

1. **The calling process's own working directory being inside the folder
   being deleted.** Windows refuses to delete a directory that is any
   running process's cwd — including `seed-cli` itself. This is easy to hit
   in practice: activate a venv, `cd` into its project directory (or the
   venv folder itself), then run a remove/purge command from right there.
   The fix moves the process out to the user's home directory first, if
   its cwd is inside (or is) the target.
2. **A process that was just force-closed** (a blocked delete closes
   whatever is holding the files, see `seed kill-processes`) not having
   released its file handles instantly. The fix retries deletion a few
   times with a short delay instead of failing on the first pass.
3. **Read-only files.** Windows refuses to delete them outright, and git
   marks every file under `.git/objects` read-only — so any tree holding a
   git checkout (every cloned repo) would otherwise fail on hundreds of
   files at once. The error handler clears the read-only bit and retries
   each failed file individually.
4. **A program can't delete its own running executable.** `seed purge` and
   `seed remove-user` run *as* `seed-cli.exe` (plus the tool venv's
   `python.exe` underneath it), which live inside the very tree being
   deleted. When those are the only survivors, the command hands them to a
   small invisible helper that finishes the deletion a moment after
   `seed-cli` exits — and says so, instead of reporting an error. The
   `seed` shell function (still loaded in your session) then waits for the
   helper and prints an explicit confirmation — "Confirmed: ~/seedling has
   been fully removed" — or a warning with the leftover path if something
   is still holding files open, so the outcome is never silent.

If a file is genuinely still stuck after all retries — something *outside*
seedling holding it open — you get its exact path printed, instead of a
vague "something might be in use" message.

---

## Help output & color

`seed` (no arguments) or `seed -h`/`--help` shows commands grouped into
Seedling Status / Python & venvs / Git repos / VS Code / Utilities / a
"danger zone" for everything destructive — rather than argparse's default flat, alphabetized
list, which stops being easy to scan once there are more than a handful of
commands. Subcommand-specific help (`seed venv -h`, etc.) is unaffected and
still uses argparse's normal per-command output.

Color (used for headers, warnings, and success messages) is automatically
disabled when stdout isn't a real terminal — piped output, redirected to a
file, CI logs — or when the `NO_COLOR` environment variable is set (per
[no-color.org](https://no-color.org)), so scripting against seedling's
output never has to deal with stray ANSI escape codes. On Windows, seedling
enables virtual terminal processing itself rather than requiring it be
turned on beforehand.

Output from the tools seedling drives is attributed in the terminal: lines
coming from uv are prefixed `[uv]`, and lines from git are prefixed
`[git]`, so it's always clear whether a message came from seedling itself
or from the tool underneath.

---

## Command logging

Every `seed` invocation appends to a daily log file under
`~/seedling/system/logs/` (e.g. `seed-2026-07-05.log`):

- the exact command line and a timestamp,
- everything the command printed — stdout *and* stderr, including the
  tagged `[uv]`/`[git]` output — with ANSI color codes stripped, so the
  logs are plain text end to end (shippable to a server, greppable, and
  displayable anywhere with no escape-code handling),
- and the exit code.

Log files older than 30 days are pruned automatically. Logging never
interferes with the command itself: if the log file can't be written, the
command carries on unlogged. Set `SEEDLING_NO_LOG=1` to disable logging for
a given call (the shell integration uses this itself for its startup
`default_venv` query, so opening a terminal doesn't spam the log).

---

## Non-interactive mode & previews

Every destructive command (`remove-python`, `remove-venv`, `remove-venv-all`,
`remove-repo`, `remove-user`, `purge`, `kill-processes`) supports three
shared flags:

- `-y` / `--yes` — skip the confirmation prompt and proceed.
  (`SEEDLING_YES=1` is the environment equivalent.)
- `--preview` — print exactly what would be deleted (full paths; for
  `kill-processes`, the actual matching processes running right now), then
  exit without changing anything.
- `--non-interactive` — never wait for keyboard input. Anything that would
  have prompted aborts safely instead, unless `-y` was also given.
  (`SEEDLING_NONINTERACTIVE=1` is the environment equivalent.) This is the
  mode for scripts and CI, where a forgotten prompt would otherwise hang
  the job forever.

### How a removal frees locked files

Deleting a file that another process holds open **fails on Windows** and
**succeeds on POSIX** — unlinking there just removes the directory entry. So
everything below is a Windows concern; on macOS and Linux a removal simply
works and none of it runs.

Every remove command (`remove-venv`, `remove-venv-all`, `remove-python`,
`remove-repo`, `remove-user`, `purge`) escalates only as far as it has to:

1. **Delete.** Usually nothing is holding anything, and **nothing is closed.**
2. **Find out what's blocking, and close only that.** seedling asks the
   Windows **Restart Manager** — the API installers use for *"the following
   applications are using files that need to be updated"* — which names the
   processes holding the surviving files. It reports them and closes just
   those:
   ```
   Something is holding files (dev): VS Code (pid 4821)
   Closing just those...
   ```
   A directory that is another process's *working directory* also blocks
   removal without holding any file handle, and the Restart Manager can't see
   that; a scoped search covers it, matching processes by where they live
   rather than by name.
3. **Last resort.** Only if the targeted close didn't free the tree does
   seedling force-close every Python and VS Code process, which is what it
   used to do unconditionally.

Earlier versions ran step 3 up front, every time — so removing a throwaway venv
would close an unrelated editor window before establishing anything was wrong.

Matching by **location rather than process name** matters in both directions.
An unrelated system Python or an editor window on another project is left
alone; and a process named nothing like Python — a PyQt/PySide app's
`QtWebEngineProcess.exe`, or a `node`/`ffmpeg` binary bundled in a venv — is
still caught, because it lives inside the tree being deleted.

`seed kill-processes` is the manual equivalent, and follows the same
principle: it closes **only seedling's processes by default**, and needs an
explicit `--system` for the machine-wide sweep.

```
seed kill-processes             # only seedling's own processes (default)
seed kill-processes --system    # every python + VS Code on the machine
seed kill-processes <name>      # every process with that name
```

`seed kill-processes all` was the old spelling of `--system` and still works
that way — it is deliberately *not* re-pointed at the narrow mode, since that
would silently change what an existing script does.

### Unsaved work in cloned repos

The commands that can delete cloned repos — `seed purge`, `seed remove-repo`
and `seed remove-user` — check each repo first for work that exists nowhere
else, and name what's at risk:

```
2 repo(s) contain work that deleting them would destroy:
  - analysis: 1 uncommitted change, 1 untracked file
  - etl: 1 untracked file
```

That covers uncommitted changes, untracked files, and commits never pushed to
a remote. It runs **before** the confirmation prompt and before the process
kill that closes VS Code, so you see it while you can still act on it.

It reports rather than blocks. `-y` still proceeds — scripted teardowns keep
working — but the warning is printed either way, so it lands in the terminal
and in seedling's run log. `--preview` shows it too.

`seed purge --keep-repos` and `seed purge-and-reinstall` don't warn: they move
repos to safety and restore them, so nothing is at risk.

Two things it cannot see, and does not claim to: **unsaved editor buffers**
(nothing has written them to disk yet, and the process kill closes VS Code),
and **unpushed commits on a branch with no upstream** (there's no remote to
compare against). Treat a clean result as "git found nothing", not as
"verified safe".

---

## Download verification

The two things seedling downloads itself as plain archives — portable
MinGit on Windows and VS Code — are verified against their publishers'
SHA-256 checksums before extraction (GitHub's release-asset digest for
MinGit; VS Code's update API hash for VS Code). A checksum mismatch deletes
the download and aborts with an explanation. If no checksum could be
obtained (e.g. the metadata endpoint is blocked on your network), the
download proceeds but says so explicitly. uv and Python interpreters are
installed by uv's own tooling, which does its own verification.

---

## Command reference

Command names follow two rules: **a bare noun is the primary action and
`noun-verb` is management of that thing** (`python` installs, `python-list`
lists) — except **everything that deletes is a `remove-*` command**, so every
destructive action reads the same way (`remove-venv`, `remove-python`,
`remove-repo`, `remove-user`) and they group together in help's Danger Zone:

| Family | Commands |
|---|---|
| Python interpreters *(structural — the base installs venvs are built from)* | `python [ver]` *(install)*, `python-list`, `remove-python` |
| Venvs & packages *(day-to-day environment work)* | `venv <name>` *(create)*, `venv-list`, `activate`, `deactivate`, `venv-default`, `install`, `uninstall`, `package-list`, `remove-venv`, `remove-venv-all` |
| Offline utilities *(build a wheel set for an air-gapped machine)* | `download-whl <package...>`, `download-requirements <req.txt>` |
| Repos | `repo-clone`, `repo-list`, `repo-cd`, `repo-vscode`, `repo-open`, `repo-install`, `remove-repo` |
| Everyday / singletons | `vscode`, `summary`, `health-check`, `logs-viewer`, `config`, `where`, `kill-processes`, `update-commands`, `remove-user`, `purge`, `purge-and-reinstall` |

**Python interpreters** — structural commands: the base installs that venvs
are built from. Most days you never touch these after the first install.

### `seed python [version]`

Installs a base CPython interpreter via `uv python install`, redirected
(via `UV_PYTHON_INSTALL_DIR`) into `~/seedling/python/base`. With no
version at all, installs the **newest stable Python** uv knows about and
derives the tag from what actually landed (e.g. `314`) — this is what the
installer's default-environment setup uses.

- Accepts `312`, `3.12`, or `3.12.4` — digits are extracted and normalized
  into a dotted version spec for uv, and a short tag (e.g. `312`) for the
  folder alias.
- After installing, seedling locates the real directory uv created and
  writes the `<tag>.alias.json` pointer file described above.
- The **first** base Python you install becomes the default used by
  `seed venv` when you don't pass `--python`. This is tracked in
  `~/seedling/system/config/settings.json`.

```
seed python 312
```

### `seed python-list`

Lists every base Python interpreter installed via `seed python`, showing
the short tag, the real versioned directory it points to, which one is the
default used by `seed venv`, and flags any alias whose target directory has
gone missing (e.g. if it was deleted by hand).

```
seed python-list
```
```
Base Python interpreters in ~/seedling/python/base:
  311      -> cpython-3.11.9-linux-x86_64-gnu
  312      -> cpython-3.12.4-linux-x86_64-gnu  (default for `seed venv`)
```

### `seed remove-python <tag> [-y]`

Deletes a base Python **and every venv that was built from it** — venvs
can't function without the interpreter they were created against, so this
cascades rather than leaving them broken.

- Detects dependent venvs by reading the `home` field out of each venv's
  `pyvenv.cfg` and checking whether it resolves inside the base Python's
  directory.
- Lists exactly what it's about to delete (the base, plus each dependent
  venv by name) before asking for confirmation, unless `-y`/`--yes`.
- Closes whatever turns out to be holding files open, escalating only as
  far as needed (see *How a removal frees locked files*) — so nothing blocks
  deletion.
- If the removed base was the default for `seed venv`, automatically
  switches the default to another remaining base (or clears it if none are
  left).

```
seed remove-python 311
```

---

**Venvs & packages** — the day-to-day family: creating and switching
environments, and installing packages into them.

### `seed venv <name> [--python <tag>] [--no-default-packages]`

Creates a virtual environment at `~/seedling/python/venvs/<name>` via
`uv venv --python <interpreter>`, then installs the default packages
(`ipython`, `ruff`, and `ipykernel`, unless changed via
`seed config set venv_default_packages ...`) into it.

- `--python <tag>` selects which installed base Python to build from
  (matching a tag from `seed python`). If omitted, uses the default base
  (the first one installed).
- `--no-default-packages` (alias `--bare`) skips the default package
  install for just this venv. If the package install fails (e.g. offline),
  the venv itself is still created and usable.
- Fails with a clear message if the requested base isn't installed, or if
  a venv with that name already exists.
- uv's own output is shown as-is (interpreter resolution, creation
  confirmation) *except* for its "activate with: source .../activate" hint,
  which is filtered out -- that's not how `seed activate` actually works
  (it's a shell function, not a sourced script path), so showing it would
  just be confusing. seedling prints its own `seed activate <name>`
  instruction instead.

```
seed venv myproject
seed venv myproject --python 311
```

### `seed venv-list`

Lists every venv under `~/seedling/python/venvs`, showing the Python
version each was created with (read straight from its `pyvenv.cfg`) and
marking whichever one matches the current `VIRTUAL_ENV` (i.e. the one
you're actually inside right now) as active.

```
seed venv-list
```
```
Venvs in ~/seedling/python/venvs:
  myproject  [python 3.12.4]  (active)
  scratch    [python 3.11.9]
```

### `seed activate <name>`

Activates a venv **in your current shell** (see
[Why `seed` is a shell function](#why-seed-is-a-shell-function)). Resolves
the right activation script per OS/shell:
- POSIX: `<venv>/bin/activate`
- Windows: `<venv>/Scripts/Activate.ps1` (falls back to `activate.bat`)

```
seed activate myproject
```

### `seed deactivate`

Deactivates whatever venv is currently active in your shell, by invoking
the `deactivate` function/command that the venv's own activation script
defined. Prints a message instead of erroring if nothing is active.

```
seed deactivate
```

### `seed venv-default [name]`

Shows or sets the venv every **new** shell auto-activates on startup —
sugar for `seed config get/set default_venv`, promoted to its own command
because it's the setting people actually reach for. The installer's
default-environment setup points this at `dev`; switching it to your real
project is a natural next step.

- With a name: validates the venv exists, then sets it. Existing shells
  are unaffected — open a new terminal (or `seed activate <name>`).
- With no name: prints the current default (or that none is set).
- Clear it with `seed config unset default_venv` — new shells then start
  with no venv active.

```
seed venv-default
seed venv-default myproject
```

### `seed install <package...>`

Direct passthrough to `uv pip install <package...>` — everything after
`install` is forwarded untouched (flags, version pins, multiple packages,
`-U`/`--upgrade`, an editable `-e .`, etc. all work exactly as they would
with `uv pip install` directly), including flags given as the very first
argument.

Prints a warning first (but still proceeds) if `VIRTUAL_ENV` isn't set in
the environment, since `uv pip` needs a target environment to install into.

```
seed install requests
seed install -U "django>=5,<6" pillow
seed install -e .                       # editable install of the current project
```

### `seed uninstall <package...>`

Direct passthrough to `uv pip uninstall <package...>`, with the same
argument-forwarding and `VIRTUAL_ENV` warning behavior as `seed install`.

```
seed uninstall requests
```

### `seed package-list`

Direct passthrough to `uv pip list` for the active venv. Anything after
`package-list` is forwarded to `uv pip list` untouched (e.g. `--format
json`, `--outdated`). Same `VIRTUAL_ENV` warning as `install`/`uninstall`.

```
seed package-list
```
```
Package            Version
------------------ ---------
certifi            2026.6.17
requests           2.34.2
urllib3            2.7.0
```

### `seed download-whl <package...>`

Downloads a package **and all of its dependencies** as `.whl` files (plus any
source archives) into a flat folder — the offline-bundle builder. Run it on a
connected machine, carry the folder to an air-gapped one, and point
`package_index` at it:

```
seed download-whl pandas
# ... copy ./wheelhouse to the offline machine or a share ...
seed config set package_index /path/to/wheelhouse
seed install pandas
```

Wheels land in `./wheelhouse` unless you pass your own `--dest`. Under the hood
it runs `uvx pip download` (uv has no `pip download` of its own, so `pip` runs
as an ephemeral uv tool — nothing is installed permanently), so **every
`pip download` flag passes straight through**. That makes cross-platform
bundles easy — build wheels for a machine you're not sitting at:

```
seed download-whl numpy --only-binary=:all: \
    --platform manylinux2014_x86_64 --python-version 312 --dest ./linux-wheels
```

If `package_index` (an Artifactory/Nexus/devpi URL, or a wheels directory) or
`ca_cert` are configured, they're applied automatically as `--index-url` /
`--find-links --no-index` / `--cert`, so a bundle can itself be built from an
internal index without setting any environment variables.

### `seed download-requirements <requirements.txt>`

Same as `download-whl`, but reads package specifiers from a `requirements.txt`
(forwarded to `pip download -r`). Everything else — default `./wheelhouse`
destination, flag passthrough, `package_index`/`ca_cert` handling — is identical.

```
seed download-requirements requirements.txt
seed download-requirements requirements.txt --dest ./bundle --python-version 311
```

### `seed remove-venv <name> [-y]`

Deletes a single venv from `~/seedling/python/venvs`. Force-closes
Python/VS Code processes first (see `seed kill-processes`) so a running
interpreter or open file inside the venv can't block deletion. Warns (but
doesn't block) if the target looks like the currently active venv
(`VIRTUAL_ENV` matches its path) — it'll be force-closed along with
everything else, and your shell deactivates it automatically once it's
gone (see [Why `seed` is a shell function](#why-seed-is-a-shell-function)).
Prompts for confirmation unless `-y`/`--yes`.

Deletion itself uses a retrying, defensive helper shared by every
`remove-*`/`purge` command — see
[Why deletion is so defensive](#why-deletion-is-so-defensive)
for the bug this fixes and how.

```
seed remove-venv myproject
seed remove-venv myproject -y
```

### `seed remove-venv-all [-y]`

Deletes **every** venv under `~/seedling/python/venvs`, with the same
process-closing behavior as `seed remove-venv`. Lists them all before
asking for confirmation (skippable with `-y`).

```
seed remove-venv-all
```

### `seed vscode [path] [--reinstall] [--no-open]`

Opens VS Code at `path` (defaults to the current directory), installing a
fully portable copy into `~/seedling/extensions/vscode/app` first if none
exists — though a default install already did that up front (see
`SEEDLING_AUTO_VSCODE` in `seedling.conf`), so normally this just opens.
`--no-open` installs/verifies without opening a window (what the
installer's default setup uses).

- **Portable mode:** a `data/` folder is created next to the VS Code
  executable, which makes VS Code keep all settings, extension installs,
  and workspace state inside that same folder — nothing goes to
  `~/.vscode`, `~/Library/Application Support`, or `%APPDATA%`.
- **Default settings** written on first install
  (`data/user-data/User/settings.json`):
  - `editor.formatOnSave: true`, default formatter set to Ruff
  - `notebook.formatOnSave.enabled: true`
  - `python.terminal.activateEnvironment: true`
  - `python.analysis.typeCheckingMode: "basic"`
  - `files.autoSave: "onFocusChange"`
  - Telemetry, auto-update, and extension auto-update all turned off
- **Default extensions** installed on first install:
  - `ms-python.python`, `ms-python.vscode-pylance`, `ms-python.debugpy`
    (Python language support + debugging)
  - `ms-toolsai.jupyter`, `ms-toolsai.jupyter-keymap`,
    `ms-toolsai.jupyter-renderers` (Jupyter notebooks)
  - `charliermarsh.ruff` (fast linting/formatting)
  - `editorconfig.editorconfig`
  - `mechatroner.rainbow-csv` (color-codes CSV/TSV columns by position, plus
    a simple SQL-like query feature over the file)
- `--reinstall` forces a fresh download/reinstall even if VS Code is
  already present.
- **Uses VS Code's actual CLI entry point** (`bin/code.cmd` on Windows,
  `Contents/Resources/app/bin/code` on macOS, `bin/code` on Linux) for both
  installing extensions and opening windows — the same thing that runs
  when you type `code --install-extension ...` or `code .` in a normal
  terminal, rather than the raw Electron GUI binary (which would open a
  full window per extension and flood stdout/stderr with log spam). If the
  CLI script genuinely can't be found, extension installation is skipped
  with a warning rather than falling back to that behavior.
- All subprocess calls (extension installs, opening a window) run with
  stdout/stderr/stdin redirected away from your terminal, and the window-
  open call is fully detached from seedling's own process — `seed vscode`
  returns immediately either way and never blocks on VS Code's own output.
- Idempotent: a plain `seed vscode` with no `--reinstall` only ever
  downloads/reinstalls/re-adds extensions on the very first run for a given
  `~/seedling`; every call after that just opens a window.
- Platform support: downloads the correct stable-build archive for
  Windows (`win32-x64-archive`), macOS (`darwin` / `darwin-arm64`), and
  Linux (`linux-x64` / `linux-arm64`) automatically.

```
seed vscode
seed vscode ./my-project
seed vscode --reinstall
```

### `seed repo-clone <git-url>`

Clones a git repository into `~/seedling/repo/<name>` via `git clone`. The
repo name is derived from the URL (handles `https://host/group/name.git`,
SSH-style `git@host:group/name.git`, and plain paths).

**git itself:** on Windows, if no system `git` is found, seedling
automatically downloads a portable copy ("MinGit", Git for Windows'
official dependency-free build — no installer, no admin rights) into
`~/seedling/extensions/git` and uses that. This is the only piece of
seedling bootstrapped this way, because it's the only platform with a
genuinely portable official build; on macOS and Linux, git is dynamically
linked against system libraries, so there's no equivalent to safely bundle.
There, if git isn't found, you'll get a clear one-line instruction
(`xcode-select --install`/`brew install git` on macOS; your distro's package
manager on Linux) instead of a silent failure.

Fails with a clear message (rather than overwriting) if a repo with that
name already exists — remove it first with `seed remove-repo`.

```
seed repo-clone https://github.com/you/some-project.git
```

### `seed repo-list`

Lists every repo cloned via `seed repo-clone`, along with each one's
`origin` remote URL (if it's still a git checkout with one configured).

```
seed repo-list
```
```
Repos in ~/seedling/repo:
  some-project  -> https://github.com/you/some-project.git
```

### `seed repo-cd [name]`

Changes your **current shell's** directory to a cloned repo — the natural
follow-up to `seed repo-clone`, and the quickest way to run git commands
(`git status`, `git pull`, `git push`) against it. With no name, takes you
to `~/seedling/repo` itself. Errors (without moving) if the repo doesn't
exist.

Like `seed activate`, this only works through the `seed` shell function —
a child process can't change its parent shell's directory — so the CLI
resolves and validates the path, and the function does the actual `cd`
(see [Why `seed` is a shell function](#why-seed-is-a-shell-function)).

```
seed repo-cd myproject
seed repo-cd
```

### `seed repo-vscode <name>`

Opens a cloned repo in VS Code — installing VS Code first if it isn't
already (same one-time setup as `seed vscode`). Shares the same CLI-entry-
point, detached-process opening logic as `seed vscode`.

```
seed repo-vscode some-project
```

### `seed repo-open [name]`

Opens a cloned repo in the **operating system's file manager** (Explorer
on Windows, Finder on macOS, your desktop's default elsewhere). With no
name, opens `~/seedling/repo` itself. For opening in VS Code, use
`seed repo-vscode`.

```
seed repo-open some-project
seed repo-open
```

### `seed repo-install <name>`

Installs a cloned repo's dependencies into the currently active venv:

- If the repo has a `pyproject.toml`, runs `uv pip install -e <repo>`
  (editable install — changes you make in the cloned repo take effect
  immediately without reinstalling, which is what you want when actively
  developing against it).
- Otherwise, if it has a `requirements.txt`, runs
  `uv pip install -r <repo>/requirements.txt`.
- If neither file exists, fails with a message rather than guessing.
- Same `VIRTUAL_ENV` warning as `seed install` if nothing is active.

```
seed activate myproject
seed repo-install some-project
```

### `seed remove-repo <name> [-y]`

Deletes a cloned repo from `~/seedling/repo`. Same process-closing
behavior as `seed remove-venv` before deletion, and the same confirmation
prompt (skippable with `-y`).

```
seed remove-repo some-project
```

### `seed kill-processes <all|name> [-y]`

An escape hatch for stuck scripts or a frozen VS Code window. Always
prompts for confirmation first (skippable with `-y`), since it's
machine-wide and destructive (unsaved work included).

- `seed kill-processes all` — force-closes every process matching common
  Python interpreter names (`python`, `python3`, `python3.8`-`3.14`,
  `pythonw`) and VS Code/Electron process names (`code`, `Code`,
  `Code Helper*`, `Electron`).
- `seed kill-processes <name>` — force-closes every process with that
  **exact** name (e.g. `seed kill-processes node`). On Windows, `.exe` is
  appended automatically if you don't include it.

Implementation notes:
- **Not** seedling-scoped — this affects every matching process on the
  machine, not just ones seedling started.
- Uses only OS-builtin tools: `pgrep -x` + `kill`/`os.kill` on macOS/Linux,
  `taskkill /F /IM` on Windows. No third-party dependency like `psutil`.
- Always excludes seedling's own running process (and its parent) from the
  kill list, so it can't terminate itself mid-cleanup — this matters
  because on macOS/Linux, `seed-cli`'s own process image is literally a
  `python3.x` process (its shebang execs the interpreter directly).
- The underlying `kill_python_and_vscode()` helper is reused by
  `seed remove-venv(-all)`, `seed remove-python`, `seed remove-repo`,
  `seed remove-user`, and `seed purge` — anything that deletes files is
  preceded by this same sweep, to avoid "file in use" failures.

```
seed kill-processes all
seed kill-processes node -y
```

### `seed update-commands`

The **only** thing that updates the `seed` command itself after initial
install. See [The update model](#the-update-model) below for the full
explanation. In short:

- If the `update_source` setting holds a git URL, downloads a fresh
  shallow clone of it into a temp folder, swaps it in as the new
  `~/seedling/system/src` (minus its `.git`), then reinstalls via
  `uv tool install --force --reinstall`. Pass **`--from-branch <branch>`**
  to clone a specific branch or tag instead of the remote's default branch
  — useful for tracking a `dev`/`staging` line or pinning a release tag.
- If `update_source` holds a directory path, re-copies from it instead
  (same swap, same reinstall). `--from-branch` doesn't apply here (a
  directory has no branches) and is ignored with a note.
- If no source is recorded, it just reinstalls from whatever is currently
  in `~/seedling/system/src`, which doubles as a repair command if you've
  hand-edited something there. A failed download also falls back to this,
  never leaving you without a working `seed`.

In every mode it finishes by re-rendering the `seed` shell function
(`~/seedling/system/shell/seed.ps1` / `seed.sh`) from the refreshed
templates, so shell-side changes ship with updates too. Your profile hook
points at that file by path, so the refresh takes effect in new shells
automatically — nothing in your profile is touched.

Replacing a running CLI is inherently delicate on Windows (the reinstall
must delete the tool venv whose `python.exe` is executing the update, and
Windows refuses to delete running executables). `seed update-commands`
handles this by *renaming* the live tool venv and `seed-cli` shim aside
(allowed even while running), installing fresh, and sweeping the set-aside
copies on the next update. If the reinstall fails partway, the previous
copies are renamed back, so a failed update always leaves a working `seed`.

```
seed update-commands
seed update-commands --from-branch dev     # track a branch (git-URL sources)
```

### `seed remove-user [-y]`

Deletes `~/seedling` in its entirety — every base Python, every venv, VS
Code and all its extensions/settings, every cloned repo, uv itself,
everything. Prompts for confirmation (`yes` typed exactly) unless
`-y`/`--yes` is passed.

Before deleting, it first force-closes every Python and VS Code process on
the machine (the same sweep as `seed kill-processes all`, with the same
self-exclusion so it can't kill `seed-cli`'s own process mid-run). This
avoids the classic "file is in use" failure on Windows, and stray file
handles on any OS, from a running venv interpreter or an open VS Code
window blocking deletion of files inside `~/seedling`. Like
`kill-processes`, this is machine-wide, not seedling-scoped — the
confirmation prompt says so up front.

This does **not** remove the `seed` shell function/hook from your shell
profile — use `seed purge` (or `uninstall.cmd` --
`sh ./uninstall.cmd` on macOS/Linux) for that.

```
seed remove-user
```

### `seed purge [-y]`

The full uninstall — everything `seed remove-user` does, **plus** removes
the `seed` shell hook from every shell profile it can find:
`~/.zshrc`, `~/.bashrc`, `~/.bash_profile`, `~/.profile`, and both the
PowerShell Core and Windows PowerShell profile locations (checked on every
OS, since PowerShell itself is cross-platform — harmless no-ops wherever
they don't exist).

After `seed purge` finishes, `seed` stops existing as a command entirely.
This is the same end state as running `uninstall.cmd` (or
`sh ./uninstall.cmd` on macOS/Linux), just reachable from inside `seed` itself without needing
the original installer files around. Reports exactly which profile files
it edited.

**`--keep-repos`** moves `~/seedling/repo` out to a sibling folder
(`~/seedling-repo-backup`, or `-1`/`-2`/... if that already exists) before
deleting everything else, so your cloned repos survive the purge. Without
it, repos are deleted along with everything else — if you have cloned
repos and didn't pass the flag, the confirmation screen reminds you before
asking you to type `yes`, but there's a single confirmation gate either
way (no separate interactive question to answer differently).

Without `--keep-repos`, any leftover `~/seedling-repo-backup*` folder from a
*previous* `seed purge --keep-repos` is deleted too — the flag means "keep
repos this time," so leaving it off means you're saying you don't want
them kept around at all, and stale backups from an earlier purge would
otherwise just accumulate in your home directory forever.

The interactive confirmation screen also points out the alternatives
before you commit: how to preserve repos (`--keep-repos`), the smaller
partial-removal commands (`remove-venv`, `remove-venv-all`, `remove-python`,
`remove-repo`, and `remove-user`, which keeps the shell hook), and the
reinstall instructions matched to how this copy was installed: the
public one-liners for a github.com install, "run the installer on the
share again" for a network-drive install, or "clone this URL" for a
self-hosted git install. The same instructions are printed again after a
successful purge — that's the last output `seed` ever produces, so it's
the last chance to see them.

```
seed purge
seed purge --keep-repos
seed purge -y --keep-repos
```

```
seed purge
```

### `seed purge-and-reinstall [-y]`

The wipe-and-start-fresh command: everything `seed purge` does, then it
**reinstalls seedling** from the source the original install recorded (the
`update_source` setting — the git URL it was cloned from, or the directory it
was copied from). Use it to rebuild a corrupted install, or to reset every
base Python, venv, and package back to a clean slate in one step.

**Cloned repos are always preserved.** They're moved to safety before the
wipe (like `seed purge --keep-repos`) and then **restored** into the freshly
reinstalled `~/seedling/repo`, so a reinstall never costs you your repos —
no flag needed.

How it works around a program not being able to delete-then-relaunch its own
executable: seed-cli writes a small self-contained reinstall script to a temp
path *outside* `~/seedling` (so it survives the wipe), then does the purge.
The `seed` **shell function** — still loaded in your terminal after seed-cli
exits — waits for the wipe to finish and then runs that script in the
foreground, so you see the reinstall happen. Because this relies on the shell
function, an existing install must have picked up this version first (run
`seed update-commands` once); a brand-new command needs the updated `seed`
either way. Open a new terminal afterward to pick up the fresh environment.

If **no `update_source` is recorded** (uncommon — every install origin records
one; mainly if you cleared it with `seed config unset update_source`), it asks
whether to reinstall from the public repo (`github.com/cryocliff/seedling`) and
aborts *without deleting anything* if you decline — set a source first with
`seed config set update_source <git-url-or-directory>`.

Reinstalling has exactly the same requirements as a first-time install from
the same source — this command adds none of its own. A **URL** source is
`git clone`d by the installer: on **Windows** that needs no pre-installed git
(the installer bootstraps a portable MinGit into `~/seedling/extensions/git`
first, the same copy `seed repo-clone` uses), while on **macOS/Linux** git
must already be on your PATH (there's no official portable build to bootstrap
there). A **directory** source (e.g. a network share, the offline-install
path) is reinstalled from in place with no git and no network.

```
seed purge-and-reinstall
seed purge-and-reinstall --preview
seed purge-and-reinstall -y
```

### `seed where`

Prints the seedling home directory (`~/seedling`, or the value of the
`SEEDLING_HOME` environment variable override if set).

```
seed where
```

### `seed --version`

Prints the version of seedling that is actually running, as
`seedling <version>`. Worth quoting in any bug report — with
`seed update-commands` in the picture, an install can be at a different
version than the share it was built from.

```
seed --version
seed -V
```

The version lives in exactly one place, `src/seedling/__init__.py`.
`src/pyproject.toml` reads it from there (`dynamic = ["version"]`), so a
release is a one-line edit and the built distribution, the CLI, and the
grouped `seed help` footer can never disagree.

### `seed summary [--sizes] [--json]`

One read-only screen showing everything seedling has installed: uv/git/VS
Code status, every base Python (and which is default), every venv (its
Python version, which is active, which auto-activates in new shells),
every cloned repo with its origin remote, and all current settings.
`--sizes` also computes disk usage per item and a grand total (it walks
the whole tree, so it can take a few seconds on big installs).

```
seed summary
seed summary --sizes
seed summary --json
```

`--json` prints the same facts as machine-readable data instead of a
rendered screen — for scripts, CI, and coding assistants that need to know
where things are without guessing. It writes nothing but JSON to stdout, so
it's safe to pipe.

The object carries a `schema` number (currently `1`); it's bumped when a
field changes meaning or goes away, never for a field that's merely added.
When seedling isn't installed yet, the object is just `schema`, `home`, and
`installed: false` — check `installed` before reading anything else.

Each venv reports a `python_executable`: the absolute path to that venv's
own interpreter, already resolved for the platform (`Scripts\python.exe` on
Windows, `bin/python` elsewhere). That's the field to use when something
needs to *run* the interpreter rather than describe it.

Size fields (`size_bytes` per item, `total_size_bytes`) are `null` unless
you pass `--sizes`, since computing them is the slow part.

```jsonc
{
  "schema": 1,
  "home": "C:\\Users\\alice\\seedling",
  "installed": true,
  "install_type": "single-user",     // or "multi-user"
  "shared_root": null,
  "tooling": {
    "uv":     { "version": "uv 0.7.19 (...)", "path": "..." },
    "git":    { "path": "..." },                    // null if not found
    "vscode": { "installed": false, "path": null, "size_bytes": null }
  },
  "pythons": [
    { "tag": "312", "target": "cpython-3.12.7-...", "path": "...",
      "default": true, "present": true, "size_bytes": null }
  ],
  "venvs": [
    { "name": "dev", "path": "...", "python_version": "3.12.7",
      "python_executable": "...\\python\\venvs\\dev\\Scripts\\python.exe",
      "active": true, "default": true, "size_bytes": null }
  ],
  "repos": [
    { "name": "myrepo", "path": "...", "remote": "https://...",
      "size_bytes": null }
  ],
  "settings": { "default_venv": "dev", "...": null },
  "total_size_bytes": null
}
```

### `seed health-check`

The health check. Verifies each moving part and prints one line per check
with three columns: a **STATUS** (`OK` / `WARN` / `FAIL`), a cyan **AREA**
label saying what the check is about (`uv`, `git`, `config`, `python`,
`venv`, `updates`, `defaults`, `certs`, `offline`, `shell`, `logs`), and the
detail. It checks: uv actually runs, git is available, the config file
parses, every base Python alias resolves to a real interpreter, every venv
has its interpreter and its base Python still exists, the configured
defaults (`default_base`, `default_venv`) point at things that exist, the
`update_source` is recorded **and actually verified** — a git URL gets a
reachability probe (`git ls-remote`, 10-second timeout, prompt-proofed so it
can never hang asking for credentials), and a directory source must exist
and look like a seedling tree (an unmounted share is reported as exactly
that, not assumed to be a URL) — any offline `python_mirror`/`package_index` directories
and `ca_cert` bundle exist, the `seed` shell hook is installed and not
stale (a hook line
pointing at a deleted file gets a loud warning), and the log directory is
writable.

`FAIL` means a core operation would not work right now and makes the
command exit 1 (useful in scripts/CI); `WARN` is informational (nothing
installed yet, no git, etc.) and doesn't affect the exit code.

```
seed health-check
```

### `seed logs-viewer [--days N] [--no-open]`

Renders every logged `seed` command (the daily plain-text files under
`~/seedling/system/logs/`) into a single **self-contained HTML page** and
opens it in your browser. The page is offline — no CDN, no network — so it
works on a closed network like everything else in seedling. It's a
**master-detail** view: a dense table on the left (**Date · Time · Status ·
Command · Duration**), and clicking a row shows that command's full output in
the pane on the right. Status is colour-coded from each command's recorded
exit code, and duration is computed from the start/finish timestamps. Above
the table are a search box (matches command *and* output), a **failures-only**
toggle, and an **interactive date-range picker** (All / Today / 7 days /
30 days presets, plus custom From/To date fields).

All embedded commands are filtered client-side, so changing the date range
is instant and needs no regeneration. `--days` still controls how much
history gets embedded in the first place (the picker can only reach within
what's loaded).

**The bootstrap installer is captured too**, into
`system/logs/install-<timestamp>.log`, shown in the viewer tagged **`setup`**
alongside your `seed` commands — so a failed or surprising install is there
to inspect after the fact.

- **macOS/Linux (`install.sh`)** tees its *entire* run — every step and the
  output of the tools it invokes (uv, git, seed-cli) — into the log, in the
  same block format as the daily logs (with a real exit code).
- **Windows (`install.ps1`)** records the console via `Start-Transcript`,
  which captures seedling's own `==>` narrative and the uv bootstrap, but
  **not** the raw output of native tools like `uv.exe`/`git` — on Windows
  PowerShell 5.1, redirecting a native command's stderr under
  `$ErrorActionPreference='Stop'` turns uv's normal progress into a fatal
  error, so the installer deliberately doesn't do that. The individual
  `seed python` / `seed venv` setup steps still appear as their own entries
  (they log themselves); the VS Code step runs as a background job during
  install (overlapping the Python setup for speed), so its output shows up
  inside the install log rather than as a separate entry. The installer ends
  its log with an explicit `seedling install completed (exit code 0)` /
  `FAILED (exit code 1)` marker, which is where the viewer's green/red
  status badge for the install comes from. (The transcript is UTF-16; the
  viewer detects that automatically.)

The page is written to `~/seedling/system/logs/logs-viewer.html` and
regenerated on every run.

- `--days N` — only include the last N days of logs (default: all, up to the
  30-day retention window runlog keeps).
- `--no-open` — write the HTML file but don't launch a browser (prints the
  path; useful over SSH / on a headless box).

```
seed logs-viewer
seed logs-viewer --days 7
```

### `seed config [get <key> | set <key> <value> | unset <key>]`

Views and changes seedling's own settings, stored in
`~/seedling/system/config/settings.json`. Bare `seed config` lists every
setting with its current value and an explanation. The keys:

- `default_base` — the base Python tag `seed venv` builds from when
  `--python` isn't given. Set automatically by your first `seed python`.
- `default_venv` — a venv name that **every new shell auto-activates** on
  startup. Unset means no auto-activation. (Existing shells are
  unaffected; open a new terminal to see it.)
- `update_source` — where `seed update-commands` gets seedling's own
  source: a git URL (works with self-hosted GitHub/GitLab on isolated
  networks) *or* a plain directory path (e.g. a network drive holding a
  copy of the repo, for machines with no git hosting at all). Recorded
  automatically at install time; unset means updates can only reinstall
  the existing copy.
- `venv_default_packages` — the packages installed into every new venv
  (default: `ipython, ruff, ipykernel`). Takes comma-separated input.
- `python_mirror` / `package_index` — offline sources for interpreters
  and packages (a URL, or a plain directory on a share). Normally seeded
  from `seedling.conf` at install time; see [OFFLINE.md](OFFLINE.md).
- `native_tls` / `ca_cert` — HTTPS trust for corporate-CA internal hosts:
  the OS trust store, or a PEM bundle (normally installed automatically
  from `vendor/certs/`). Applied to uv, git, and seedling's own downloads
  on every command.

`seed config get <key>` prints just the value (nothing at all when unset),
so it's script-friendly. `unset` resets a key to its built-in default.

```
seed config
seed config set default_venv myproject
seed config set update_source https://github.mycompany.com/tools/seedling.git
seed config set update_source "S:\shared\seedling"
seed config set venv_default_packages "ipython,ruff,requests"
seed config unset default_venv
```

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
seed admin-remove-user alice          # removes C:\seedlinglice entirely
```

---

## The update model

seedling is deliberately designed so that **nothing updates the `seed`
command without you explicitly asking it to.**

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
[`seed purge-and-reinstall`](#seed-purge-and-reinstall--y) — it purges and
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
  the installer did — `SEEDLING_HOME` env override, else `seedling.conf`'s
  `SEEDLING_HOME_DIR` with `~`/`{user}` expansion — so relocated and
  shared-root installs are targeted correctly. (For removing *other* users'
  installs on a shared machine, that's the elevated
  [`admin-*` family](#admin-commands-shared-root-teardown) instead.)

If you have *neither* a working `seed` *nor* the repo, you can pipe the
uninstaller straight from GitHub — the same one-liner shape as the
installer (pipe the underlying `installers/uninstall.*`, not `uninstall.cmd`):

```sh
curl -fsSL https://raw.githubusercontent.com/cryocliff/seedling/main/installers/uninstall.sh | sh
```
```powershell
irm https://raw.githubusercontent.com/cryocliff/seedling/main/installers/uninstall.ps1 | iex
```

Piped like this there's no local `seedling.conf` to read, so it targets the
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

**A venv or VS Code window is stuck / won't close** — `seed kill-processes
all` (or targeting a specific process name) force-closes it, after
confirmation. Every `remove-*` command and `seed purge` also do this
automatically before deleting anything.

**`git isn't installed, and seedling can't bundle a portable copy on
<macOS/Linux>`** — install git through your OS's package manager (the error
message tells you the exact command for your platform) and try again. On
Windows this shouldn't happen — seedling downloads a portable copy
automatically — but if it does (e.g. GitHub API rate-limiting), the error
message includes a manual download link and the exact folder to extract it
into.

---

## Contributing

Working on seedling itself — the `seed` commands, the installers, or the shell
integration? See the **[contributor guide](CONTRIBUTING.md)** for the
edit → `seed update-commands` loop (including `--from-branch` for tracking a
fork's branch), the source layout, and running the tests.

---

## Known limits

- `seed vscode`/`seed repo-vscode` on macOS unpack the official `.app` bundle
  and launch its embedded CLI binary; this is the least-tested of the
  three platforms.
- `seed python` version resolution assumes CPython (uv's default); PyPy and
  other implementations aren't wired up.
- `seed kill-processes` (and everything that reuses it) is machine-wide,
  not seedling-scoped, by design — see the command reference above.
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
