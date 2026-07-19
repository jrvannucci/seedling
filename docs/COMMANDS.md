# Command reference

Every `seed` command and flag, as currently implemented. For the guided
tour, start with **[Using seedling](GUIDE.md)**.

---

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

## `seed python [version]`

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

## `seed python-list`

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

## `seed remove-python <tag> [-y]`

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

## `seed venv <name> [--python <tag>] [--no-default-packages]`

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

## `seed venv-list`

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

## `seed activate <name>`

Activates a venv **in your current shell** (see
[Why `seed` is a shell function](GUIDE.md#why-seed-is-a-shell-function)). Resolves
the right activation script per OS/shell:
- POSIX: `<venv>/bin/activate`
- Windows: `<venv>/Scripts/Activate.ps1` (falls back to `activate.bat`)

```
seed activate myproject
```

## `seed deactivate`

Deactivates whatever venv is currently active in your shell, by invoking
the `deactivate` function/command that the venv's own activation script
defined. Prints a message instead of erroring if nothing is active.

```
seed deactivate
```

## `seed venv-default [name]`

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

## `seed install <package...>`

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

## `seed uninstall <package...>`

Direct passthrough to `uv pip uninstall <package...>`, with the same
argument-forwarding and `VIRTUAL_ENV` warning behavior as `seed install`.

```
seed uninstall requests
```

## `seed package-list`

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

## `seed download-whl <package...>`

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

## `seed download-requirements <requirements.txt>`

Same as `download-whl`, but reads package specifiers from a `requirements.txt`
(forwarded to `pip download -r`). Everything else — default `./wheelhouse`
destination, flag passthrough, `package_index`/`ca_cert` handling — is identical.

```
seed download-requirements requirements.txt
seed download-requirements requirements.txt --dest ./bundle --python-version 311
```

## `seed remove-venv <name> [-y]`

Deletes a single venv from `~/seedling/python/venvs`. Force-closes
Python/VS Code processes first (see `seed kill-processes`) so a running
interpreter or open file inside the venv can't block deletion. Warns (but
doesn't block) if the target looks like the currently active venv
(`VIRTUAL_ENV` matches its path) — it'll be force-closed along with
everything else, and your shell deactivates it automatically once it's
gone (see [Why `seed` is a shell function](GUIDE.md#why-seed-is-a-shell-function)).
Prompts for confirmation unless `-y`/`--yes`.

Deletion itself uses a retrying, defensive helper shared by every
`remove-*`/`purge` command — see
[Why deletion is so defensive](DESIGN.md#why-deletion-is-so-defensive)
for the bug this fixes and how.

```
seed remove-venv myproject
seed remove-venv myproject -y
```

## `seed remove-venv-all [-y]`

Deletes **every** venv under `~/seedling/python/venvs`, with the same
process-closing behavior as `seed remove-venv`. Lists them all before
asking for confirmation (skippable with `-y`).

```
seed remove-venv-all
```

## `seed vscode [path] [--reinstall] [--no-open]`

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

## `seed repo-clone <git-url>`

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

## `seed repo-list`

Lists every repo cloned via `seed repo-clone`, along with each one's
`origin` remote URL (if it's still a git checkout with one configured).

```
seed repo-list
```
```
Repos in ~/seedling/repo:
  some-project  -> https://github.com/you/some-project.git
```

## `seed repo-cd [name]`

Changes your **current shell's** directory to a cloned repo — the natural
follow-up to `seed repo-clone`, and the quickest way to run git commands
(`git status`, `git pull`, `git push`) against it. With no name, takes you
to `~/seedling/repo` itself. Errors (without moving) if the repo doesn't
exist.

Like `seed activate`, this only works through the `seed` shell function —
a child process can't change its parent shell's directory — so the CLI
resolves and validates the path, and the function does the actual `cd`
(see [Why `seed` is a shell function](GUIDE.md#why-seed-is-a-shell-function)).

```
seed repo-cd myproject
seed repo-cd
```

## `seed repo-vscode <name>`

Opens a cloned repo in VS Code — installing VS Code first if it isn't
already (same one-time setup as `seed vscode`). Shares the same CLI-entry-
point, detached-process opening logic as `seed vscode`.

```
seed repo-vscode some-project
```

## `seed repo-open [name]`

Opens a cloned repo in the **operating system's file manager** (Explorer
on Windows, Finder on macOS, your desktop's default elsewhere). With no
name, opens `~/seedling/repo` itself. For opening in VS Code, use
`seed repo-vscode`.

```
seed repo-open some-project
seed repo-open
```

## `seed repo-install <name>`

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

## `seed remove-repo <name> [-y]`

Deletes a cloned repo from `~/seedling/repo`. Same process-closing
behavior as `seed remove-venv` before deletion, and the same confirmation
prompt (skippable with `-y`).

```
seed remove-repo some-project
```

## `seed kill-processes <all|name> [-y]`

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

## `seed update-commands`

The **only** thing that updates the `seed` command itself after initial
install. See [The update model](GUIDE.md#the-update-model) for the full
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

## `seed remove-user [-y]`

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

## `seed purge [-y]`

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

## `seed purge-and-reinstall [-y]`

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

## `seed where`

Prints the seedling home directory (`~/seedling`, or the value of the
`SEEDLING_HOME` environment variable override if set).

```
seed where
```

## `seed --version`

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

## `seed summary [--sizes] [--json]`

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

## `seed health-check`

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

## `seed logs-viewer [--days N] [--no-open]`

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

## `seed config [get <key> | set <key> <value> | unset <key>]`

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

