# Deployment profiles

**One file that says what environment your users should end up with.** The
admin writes it, distributes it with seedling, and every user gets the same
interpreters, venvs, packages and repos from the single command they already
run. Later, when the standard changes, they re-run `seed apply` and pick up
the difference.

`seedling.conf` says *where seedling gets things from*. A profile says *what
to set up once seedling works*. They are separate files because they answer
separate questions and are read at different times.

---

## Contents

- [A complete example](#a-complete-example)
- [Installing with your own profile](#installing-with-your-own-profile)
- [Distributing it](#distributing-it)
- [Applying it later](#applying-it-later)
- [What apply will and won't do](#what-apply-will-and-wont-do)
- [Reference](#reference)
- [Offline bundles](#offline-bundles)

---

## A complete example

```toml
# seedling-profile.toml -- the standard environment for the data team.
schema = 1

# Interpreters to install. Omit to use whatever `seed python` picks.
python = ["3.12"]

[[venv]]
name = "dev"
packages = ["ipython", "ruff", "requests"]
default = true              # the venv new shells auto-activate

[[venv]]
name = "analysis"
python = "312"              # pin to a specific base; optional
packages = ["pandas", "numpy", "jupyterlab"]
default_packages = false    # skip venv_default_packages for this one

[[repo]]
url = "https://git.corp/data-team/toolkit.git"
install = true              # also install its dependencies

[config]
vscode_extensions = ["ms-python.python", "charliermarsh.ruff"]
```

Everything is optional. A profile with one `[[venv]]` is a perfectly good
profile.

---

## Installing with your own profile

You don't need to distribute a modified copy of seedling to use a profile.
Point the ordinary one-line installer at a file with the `SEEDLING_PROFILE`
environment variable — this is how an admin can email or publish a single
`.toml` and have people install straight from the public one-liner:

**macOS / Linux:**
```sh
curl -fsSL https://raw.githubusercontent.com/cryocliff/seedling/main/installers/install.sh \
  | SEEDLING_PROFILE=./team.toml sh
```

**Windows (PowerShell):**
```powershell
$env:SEEDLING_PROFILE = "C:\Users\me\Downloads\team.toml"
irm https://raw.githubusercontent.com/cryocliff/seedling/main/installers/install.ps1 | iex
```

Relative paths resolve against the directory you ran the installer from.

Two things happen that are worth knowing:

- **The file is copied into `~/seedling/system/config/profile.toml`.** The
  original might be a downloads folder, a temp file or a mounted share, and
  `seed apply` has to keep working long after that goes away — the same
  reason seedling copies its own source in.
- **A path that doesn't exist stops the install.** This is deliberately
  unlike the [distributed](#distributing-it) case, which warns and falls back
  to the default setup: if you explicitly named a profile and silently got a
  plain environment instead, you wouldn't find out until something you
  expected was missing.

The environment variable wins over any `SEEDLING_PROFILE` in `seedling.conf`,
matching how `SEEDLING_REPO` and `SEEDLING_HOME` already override their conf
equivalents for one run.

---

## Distributing it

Put the file in the copy of seedling you distribute and name it in
[`seedling.conf`](https://github.com/cryocliff/seedling/blob/main/seedling.conf):

```
SEEDLING_PROFILE="seedling-profile.toml"
```

That is the whole handoff. Your users run the same `install.cmd` they would
have anyway, and the installer applies the profile as part of setup — no
extra step, no flags, nothing to explain.

When a profile is set it **replaces** the built-in default setup (a single
`dev` venv), rather than layering on top of it. Otherwise every machine would
carry a `dev` venv you never asked for alongside the ones you declared.

The profile is copied into `~/seedling/system/src` along with the rest of the
source, so `seed apply` keeps working after the share it was installed from
is unmounted, and `seed update-commands` refreshes it.

> If the conf names a profile that isn't there, the installer warns and falls
> back to the default setup rather than failing. A missing profile shouldn't
> brick a fleet's installs.

---

## Applying it later

```sh
seed apply                  # the profile recorded at install time
seed apply ./team.toml      # a specific file
seed apply --preview        # show what would change, do nothing
seed apply --force          # also add missing packages to existing venvs
```

This is what makes a profile a *fleet-management* tool rather than a one-shot
installer input. Add a package, publish the updated profile, tell people to
run `seed apply` — only the difference is acted on, and running it twice
changes nothing the second time.

`seed apply --preview` prints the plan and exits. Use it before rolling a
change out to anyone.

---

## What apply will and won't do

**It will:** install missing interpreters, create missing venvs with their
packages, clone missing repos, and write the settings you declared.

**It will not delete or recreate anything.** A venv that already exists is
left exactly as it is, even if its packages have drifted from the profile —
someone may have installed something they need. `--force` adds the profile's
*missing* packages to an existing venv; it still never removes or rebuilds.
Getting rid of something is `seed remove-venv`, run deliberately by a person.

**Partial application is reported as failure.** If a step fails, `seed apply`
exits non-zero and names what didn't finish, because a half-applied profile
means the machine isn't what you specified. Re-running is safe: what already
succeeded is skipped.

Exit codes: `0` applied (or already current), `1` a step failed, `2` the
profile itself is invalid.

---

## Reference

| Key | Type | Meaning |
|---|---|---|
| `schema` | int | Profile format version. Currently `1`. |
| `python` | list | Interpreter versions to install, e.g. `["3.12"]`. |
| `[[venv]] name` | string | **Required.** Venv name. |
| `[[venv]] python` | string | Base tag to build from, e.g. `"312"`. Defaults to the default base. |
| `[[venv]] packages` | list | Packages for this venv. Specifiers like `"ruff>=0.5"` are fine. |
| `[[venv]] default` | bool | Make this the venv new shells auto-activate. At most one. |
| `[[venv]] default_packages` | bool | `false` skips `venv_default_packages` for this venv. |
| `[[repo]] url` | string | **Required.** Git URL to clone. |
| `[[repo]] install` | bool | Also install its dependencies, into the default venv. |
| `[config]` | table | Settings to write. See below. |

`[config]` accepts only settings that make sense per-user and after install:
`default_base`, `default_venv`, `venv_default_packages`, `vscode_flavor`,
`extension_gallery`, `vscode_extensions`.

Install-time settings — `update_source`, `package_index`, `python_mirror`,
`native_tls`, `ca_cert` — deliberately **cannot** be set from a profile. They
must be correct *before* seed-cli runs, so `seedling.conf` owns them; letting
a profile rewrite them would create two sources of truth for one value.

**Validation is strict.** An unknown key, a duplicate venv name, two default
venvs, or a `default_venv` naming a venv the profile doesn't declare all
reject the whole file with a message naming the problem. A profile goes to a
whole fleet: a typo should fail once for you, not quietly for each user.

---

## Offline bundles

`build-offline.cmd` reads the profile automatically (or takes `--profile
PATH`) and adds every package the profile's venvs need to the wheel set.

This matters more than it sounds. Without it, the profile and the bundler's
`--packages` list are two hand-maintained lists of the same thing, and any
drift between them surfaces as a failed install on the air-gapped side, long
after the bundle was carried there. Deriving one from the other removes that
failure mode. The preflight check then verifies the result before it leaves.

Pass `--profile=` (empty) to build a bundle that deliberately doesn't match
the repo's profile.
