# Custom commands

**Let your organization add its own verbs to `seed`.** A team's own shortcut
— `seed lint`, `seed data-stack`, `seed bootstrap` for a brand-new project
venv — without it becoming an upstream seedling feature, and without asking
every user to remember a script's full path.

A [deployment profile](PROFILES.md) says *what environment `seed apply`
builds*. Custom commands say *what extra verbs `seed` itself understands*.
They're separate mechanisms because they're read differently: a profile is
only consulted when someone runs `seed apply`; custom commands have to be
resolved on essentially every `seed custom ...` (and, for `toplevel` ones,
every bare `seed <name>`) invocation.

**One file, `custom-commands.toml`, is the whole of it.** Every command —
whether it's a fixed one-liner or something with real logic — is one
`[[command]]` entry. There's no second, directory-scanned mechanism to learn:
if you can read the TOML file, you know every custom command the
organization has, what it does, and whether it's top-level, without opening
anything else.

A command is exactly one of two shapes:

- **`run = [...]`** — a fixed argv, optionally against a named `venv`. Zero
  code to write. Right for "run this program" or "run this program in this
  venv."
- **`script = "..."`** — a `.py`, `.sh`, or `.ps1` file, resolved relative to
  wherever `custom-commands.toml` itself lives (ship it alongside, no
  separate directory setting to keep in sync). Right for anything with real
  logic, a companion data file, or that needs to chain more than one `seed`
  operation together (e.g. "create a venv, then run something in it").

---

## Contents

- [The `run` shape](#the-run-shape)
- [The `script` shape](#the-script-shape)
- [Worked examples](#worked-examples)
- [Making a command top-level](#making-a-command-top-level)
- [Running commands at startup](#running-commands-at-startup)
- [Distributing it](#distributing-it)
- [Reference](#reference)

---

## The `run` shape

```toml
# custom-commands.toml
[[command]]
name = "lint"
run = ["ruff", "check", "."]
description = "Lint the current project"

[[command]]
name = "sync"
run = ["python", "-m", "myorg_tools.sync"]
venv = "dev"
description = "Sync data using the myorg_tools package installed in 'dev'"
```

- `name` — what you type after `seed custom`. Letters, digits, `.`, `_`,
  `-`; must start with a letter or digit.
- `run` — the argv to execute. A list of strings, **never a shell string**
  (no `shell=True`, no `&&`, no globbing) — the same stance `seed run`
  already takes. Covers running a plain program AND running a distributed
  Python function that's wrapped as a runnable module (`python -m
  pkg.module`) or an installed console-script entry point.
- `venv` (optional, `run` only) — run inside this **named** venv (resolved
  strictly: a name that doesn't exist is an error, never a silent
  fallback). Omit it and the command runs in the ambient environment —
  whatever's already active in the calling shell, which is exactly what
  makes `run = ["seed", "install", ...]` with no `venv` mean "into the
  currently activated venv" (see [worked examples](#worked-examples)).
- `description` (optional) — shown in `seed custom` and `seed help`.
- `toplevel` (optional, default `false`) — see [making a command
  top-level](#making-a-command-top-level).

Trailing arguments are appended to `run` verbatim: `seed custom lint --fix`
runs `ruff check . --fix`.

---

## The `script` shape

```toml
[[command]]
name = "quote"
script = "scripts/quote.py"
description = "Print a random quote"

[[command]]
name = "bootstrap"
script = "scripts/bootstrap.py"
description = "Set up this user's project venv from scratch"
toplevel = true
```

`script` names a `.py`/`.sh`/`.ps1` file, resolved relative to the directory
`custom-commands.toml` itself is in — an absolute path is left alone. `.py`
is the recommended default: it's the one extension that runs identically on
every platform, because seedling runs it with **its own interpreter**
(`sys.executable`) — whatever seed-cli itself is running on right now,
guaranteed present, no dependency on a system `python3` existing. A `.sh`/
`.ps1` still works for something that's fundamentally a shell one-liner or
needs OS-specific behavior.

`venv` doesn't apply to a `script` entry (it's a validation error to set
both) — a script already runs in seed-cli's own interpreter/shell, and
reaches a venv itself, on its own terms, via `seed run -n <venv> -- ...`.

**Orchestration scripts don't get a special API.** `seed` is already a full,
composable CLI — a script chains operations by shelling out to it, the
same thing `seed apply` already does internally:

```python
# scripts/bootstrap.py
import subprocess, sys

def main(argv):
    subprocess.run(["seed", "venv", "myproj", "--python", "312"], check=True)
    subprocess.run(["seed", "run", "-n", "myproj", "--",
                     "python", "-m", "myorg_tools.setup", *argv], check=True)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
```

Stick to the standard library plus `seed` subprocess calls — these scripts
run in seed-cli's own interpreter, not a project venv, so they were never
meant to `import` project packages directly. (For "run a function that
lives inside packages installed in venv X," use the [`run` shape](#the-run-shape)
with `run = ["python", "-m", "pkg.module"]` and `venv` instead.)

---

## Worked examples

**Install a package set into whatever venv is currently active** — `run`,
and the trick is that it can invoke `seed` itself:

```toml
[[command]]
name = "data-stack"
run = ["seed", "install", "pandas", "numpy", "matplotlib", "scikit-learn"]
description = "Install the standard data-science package set into the active venv"
```

No `venv` key: plain `seed install` already targets whatever's active, so
omitting `venv` here and calling `seed install` *is* "into the currently
activated venv." `seed custom data-stack --upgrade` becomes `seed install
pandas numpy matplotlib scikit-learn --upgrade` — flags fall out for free
from the trailing-args rule.

**Print a random string from a text file, one per line** — `script`,
because it needs real logic (`random.choice`) and a companion data file
resolved relative to the script itself:

```toml
[[command]]
name = "quote"
script = "quote.py"
description = "Print a random quote"
```

```python
# quote.py, next to custom-commands.toml
import random, sys
from pathlib import Path

def main(argv):
    lines = [ln for ln in (Path(__file__).parent / "quotes.txt")
             .read_text(encoding="utf-8").splitlines() if ln.strip()]
    print(random.choice(lines))
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

`quotes.txt` sits right next to `quote.py` and is never mistaken for a
command of its own — only files a `[[command]] script` entry actually names
are ever run.

**Build a new venv for a user, then run a function in it** — `script`
again; see the `bootstrap.py` example above.

---

## Making a command top-level

Most custom commands are reached with `seed custom <name>`. A command can
**also** run as bare `seed <name>` with `toplevel = true` — for `run` and
`script` entries alike.

**Built-in commands always win.** If a `toplevel` name collides with a real
`seed` command (current or, later, a new one seedling ships), the custom
command is silently dropped from the top-level short-circuit — `seed venv`
always means the real thing — but it's never dropped entirely: it stays
reachable via `seed custom <name>`, and the collision is reported the next
time `seed custom` or `seed help` runs, so you notice and rename it. A
custom command can never shadow or break a built-in one.

---

## Running commands at startup

`toplevel` makes a command available in every shell. `startup_commands`
**runs** commands automatically in every shell — for an offline
organization that wants a standard routine (a connectivity check to an
internal mirror, a data sync, a message of the day) to just happen, with
nothing for a user to remember or type:

```
seed config set startup_commands "check-mirror, motd"
```

or set once for a whole fleet in `global.conf` (see
[distributing it](#distributing-it)):

```
SEEDLING_STARTUP_COMMANDS="check-mirror,motd"
```

Each name is looked up exactly the way `seed custom <name>` does, whether
it's `toplevel` or not, and run in the listed order, every time a new shell
opens.

**Chain commands that depend on each other with `&&`**, the same operator
shell scripting already uses for "run the next one only if this one
succeeded":

```
seed config set startup_commands "ensure-venv&&sync-data, motd"
```

`,` still separates independent entries (`motd` here runs regardless of
whether the `ensure-venv&&sync-data` chain succeeded); `&&` *within* one
entry chains its names — `sync-data` only runs if `ensure-venv` exited `0`.
Nothing else has to change to opt in: a bare name with no `&&` is just a
chain of one, so every existing `startup_commands` value keeps meaning
exactly what it always did.

**One seed-cli process runs the lot**, so a five-command routine costs one
startup rather than five — the reason this is viable in *every* shell.

**It is deliberately unconditional.** Unlike `default_venv` auto-activation,
startup commands run whether or not a venv is already active: a connectivity
check or a sync that only ran sometimes would be worse than not having one.

**A failure warns and moves on** to the next entry — never to the rest of a
`&&` chain, and never stopping the shell from opening. A typo in this list
must not lock anyone out of their terminal, so an undeclared name warns once
and is skipped.

## Distributing it

Same shape as a [profile](PROFILES.md#distributing-it): name the file in
[`global.conf`](https://github.com/jrvannucci/seedling/blob/main/global.conf),
distribute the copy of seedling that carries it (and any `script` files
alongside it), and every installer run picks it up automatically:

```
SEEDLING_CUSTOM_COMMANDS="custom-commands.toml"
SEEDLING_STARTUP_COMMANDS="check-mirror,motd"
```

Both are independent and optional. The relative path resolves against the
repo copy being installed from. As with a profile, `custom_commands` is
read fresh from wherever it's configured on every `seed custom`/`seed help`
invocation (no caching) — a conf-sourced path inside the distributed repo
rides along automatically whenever that repo copy is refreshed by `seed
update-commands`, `script` files included, since the whole tree is what
gets refreshed. `startup_commands` is a plain list, recorded once into
`settings.json` the same way, and read by the shell hook (`seed.ps1`/
`seed.sh`) itself, not by `seed-cli` — see [running commands at
startup](#running-commands-at-startup).

**One thing to know about the piped-one-liner install** (`SEEDLING_CUSTOM_COMMANDS`
set as an *environment variable* rather than in `global.conf`): the
installer copies the TOML file's **whole containing directory**, not just
the file, so relative `script` entries and their own companion files
survive — the same thing the conf-distributed form already gets for free
from the source-tree copy. That does mean the directory holding
`custom-commands.toml` should be scoped to just this deployment's files;
point the env var at a dedicated folder, not somewhere with a lot of
unrelated content, since all of it gets copied in.

You can also change either setting on an existing install without a
fleet-wide rollout:

```
seed config set custom_commands ./team-commands.toml
seed config set startup_commands "check-mirror,motd"
```

---

## Reference

| Key | Type | Meaning |
|---|---|---|
| `[[command]] name` | string | **Required.** The invocable name. |
| `[[command]] run` | list of strings | Argv to execute — never a shell string. Exactly one of `run`/`script`. |
| `[[command]] script` | string | A `.py`/`.sh`/`.ps1` file, resolved relative to this TOML file's own directory (or absolute). Exactly one of `run`/`script`. |
| `[[command]] venv` | string | `run` only. Run inside this named venv (strict resolution). Omit for the ambient environment. |
| `[[command]] description` | string | Shown in `seed custom` / `seed help`. |
| `[[command]] toplevel` | bool | Also expose as bare `seed <name>`. Default `false`. |

| Setting | Meaning |
|---|---|
| `custom_commands` | Path to `custom-commands.toml`. Empty/null means none. |
| `startup_commands` | Custom command names (list) run, in order, by every new shell. Empty/null means nothing runs at startup. |

**Validation is strict.** An unknown key, a duplicate name, `run` and
`script` both set (or neither), an empty `run`, a bad `name`, or `venv` set
on a `script` entry rejects the *whole file* with a message naming the
problem — the same reasoning a [profile](PROFILES.md) uses: a typo should
fail once for you, not quietly for each user. Unlike a profile, though, a
broken `custom-commands.toml` only breaks `seed custom` and the `seed help`
group — it can never break an unrelated command like `seed venv`.
