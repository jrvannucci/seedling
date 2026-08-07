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
| Venvs & packages *(day-to-day environment work)* | `venv <name>` *(create)*, `venv-list`, `activate`, `deactivate`, `run`, `which`, `venv-default`, `auto-activate`, `install`, `uninstall`, `package-list`, `remove-venv`, `remove-venv-all` |
| Python applications *(run, not imported — each in its own env)* | `app-install <name>` *(install)*, `app-list`, `app-remove` |
| Command-line tools from conda-forge *(the non-Python tools)* | `tool <cmd>` *(run)*, `tool-install <name>` *(install)*, `tool-list`, `tool-remove` |
| Offline utilities *(stage packages/tools for an air-gapped machine)* | `download-whl <package...>`, `download-requirements <req.txt>`, `download-tool <name...>` |
| Repos | `repo-clone`, `repo-list`, `repo-cd`, `repo-open`, `repo-install`, `remove-repo` |
| Editors & IDEs *(installed on demand)* | `vscode`, `vscode-repo`, `spyder`, `spyder-repo` |
| Custom commands *(your organization's own — see [CUSTOM-COMMANDS.md](CUSTOM-COMMANDS.md))* | `custom <name>` *(run)* |
| Everyday / singletons | `summary`, `health-check`, `logs-viewer`, `config`, `apply`, `where`, `kill-processes`, `update-commands`, `remove-user`, `purge`, `purge-and-reinstall` |

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

## `seed python-list [--json]`

Lists every base Python interpreter installed via `seed python`, showing
the short tag, the real versioned directory it points to, which one is the
default used by `seed venv`, and flags any alias whose target directory has
gone missing (e.g. if it was deleted by hand). `--json` prints the same
data as machine-readable JSON instead — see
[Scripting & automation](#scripting--automation).

```
seed python-list
```
```
Base Python interpreters in ~/seedling/python/base:
  311      -> cpython-3.11.9-linux-x86_64-gnu
  312      -> cpython-3.12.4-linux-x86_64-gnu  (default for `seed venv`)
```

## `seed remove-python <tag> [-y] [--preview] [--non-interactive]`

Deletes a base Python **and every venv that was built from it** — venvs
can't function without the interpreter they were created against, so this
cascades rather than leaving them broken.

- Detects dependent venvs by reading the `home` field out of each venv's
  `pyvenv.cfg` and checking whether it resolves inside the base Python's
  directory.
- Lists exactly what it's about to delete (the base, plus each dependent
  venv by name) before asking for confirmation, unless `-y`/`--yes`.
  `--preview` shows the same list and exits without deleting anything;
  `--non-interactive` refuses to prompt and aborts instead of waiting — see
  [Non-interactive mode & previews](DESIGN.md#non-interactive-mode--previews).
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

## `seed venv-list [--json]`

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

`--json` emits the same venvs as data, with the `python_executable` path for
each. The payload is byte-identical to the `venvs` array in `seed summary
--json` — one definition of "a venv, as data", so a consumer never has to
learn two shapes.

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

## `seed run [-n <venv>] -- <command> [args...]`

Runs one command inside a venv **without activating anything**. This is the
non-interactive sibling of `seed activate`: a Makefile recipe, a CI step and
an AI agent each get a fresh process per command and have no shell to
mutate, so `activate` can't help them.

```
seed run -- python -V
seed run -n myproject -- pytest -q
```

Which venv it uses, most specific first:

1. `-n/--venv <name>`, when you say outright. A name that doesn't resolve is
   an error — never a silent fallback to a different environment.
2. `VIRTUAL_ENV` — the venv active in this shell, the same one `seed
   install` would install into.
3. `default_venv`.

Inside the child it makes exactly the three changes an activate script
makes: sets `VIRTUAL_ENV`, prepends the venv's `bin`/`Scripts` to `PATH`,
and clears `PYTHONHOME`. It is a launcher, not a sandbox — the command has
every bit of reach you do.

The command name is resolved **in the venv**, so `seed run -- python` is the
venv's python and `seed run -- pytest` is the venv's pytest. (This is worth
stating because it doesn't come free: on Windows, `CreateProcess` resolves a
bare command name against the *calling* process's `PATH`, so a naive
implementation sets the environment up correctly and then runs the system
copy inside it.)

Three guarantees worth relying on:

- **The command's exit code is yours, verbatim.** `seed run -- pytest`
  returns what pytest returned.
- **stdout and stderr are the command's, untouched.** The child writes to
  the real file descriptors, so its output does not pass through seedling's
  logging tee and stays byte-exact and pipeable. The invocation is logged;
  the child's output is not, deliberately.
- **It's argv, not a shell.** No pipes, redirection, or glob expansion. Put
  the command after `--` if it starts with a dash. For shell semantics, ask
  for them explicitly: `seed run -- sh -c '...'`.

A command that isn't installed in that venv exits **127**, matching shell
convention.

## `seed which [name] [--json]`

Prints the absolute path to a venv's Python interpreter — and nothing else,
so `$(seed which myproject)` works. Same resolution order as `seed run`.

```
seed which
```
```
/home/you/seedling/python/venvs/myproject/bin/python
```

**stdout carries the path and only the path.** Every diagnostic goes to
stderr, and a venv that can't be resolved is a non-zero exit rather than a
message where a path should be. `--json` adds the surrounding facts:

```
seed which myproject --json
```
```json
{
  "schema": 1,
  "found": true,
  "name": "myproject",
  "path": "/home/you/seedling/python/venvs/myproject",
  "python_executable": "/home/you/seedling/python/venvs/myproject/bin/python",
  "bin_dir": "/home/you/seedling/python/venvs/myproject/bin",
  "source": "argument"
}
```

`source` is which rule answered — `argument`, `VIRTUAL_ENV`, or
`default_venv`. Under `--json` a failure is also JSON (`"found": false` with
an `error`), so a consumer that always parses stdout never has to special-case
it. The exit code is still 1.

Scope is venvs only. For base interpreters, apps, tools or anything else,
`seed summary --json` already answers the broader question.

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

## `seed auto-activate [True|False]`

Turns **auto-activation of the default venv in new shells** on or off. This
is separate from *which* venv is the default (`seed venv-default`): it decides
*whether* that venv activates automatically when you open a terminal.

- With `True` / `False` (case-insensitive): sets it. Existing shells are
  unaffected — open a new terminal to see the change.
- With no argument: shows the current state.
- Turning it off **leaves `default_venv` set** — `seed activate` still works,
  and turning it back on resumes activating the same venv.

Sugar for the `auto_activate` setting (`seed config set auto_activate
true|false`); on by default. The shell hook honours it without launching
seed-cli — it detects the disabled state with a plain `grep` of
`settings.json`, which also lets it skip the startup seed-cli call entirely
when auto-activation is off.

```
seed auto-activate            # show current state
seed auto-activate False      # stop auto-activating in new terminals
seed auto-activate True       # resume
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

## `seed package-list [--json]`

Direct passthrough to `uv pip list` for the active venv. Anything after
`package-list` is forwarded to `uv pip list` untouched (e.g. `--outdated`).
Same `VIRTUAL_ENV` warning as `install`/`uninstall` — though under `--json`
that note goes to stderr, so stdout stays parseable.

`--json` is translated to uv's own `--format json`, so you don't have to
remember which layer you're talking to; the output is uv's, unwrapped. An
explicit `--format` is left alone.

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

## `seed tool <command> [args...]`

Runs an installed conda-forge tool **without needing it on PATH or a fresh
terminal** — `seed tool gh pr create`, `seed tool rg TODO`. seedling runs the
tool by its exact path (via `micromamba run`), inheriting your terminal, so
interactive prompts, colour, and pagers all behave normally, and the tool's
own exit code is passed back.

This is the convenient, always-works counterpart to the PATH launchers: the
launchers let *other* programs and scripts find `gh`/`rg` by bare name and are
nice for heavy interactive use, but they need a new terminal (and a shell that
has seedling's hook). `seed tool <command>` works the moment the tool is
installed.

Everything after the command name is passed straight through untouched. Run
`seed tool` with no arguments to list the available commands.

```
seed tool gh auth login
seed tool rg "def install" src
```

## `seed app-install <name>[==version] [--reinstall] [-y] [--non-interactive]`

Installs a **Python application from PyPI into its own isolated
environment** — Spyder, JupyterLab, httpie: things you *run* rather than
import, whose dependency trees you don't want inside a project venv.

Three commands install software, split by where it comes from:

| Command | Source | Lands in |
|---|---|---|
| `seed install` | PyPI, **into the active venv** | that venv |
| `seed app-install` | PyPI, **its own venv** | `extensions/apps/<name>/` |
| `seed tool-install` | conda-forge (not Python) | `system/conda/envs/<name>/` |

Backed by `uv tool install`, so the environment and the command launchers
are uv's own work; seedling just points it at the right directories and
keeps `package_index` / `ca_cert` applied, so this works on an internal
index or fully offline exactly like `seed install`.

- Launchers land in `~/seedling/system/shims`, which the shell hook puts on
  PATH — open a new terminal to run them by name.
- Pin with `==`: `seed app-install spyder==6.1.5`.
- `--reinstall` forces a fresh install of something already present.
- `-y`/`--yes` skips the "install this now?" confirmation; `--non-interactive`
  refuses to prompt and aborts instead — see
  [Non-interactive mode & previews](DESIGN.md#non-interactive-mode--previews).
- The app's environment is **separate from seed-cli's own** (`system/tool`),
  so `uv tool` operations on your apps can never touch the running CLI.

```
seed app-install spyder
seed app-install jupyterlab
```

## `seed app-list`

Lists installed applications and their versions.

```
seed app-list
```
```
Applications in ~/seedling/extensions/apps:
  spyder  [6.1.5]
```

## `seed app-remove <name> [-y]`

Removes an application: its environment and its launchers. Supports
`--preview`. Uses `uv tool uninstall`, falling back to deleting the tree so
a half-installed app that uv no longer recognizes is still removable.

**It removes the application, not what the application put in your venvs.**
`seed spyder`, for instance, installs `spyder-kernels` into whichever venv
it was pointed at; `seed app-remove spyder` leaves that alone. This is
deliberate — undoing it would mean a `remove-*` command reaching into a
venv to change packages you may now depend on, and in Spyder's case
deciding whether to restore the `ipykernel` version it had displaced.
Leaving one small, harmless package behind is the milder outcome. Remove it
yourself if you want to:

```
seed activate myproject
seed uninstall spyder-kernels
```

```
seed app-remove spyder
```

## `seed tool-install <name>[=version]`

Installs a **command-line tool from conda-forge** — the things that aren't
Python packages and so aren't `seed install`-able: `ripgrep`, `pandoc`,
`ffmpeg`, `gh`, compilers, and so on.

This is seedling's *second* engine. `seed install` is uv (the PyPI world);
`seed tool-install` is [micromamba](https://mamba.readthedocs.io), fetched
once into `system/bin` the first time you use it (or dropped there as a
vendored binary for an offline install). Each tool gets its own isolated
environment, and seedling writes a small launcher for every command the tool
provides into a directory the shell hook puts on your PATH — so the tool runs
as a bare command in a new terminal.

Packages come from **conda-forge only** — the community channel, which is
distinct from Anaconda's `defaults` and its commercial terms (see
[Licensing](LICENSING.md)). Point `conda_channel` at an internal mirror or a
local directory for a proxied or air-gapped network.

- Pin a version with `=`: `seed tool-install ripgrep=14.1.0`.
- The command name is often not the package name (installing `ripgrep` gives
  you `rg`); seedling prints what it exposed.
- Open a new terminal afterward so the tool is on PATH.

```
seed tool-install ripgrep
seed tool-install pandoc=3.2
```

## `seed tool-list`

Lists the conda-forge tools you've installed and the command(s) each provides.

```
seed tool-list
```
```
conda-forge tools:
  ripgrep  ->  rg   (ripgrep)
  pandoc   ->  pandoc   (pandoc=3.2)
```

## `seed tool-remove <name> [-y]`

Removes a conda-forge tool: its environment, its PATH launchers, and its
record. Prompts for confirmation first (skippable with `-y`/`--yes`), like
every other `remove-*` command, and supports `--preview` to see exactly what
would go without touching anything.

```
seed tool-remove ripgrep
seed tool-remove ripgrep --preview
seed tool-remove ripgrep -y
```

## `seed download-tool <name>[=version]... [--dest <dir>]`

The conda-forge counterpart of `download-whl`: on a connected machine, resolve
a tool **and all its dependencies** and write them into a local **conda
channel** — a directory you carry to an air-gapped machine (or a share) and
install from offline.

```
(connected)  seed download-tool ripgrep pandoc
(copy the ./conda-channel folder to the offline machine or a share)
(offline)    seed config set conda_channel <that-folder>
             seed tool-install ripgrep
```

seedling solves the request with micromamba, downloads each package
(checksum-verified), and synthesizes the channel's `repodata.json` from the
solve — so no `conda index` or network is needed on the offline side. When
`conda_channel` points at a local folder, `tool-install` runs fully offline
automatically.

Lands in `./conda-channel` unless you pass `--dest`. Pin versions with `=`
(`seed download-tool pandoc=3.2`).

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

## `seed remove-venv <name> [-y] [--preview] [--non-interactive]`

Deletes a single venv from `~/seedling/python/venvs`. Force-closes
Python/VS Code processes first (see `seed kill-processes`) so a running
interpreter or open file inside the venv can't block deletion. Warns (but
doesn't block) if the target looks like the currently active venv
(`VIRTUAL_ENV` matches its path) — it'll be force-closed along with
everything else, and your shell deactivates it automatically once it's
gone (see [Why `seed` is a shell function](GUIDE.md#why-seed-is-a-shell-function)).
Prompts for confirmation unless `-y`/`--yes`; `--preview` shows what would
be deleted without deleting it; `--non-interactive` refuses to prompt and
aborts instead — see
[Non-interactive mode & previews](DESIGN.md#non-interactive-mode--previews).

Deletion itself uses a retrying, defensive helper shared by every
`remove-*`/`purge` command — see
[Why deletion is so defensive](DESIGN.md#why-deletion-is-so-defensive)
for the bug this fixes and how.

```
seed remove-venv myproject
seed remove-venv myproject -y
```

## `seed remove-venv-all [-y] [--preview] [--non-interactive]`

Deletes **every** venv under `~/seedling/python/venvs`, with the same
process-closing behavior as `seed remove-venv`. Lists them all before
asking for confirmation (skippable with `-y`); `--preview` lists them and
exits without deleting; `--non-interactive` refuses to prompt and aborts
instead — see
[Non-interactive mode & previews](DESIGN.md#non-interactive-mode--previews).

```
seed remove-venv-all
```

## `seed vscode [path] [--reinstall] [--no-open] [-y]`

Opens VS Code at `path` (defaults to the current directory), installing a
fully portable copy into `~/seedling/extensions/vscode/app` first if none
exists — though a default install already did that up front (see
`SEEDLING_AUTO_VSCODE` in `seedling.conf`), so normally this just opens.
`--no-open` installs/verifies without opening a window (what the
installer's default setup uses).

- **The first-time install asks first.** With nothing installed yet, this
  command would otherwise pull ~300 MB without warning, which is expensive
  on a metered or locked-down connection. It prints the size and prompts;
  declining exits 0 and tells you how to install later. Once VS Code *is*
  installed there is no prompt — opening stays instant.
- `-y`/`--yes` (or `SEEDLING_YES=1`) skips that prompt, and
  `--non-interactive` (or `SEEDLING_NONINTERACTIVE=1`) skips the install
  rather than waiting for input. `--reinstall` is exempt: asking for a
  reinstall already says you want the download.
- `seed vscode-repo` shares the same gate and the same flags, since it can
  trigger the same first-time download.

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
  - `python.venvPath` set to `~/seedling/python/venvs`, so every `seed venv`
    shows up in VS Code's interpreter picker automatically
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

## `seed vscode-repo <name> [-y]`

Opens a cloned repo in VS Code — installing VS Code first if it isn't
already (same one-time setup as `seed vscode`). Shares the same CLI-entry-
point, detached-process opening logic as `seed vscode`, and the same
first-time download prompt (with the same `-y` / `--non-interactive`
flags) — reaching the editor from a repo shouldn't cost 300 MB any more
quietly than reaching it directly.

```
seed vscode-repo some-project
```

## `seed spyder [path] [--venv <name>] [--no-open] [-y] [--non-interactive]`

Installs (once) and opens **Spyder**, the scientific Python IDE — the
variable explorer, IPython console and plots pane that people coming from
MATLAB or R usually want. Same shape as `seed vscode`, and it asks before
its first-time ~200 MB download in exactly the same way.

`-y`/`--yes` skips the first-run "install this ~200 MB?" prompt;
`--non-interactive` (or `SEEDLING_NONINTERACTIVE=1`) refuses to prompt at
all and aborts instead — the same two shared confirmation knobs every
consequential-but-not-destructive prompt in seedling honors (see
[Non-interactive mode & previews](DESIGN.md#non-interactive-mode--previews)).

Underneath it's `seed app-install spyder`, but the command exists because
three things have to be arranged that a plain application install can't
know about:

- **Its settings stay inside seedling.** Spyder would otherwise write to
  `~/.config/spyder-6` or `%APPDATA%`; seedling points it at
  `~/seedling/extensions/spyder-config` (`--conf-dir`), so `seed purge`
  still leaves nothing behind.
- **It's pointed at a venv.** Unlike VS Code, whose Python extension
  discovers environments itself, Spyder has to be told. seedling writes the
  interpreter into its `spyder.ini`, **merging** rather than overwriting, so
  your own Spyder settings survive.
- **`spyder-kernels` is installed into that venv**, pinned to the minor
  series matching the installed Spyder (read from Spyder's own environment,
  never hardcoded). Without a compatible version, Spyder's console refuses
  to connect — the classic Spyder failure.

### Which venv it uses

Most specific wins:

1. **`--venv <name>`** — when you say outright. Naming a venv that doesn't
   exist is an error, not a fall back to a different one.
2. **The venv active in this shell** (`VIRTUAL_ENV`) — so `seed activate
   analysis && seed spyder` gives you that environment, the same way
   `seed install` targets it. Any active venv counts, seedling-managed or
   not.
3. **`default_venv`** — so it still works from a shell with nothing
   activated.

Because the kernel is prepared *before* Spyder launches, switching venvs and
reopening switches the console with it. With nothing active and no default,
Spyder still opens but runs on its own interpreter and won't see your
packages; it says so.

> **Close Spyder before switching venvs.** A running instance won't pick up
> the new interpreter, and Spyder rewrites its own config on exit — so it can
> overwrite the setting seedling just wrote.

- Installing `spyder-kernels` may **downgrade `ipykernel`** in that venv:
  it requires `ipykernel<7`, and seedling's default venv packages install a
  newer one, so this happens on a stock venv. It's required for Spyder's
  console to work at all, and seedling says so explicitly when it happens —
  including that anything else in that venv (Jupyter, VS Code notebooks)
  gets the older version too. The cap is `spyder-kernels`', not Spyder's,
  and upstream is already relaxing it (3.2 raises it to `<7.3`); because
  seedling reads the required version from Spyder's own environment rather
  than pinning one, that fixes itself when it ships.

> **x86_64 only.** Spyder comes from PyPI, and PyQt5's Qt payload publishes
> no arm64 wheels — so this can't work on Apple Silicon or ARM Linux. There,
> use the conda-forge build instead: `seed tool-install spyder`. `seed
> spyder` says exactly that rather than failing with a dependency error.

```
seed spyder                      # the active venv, else the default
seed activate analysis
seed spyder                      # now runs in 'analysis'
seed spyder --venv scratch       # or name one outright
```

## `seed spyder-repo <name> [--venv <name>] [-y] [--non-interactive]`

Opens a cloned repo as a **Spyder project** (`--project`), the natural
counterpart to `seed vscode-repo`. Same install-if-needed behavior, the
same first-run prompt (and the same `-y`/`--non-interactive` knobs for it),
and the same [venv resolution](#which-venv-it-uses) as `seed spyder` —
`--venv <name>` names one outright, otherwise the active venv or
`default_venv` is used.

```
seed spyder-repo some-project
seed spyder-repo some-project --venv analysis
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

## `seed repo-open [name]`

Opens a cloned repo in the **operating system's file manager** (Explorer
on Windows, Finder on macOS, your desktop's default elsewhere). With no
name, opens `~/seedling/repo` itself. For opening in VS Code, use
`seed vscode-repo`.

```
seed repo-open some-project
seed repo-open
```

## `seed repo-install <name>[extras] [--venv NAME]`

Installs a cloned repo's dependencies into a venv — the active one by
default, or the one you name:

- If the repo has a `pyproject.toml`, runs `uv pip install -e <repo>`
  (editable install — changes you make in the cloned repo take effect
  immediately without reinstalling, which is what you want when actively
  developing against it).
- Otherwise, if it has a `requirements.txt`, runs
  `uv pip install -r <repo>/requirements.txt`.
- If neither file exists, fails with a message rather than guessing.
- `name[extra,...]` selects the repo's optional dependencies, same spelling
  as a package spec: `seed repo-install plotpress[gui]` installs
  `uv pip install -e <repo>[gui]`. Extras need a `pyproject.toml` to select
  from — asking for them on a `requirements.txt`-only repo is an error, not
  a silent plain install.
- `--venv NAME` (`-n`) installs into that venv whatever this shell has
  active, and fails if there's no such venv rather than falling back to
  another one. Without it, the same `VIRTUAL_ENV` warning as `seed install`
  if nothing is active.

```
seed activate myproject
seed repo-install some-project
seed repo-install some-project[gui]
seed repo-install some-project[gui,dev] --venv analysis
```

A profile can declare the same thing for a fleet — see
[`[[repo]] install`](PROFILES.md#reference).

## `seed remove-repo <name> [-y] [--preview] [--non-interactive]`

Deletes a cloned repo from `~/seedling/repo`. Same process-closing
behavior as `seed remove-venv` before deletion, and the same confirmation
prompt (skippable with `-y`), `--preview`, and `--non-interactive` — see
[Non-interactive mode & previews](DESIGN.md#non-interactive-mode--previews).

```
seed remove-repo some-project
```

## `seed custom [name] [args...]`

Runs an organization's own **custom command** — full details, including how
to define one, are in **[CUSTOM-COMMANDS.md](CUSTOM-COMMANDS.md)**.

Every command is one `[[command]]` entry in `custom-commands.toml`: either
`run = [...]` (a fixed argv, an optional venv) for the simple case, or
`script = "..."` (a `.py`/`.sh`/`.ps1` file next to the TOML file) for
anything that needs real logic or to chain several `seed` subcommands
together — a script orchestrates by shelling out to `seed` itself, the same
thing `seed apply` already does internally, so there's no special API to
learn.

Everything after the command's own name is passed straight through. Run
`seed custom` with no arguments to list what's configured. A command can
also opt into running as bare `seed <name>` — see
[Making a command top-level](CUSTOM-COMMANDS.md#making-a-command-top-level);
a built-in `seed` command always wins any name collision.

```
seed custom lint
seed custom lint --fix
seed custom
```

A configured `startup_commands` list runs these same commands automatically
in every new shell — see [CUSTOM-COMMANDS.md#running-commands-at-
startup](CUSTOM-COMMANDS.md#running-commands-at-startup).

## `seed kill-processes [name] [--system] [-y] [--preview] [--non-interactive]`

An escape hatch for stuck scripts or a frozen VS Code window. **Scoped to
seedling by default** — bare `seed kill-processes` only force-closes
processes belonging to the seedling tree (decided by executable path,
command line, or working directory under `~/seedling`, never by name), on
the reasoning that "something of mine is stuck" shouldn't close a
colleague's editor or an unrelated job. Widening the blast radius takes an
explicit flag:

- `seed kill-processes` (no arguments) — seedling's own processes only.
  Prompts for confirmation unless `-y`/`--yes`.
- `seed kill-processes --system` — force-closes every process matching common
  Python interpreter names (`python`, `python3`, `python3.8`-`3.14`,
  `pythonw`) and VS Code/Electron process names (`code`, `Code`,
  `Code Helper*`, `Electron`) **on the whole machine**, seedling-started or
  not. Always prompts unless `-y`.
- `seed kill-processes <name>` — force-closes every process with that
  **exact** name, machine-wide (e.g. `seed kill-processes node`). On
  Windows, `.exe` is appended automatically if you don't include it. Always
  prompts unless `-y`.

`--preview` lists exactly what would be closed without closing anything;
`--non-interactive` refuses to prompt and aborts instead — see
[Non-interactive mode & previews](DESIGN.md#non-interactive-mode--previews).

Implementation notes:
- Uses only OS-builtin tools: `pgrep -x` + `kill`/`os.kill` on macOS/Linux,
  `taskkill /F /IM` on Windows. No third-party dependency like `psutil`.
- Always excludes seedling's own running process (and its parent) from the
  kill list, so it can't terminate itself mid-cleanup — this matters
  because on macOS/Linux, `seed-cli`'s own process image is literally a
  `python3.x` process (its shebang execs the interpreter directly).
- The underlying `kill_python_and_vscode()` helper (the `--system` sweep) is
  reused by `seed remove-venv(-all)`, `seed remove-python`, `seed remove-repo`,
  `seed remove-user`, and `seed purge` — anything that deletes files is
  preceded by this same sweep, to avoid "file in use" failures.

```
seed kill-processes                # just seedling's own stuck processes
seed kill-processes --system
seed kill-processes node -y
```

## `seed update-commands`

The **only** thing that updates the `seed` command itself after initial
install. See [The update model](GUIDE.md#the-update-model) for the full
explanation. In short:

> **Not what you want if your venvs/packages/repos are out of date with a
> [deployment profile](PROFILES.md)** — that's [`seed apply`](#seed-apply-profile---preview---force),
> a completely separate command. This one only ever touches `seed`'s own
> code; it never creates, installs, or removes anything `seed apply`
> manages, and `seed apply` never pulls a newer `seed`.

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

**It also tells you if `seedling.conf` changed underneath you.** Settings
(`seed config`'s values, like `package_index` or `venv_default_packages`)
are seeded from `seedling.conf` once, at install time, and never
re-applied automatically — an org changing a share path or an index later
previously left every existing machine silently out of sync, discoverable
only when something broke. After refreshing, this command re-reads the
(now current) `seedling.conf` and reports anything it now sets
differently than what's actually configured here, with the exact
`seed config set` to apply it:

```
The organization's seedling.conf now sets these differently than what's
configured on this machine (settings are only ever seeded at install
time, never re-applied automatically):
  package_index: 'https://old.example/simple' -> 'https://new.example/simple'
    seed config set package_index "https://new.example/simple"
```

Deliberately a **report, not an apply** — a value you set by hand with
`seed config set` is a real customization, and this must never silently
overwrite it. `update_source`, `profile`, and `custom_commands` (file
paths an installer resolves relative to its own invocation, sometimes
copying) aren't covered by this check; those still need a person to
notice and re-run `seed config set`.

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

## `seed remove-user [-y] [--preview] [--non-interactive]`

Deletes `~/seedling` in its entirety — every base Python, every venv, VS
Code and all its extensions/settings, every cloned repo, uv itself,
everything. Prompts for confirmation (`yes` typed exactly) unless
`-y`/`--yes` is passed; `--preview` shows what would be deleted without
deleting it; `--non-interactive` refuses to prompt and aborts instead —
see [Non-interactive mode & previews](DESIGN.md#non-interactive-mode--previews).

Before deleting, it first force-closes every Python and VS Code process on
the machine (the same sweep as `seed kill-processes --system`, with the same
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

## `seed purge [-y] [--preview] [--non-interactive]`

Supports the same `-y`/`--preview`/`--non-interactive` trio as
`seed remove-user` (see
[Non-interactive mode & previews](DESIGN.md#non-interactive-mode--previews)).
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
whether to reinstall from the public repo (`github.com/jrvannucci/seedling`) and
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

```json5
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

## `seed health-check [--json]`

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

`--json` emits the same checks as data — `{schema, home, healthy, failures,
warnings, checks[]}`, each check being `{status, area, detail}`. The
rendering changes; the verdict doesn't, and the exit code is the same either
way.

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

## `seed apply [profile] [--preview] [--force]`

Brings this machine in line with a [deployment profile](PROFILES.md) — the
interpreters, named venvs and their packages, repos, and settings an
organization has standardized on.

> **Not what you want if `seed` itself is out of date** — that's
> [`seed update-commands`](#seed-update-commands), a completely separate
> command. This one only ever touches your environment (interpreters,
> venvs, packages, repos); it never changes `seed`'s own code, and
> `update-commands` never touches any of what this one manages.

- With no path, uses the profile recorded at install time (the `profile`
  setting), else `seedling-profile.toml` in the current directory.
- **Idempotent.** Applying twice changes nothing the second time, which is
  what makes it usable both as the install-time provisioning step and as the
  way a fleet picks up later changes to the standard.
- **Never destroys.** An existing venv is left exactly as it is. `--force`
  installs the profile's *missing* packages into it; nothing is ever removed
  or recreated. Deleting is `seed remove-venv`, run on purpose. An existing
  clone is likewise never pulled, only cloned when absent — though a repo the
  profile installs is installed again into any of its venvs that doesn't have
  it, so rebuilding a venv brings the repo back with it.
- **Settings are the exception**: a key in the profile's `[config]`, and the
  default venv, are rewritten whenever this machine's value differs. See
  [what apply will and won't do](PROFILES.md#what-apply-will-and-wont-do)
  for the full per-declaration table.
- `--preview` prints the plan and exits without changing anything.
- Exit codes: `0` applied or already current, `1` a step failed (it names
  which), `2` the profile itself is invalid.

Every step is an ordinary `seed` command underneath (`python`, `venv`,
`install`, `repo-clone`, `repo-install`, `config set`), so a profile can only
do what you could have done by hand.

```
seed apply --preview
seed apply
seed apply ./team-profile.toml --force
```

---

## `seed config [get <key> | set <key> <value> | unset <key>]`

Views and changes seedling's own settings, stored in
`~/seedling/system/config/settings.json`. Bare `seed config` lists every
setting with its current value and an explanation. The keys:

- `default_base` — the base Python tag `seed venv` builds from when
  `--python` isn't given. Set automatically by your first `seed python`.
- `default_venv` — a venv name that **every new shell auto-activates** on
  startup. Unset means no auto-activation. (Existing shells are
  unaffected; open a new terminal to see it.)
- `auto_activate` — whether new shells auto-activate `default_venv`
  (true/false, default true). Toggle with
  [`seed auto-activate True|False`](#seed-auto-activate-truefalse); when
  false, the default venv stays set but isn't activated automatically.
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
- `conda_channel` — where `seed tool-install` fetches conda-forge
  command-line tools from (default: `conda-forge`). A URL or local
  directory for an internal mirror or an offline network.
- `shared_root` — the directory holding per-user seedling homes, recorded
  automatically when `SEEDLING_HOME_DIR` used a `{user}` token. Only set on
  shared multi-user installs; enables the `admin-*` commands.
- `native_tls` / `ca_cert` — HTTPS trust for corporate-CA internal hosts:
  the OS trust store, or a PEM bundle (normally installed automatically
  from `vendor/certs/`). Applied to uv, git, and seedling's own downloads
  on every command.
- `profile` — the [deployment profile](PROFILES.md) `seed apply` uses when
  given no path. Recorded at install time from `SEEDLING_PROFILE`.
- `custom_commands` — path to the TOML file declaring your organization's
  own [custom commands](CUSTOM-COMMANDS.md). Recorded at install time from
  `SEEDLING_CUSTOM_COMMANDS`.
- `startup_commands` — custom command names run automatically, in order, by
  every new shell (list; takes comma-separated input, `&&` chains names
  within one entry so a failure stops just that chain). Recorded at install
  time from `SEEDLING_STARTUP_COMMANDS`. See [CUSTOM-COMMANDS.md#running-
  commands-at-startup](CUSTOM-COMMANDS.md#running-commands-at-startup).
- `vscode_flavor` — which editor build `seed vscode` installs:
  `microsoft` (default) or `vscodium`. Affects the **next** install; use
  `seed vscode --reinstall` to switch an existing one.
- `extension_gallery` — the extension registry base URL, when it shouldn't
  be the flavor's own default (e.g. an internal Open VSX mirror).
- `vscode_extensions` — the extensions installed into a fresh editor.
  Takes comma-separated input; an empty list installs none. Unset means
  the starter kit for the configured flavor.

The three editor settings are usually deployment-wide rather than personal;
see [the deployment guide](DEPLOYMENT.md#which-vs-code-build)
for what they're for and the licensing tradeoff they encode.

`seed config get <key>` prints just the value (nothing at all when unset),
so it's script-friendly. `unset` resets a key to its built-in default.

```
seed config
seed config set default_venv myproject
seed config set update_source https://github.mycompany.com/tools/seedling.git
seed config set update_source "S:\shared\seedling"
seed config set venv_default_packages "ipython,ruff,requests"
seed config set vscode_flavor vscodium
seed config set vscode_extensions "ms-python.python,charliermarsh.ruff"
seed config unset default_venv
```

---

# Scripting & automation

Most of seedling is written for a person at a terminal. This is the subset
written for everything else — Makefiles, CI steps, provisioning scripts, and
AI coding agents — collected in one place because that audience arrives
looking for it, not for a particular noun.

**Get an interpreter without a shell.** `seed activate` mutates the calling
shell, which is useless to a caller that gets a fresh process each time. Use
[`seed which`](#seed-which-name---json) to resolve the interpreter, or
[`seed run`](#seed-run--n-venv----command-args) to execute in the venv
directly:

```sh
"$(seed which myproject)" -m mytool     # explicit interpreter
seed run -n myproject -- pytest -q      # or let seed set up the env
```

`seed run` passes the child's exit code through verbatim and leaves its
stdout and stderr byte-exact — the child writes to the real file
descriptors, so its output never passes through seedling's logging tee.

**Read state as data.** `--json` is available on every read command, and the
shapes agree with each other:

| Command | Payload |
|---|---|
| `seed summary --json` | everything: tooling, interpreters, venvs, repos, settings |
| `seed venv-list --json` | the `venvs` array, identical to summary's |
| `seed python-list --json` | the `pythons` array, identical to summary's |
| `seed which <name> --json` | one venv, plus which rule resolved it |
| `seed health-check --json` | every check as `{status, area, detail}` |
| `seed package-list --json` | uv's own `pip list --format json`, unwrapped |

Every payload carries a `schema` integer. It bumps only when a field
**changes meaning or is removed** — never when one is added — so pinning to
a schema version is safe.

**Never block on a prompt.** `--non-interactive` makes a command that would
ask a question abort instead of waiting, and `-y`/`--yes` pre-answers it.
`SEEDLING_NONINTERACTIVE=1` and `SEEDLING_YES=1` set the same two things for
a whole session, which is usually what you want in CI:

```sh
export SEEDLING_NONINTERACTIVE=1
export SEEDLING_YES=1
```

Without `-y`, a `--non-interactive` command that needs confirmation exits
non-zero and says so — it never guesses.

**Concurrency is handled.** Commands that mutate a venv (`install`,
`uninstall`, `venv`, `remove-venv`) take an exclusive lock on that venv for
the duration, so parallel CI jobs or several agents on one machine queue
instead of corrupting a shared `site-packages`. Locks are per-venv, so
unrelated environments never wait on each other; a command that waits says
so on stderr, and one that waits too long fails rather than proceeding
unsafely. See [DESIGN.md](DESIGN.md#concurrent-commands).

**Set up an environment declaratively.** A [deployment
profile](PROFILES.md) lists the interpreters, venvs, packages and repos a
machine should end up with, and `seed apply` reaches that state
idempotently — the right primitive for provisioning a fresh machine or
bringing a stale one back in line.

**Exit codes.** `0` success, `1` failure, `127` from `seed run` when the
command isn't in the venv, `130` on interrupt. `seed health-check` exits `1`
when any check FAILs (warnings don't count).
