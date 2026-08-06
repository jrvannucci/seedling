# Profile examples

Complete, working [deployment profiles](PROFILES.md) for real situations.
Each one is a whole file — copy it, change the names, ship it. For what every
key means, see the [profile reference](PROFILES.md#reference).

Save any of these as `seedling-profile.toml` next to `seedling.conf` in the
copy you distribute, and everyone who installs from it gets that environment.

## Contents

| Example | What it's for | Offline | Index | VS Code | Spyder | conda-forge | CA certs | Bundle | x86_64 only |
| --- | --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| **[Research group](#research-group)** | Spyder, two venvs | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |
| **[Software team](#software-team)** | VS Code, repos cloned | ❌ | ⚠️ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **[Both editors](#both-editors)** | One shared venv | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| **[Classroom](#classroom)** | Pinned, reproducible | ❌ | ❌ | ❌ | ✅ | ❌ | ⚠️ | ⚠️ | ✅ |
| **[Internal mirrors](#internal-mirrors)** | No bundle needed | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ |
| **[Internal PyPI only](#internal-pypi-only)** | Partial bundle | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ⚠️ | ✅ |
| **[Air-gapped (VSCodium)](#air-gapped-vscodium)** | No redistribution rights | ✅ | ✅ | ❌ | ❌ | ✅ | ⚠️ | ✅ | ❌ |
| **[Air-gapped (VS Code)](#air-gapped-vs-code)** | Keeps Pylance | ✅ | ✅ | ✅ | ❌ | ✅ | ⚠️ | ✅ | ❌ |
| **[Air-gapped (everything)](#air-gapped-everything)** | Every capability at once | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **[Just Python](#just-python)** | Interpreters and venvs only | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

✅ needed / available  ·  ❌ not needed / unavailable  ·  ⚠️ depends — see the
example

**What each column asks**

| Column | The question | Set by |
|---|---|---|
| **Offline** | Do the machines run with no internet access? | — |
| **Index** | Is a package source configured instead of pypi.org? | `SEEDLING_PACKAGE_INDEX` |
| **VS Code** | Does this need official VS Code and the Marketplace? | `editor`, `SEEDLING_VSCODE_FLAVOR` |
| **Spyder** | Does this install Spyder, from PyPI? | `editor` |
| **conda-forge** | Does this install conda-forge command-line tools? | `tools` |
| **CA certs** | Does this need a corporate CA certificate? | `vendor/certs/`, `SEEDLING_NATIVE_TLS` |
| **Bundle** | Must you build an offline bundle first? | `build-offline` |
| **x86_64 only** | Does this rule out arm64 machines? | implied by Spyder |

**Index** is the one to read carefully: ✅ means `package_index` is *set*, not
that you need an Artifactory. For the networked examples it's a URL pointing
at an internal mirror; for the air-gapped ones it's a *directory* of wheels on
the share. Same setting, two very different deployments — the example says
which. Likewise **x86_64 only** ✅ comes solely from Spyder, whose Qt dependency
publishes no arm64 wheels; every other piece runs on arm64 fine.

Scanning down a column tells you which scenarios share your constraint. Each
example then answers eleven questions rather than these eight — the three
omitted here (bundled git, a reachable git host, a multi-user share root)
matter less often when choosing.

---

## Research group

Scientists who work in Spyder and want their data collection kept apart from
their analysis. Two environments, because instrument drivers and analysis
libraries have a habit of disagreeing about versions — and when they do, you
want the collection rig to keep working.

**Assumes**

| Needs | ? | Detail |
|---|:-:|---|
| Internet on the machines | ✅ | every machine reaches PyPI |
| Internal package index | ❌ | public PyPI; set `package_index` for an internal mirror |
| Official VS Code + Marketplace | ❌ | no Microsoft account or Marketplace access needed |
| Spyder (from PyPI) | ✅ | the editor for this deployment |
| conda-forge tools | ❌ | nothing outside PyPI |
| Corporate CA certificate | ❌ | default trust store |
| Bundled git (MinGit) | ❌ | Windows bootstraps it if `seed repo-clone` is used |
| A reachable git host | ❌ | no `[[repo]]` entries |
| Multi-user share root | ❌ | each person installs to their own `~/seedling` |
| Offline bundle to build | ❌ | installs straight from the internet |
| **x86_64 only** | ✅ | Spyder's Qt wheels are x86_64-only |

```toml
# seedling-profile.toml -- environment for the lab.

python = ["3.12"]

# Spyder only. No VS Code: this also switches off the installer's VS Code
# setup, so nobody waits on a ~300 MB download they'll never open.
editor = "spyder"

# Collecting: talks to instruments. Deliberately lean -- the fewer libraries
# in here, the fewer things that can break a run that's already underway.
[[venv]]
name = "collect"
packages = ["pyserial", "pyvisa", "pandas"]

# Analysing: the heavy stack. This is the one people are in most of the day,
# so it's the default -- new terminals land here, and `seed spyder` opens
# against it.
[[venv]]
name = "analyse"
packages = ["pandas", "numpy", "scipy", "matplotlib", "seaborn",
            "jupyterlab", "openpyxl"]
default = true
```

**Why it's shaped this way**

- `default = true` on `analyse` sets what new terminals activate. Spyder
  follows the *activated* venv, so `seed activate collect && seed spyder`
  opens against the rig instead — the switch is one command, no
  reconfiguration.
- Spyder's console needs a matching `spyder-kernels` in whichever venv it
  runs code in. `seed spyder` installs it for you; you don't list it here.
- `openpyxl` because someone always has an `.xlsx`.

> **Spyder is x86_64 only** — its Qt dependency publishes no arm64 wheels. On
> Apple Silicon or ARM Linux, drop the `editor` line and use
> `tools = ["spyder"]` instead, which installs the conda-forge build.

**Vendor folder:** none — nothing is bundled, so there is no `vendor/` at all.
Everything downloads on demand from PyPI.

---

## Software team

Engineers who live in VS Code, on a codebase that's already in git. The repos
are cloned *and* their dependencies installed, so a new hire's first command
is the one that does actual work.

**Assumes**

| Needs | ? | Detail |
|---|:-:|---|
| Internet on the machines | ✅ | PyPI, the Marketplace and your git host |
| Internal package index | ⚠️ | swap in Artifactory/Nexus via `package_index` if you have one |
| Official VS Code + Marketplace | ✅ | the official build, with Pylance |
| Spyder (from PyPI) | ❌ | VS Code only |
| conda-forge tools | ✅ | `ripgrep`, `gh`, `just` from conda-forge |
| Corporate CA certificate | ❌ | default trust store |
| Bundled git (MinGit) | ❌ | system git on macOS/Linux; Windows bootstraps it |
| A reachable git host | ✅ | two `[[repo]]` entries clone from GitHub |
| Multi-user share root | ❌ | per-user installs |
| Offline bundle to build | ❌ | installs straight from the internet |
| **x86_64 only** | ❌ | VS Code runs on arm64 too |

```toml
# seedling-profile.toml -- the platform team's standard environment.

python = ["3.12", "3.11"]

# Command-line tools that aren't Python packages, so `seed install` can't
# provide them.
tools = ["ripgrep", "gh", "just"]

editor = "vscode"

[[venv]]
name = "dev"
python = "312"
packages = ["pytest", "pytest-cov", "mypy", "ruff", "ipython"]
default = true

# Kept on 3.11 because the legacy service hasn't moved yet. Both interpreters
# are listed above, so this resolves without anyone installing one by hand.
[[venv]]
name = "legacy"
python = "311"
packages = ["pytest", "requests"]

[[repo]]
url = "https://github.com/acme/platform.git"
install = "dev"         # editable install into the dev venv

# The shared library is developed against from both environments, so it's
# named for both rather than left to whichever venv happens to be the default.
# Its test extra is wanted on 3.12 only -- extras attach to the venv they're
# for, so one clone lands differently in each.
[[repo]]
url = "https://github.com/acme/shared-lib.git"
install = ["dev[test]", "legacy"]

[config]
vscode_extensions = [
    "ms-python.python",
    "ms-python.vscode-pylance",
    "charliermarsh.ruff",
    "eamodio.gitlens",
]
```

**Why it's shaped this way**

- `python = ["3.12", "3.11"]` first, then each venv names its base with
  `python = "312"` / `"311"`. A venv can only build from an interpreter the
  profile installs.
- `install` names the venvs to run the equivalent of `seed repo-install` in
  after cloning — an editable install when the repo has a `pyproject.toml`,
  otherwise its `requirements.txt`. One name or a list; rebuild one of those
  venvs later and `seed apply` installs the repo into it again.
- `vscode_extensions` **replaces** the built-in starter kit rather than adding
  to it, so list everything you want, including the Python extension.

**Team shortcuts, as [custom commands](CUSTOM-COMMANDS.md).** `ruff` and
`pytest` are already in `dev`'s packages above — declaring `seed lint` and
`seed test` as one-line wrappers means a new hire's first commands work
without them ever discovering the underlying tool names:

```toml
# custom-commands.toml -- next to seedling-profile.toml in the distributed copy
[[command]]
name = "lint"
run = ["ruff", "check", "."]
venv = "dev"
description = "Lint the current project"

[[command]]
name = "test"
run = ["pytest", "-q"]
venv = "dev"
description = "Run the test suite"
```

Wired in `seedling.conf` next to `SEEDLING_PROFILE`:

```sh
SEEDLING_CUSTOM_COMMANDS="custom-commands.toml"
```

`venv = "dev"` pins both to the `dev` venv regardless of what's active in the
caller's shell — the same reasoning `[[repo]] install` names venvs explicitly
rather than trusting whatever happens to be the default.

**Vendor folder:** none. Everything downloads on demand.

---

## Both editors

One department, two working styles. Both editors are installed; each person
uses whichever they open.

**Assumes**

| Needs | ? | Detail |
|---|:-:|---|
| Internet on the machines | ✅ | PyPI and the Marketplace |
| Internal package index | ❌ | public PyPI |
| Official VS Code + Marketplace | ✅ | for the VS Code half |
| Spyder (from PyPI) | ✅ | for the Spyder half |
| conda-forge tools | ❌ | none declared |
| Corporate CA certificate | ❌ | default trust store |
| Bundled git (MinGit) | ❌ | not needed |
| A reachable git host | ❌ | no `[[repo]]` entries |
| Multi-user share root | ❌ | per-user installs |
| Offline bundle to build | ❌ | installs straight from the internet |
| **x86_64 only** | ✅ | the Spyder half pins the whole profile to x86_64 |

```toml
# seedling-profile.toml -- research engineering.

python = ["3.12"]

editor = ["vscode", "spyder"]

[[venv]]
name = "work"
packages = ["pandas", "numpy", "matplotlib", "pytest", "ipython"]
default = true
```

**Why it's shaped this way**

- Listing both means ~500 MB of editors, so it's worth being deliberate.
  Naming VS Code among them also keeps its download running in parallel with
  the Python setup, which listing Spyder alone would skip.
- One shared venv, because the split here is about tooling preference, not
  about incompatible dependencies. Use separate venvs when the *packages*
  disagree, not when the people do.

**Vendor folder:** none. Everything downloads on demand.

---

## Classroom

Thirty machines that must be identical, and a student who breaks one should
be able to rebuild it in a single command. Everything pinned, nothing
optional.

**Assumes**

| Needs | ? | Detail |
|---|:-:|---|
| Internet on the machines | ✅ | during setup at least |
| Internal package index | ❌ | public PyPI |
| Official VS Code + Marketplace | ❌ | deliberately avoided -- no accounts to manage |
| Spyder (from PyPI) | ✅ | the only editor |
| conda-forge tools | ❌ | none |
| Corporate CA certificate | ⚠️ | only if the campus proxy inspects TLS |
| Bundled git (MinGit) | ❌ | not needed |
| A reachable git host | ❌ | no `[[repo]]` entries |
| Multi-user share root | ❌ | per-user installs on lab machines |
| Offline bundle to build | ⚠️ | only if the lab machines have no internet |
| **x86_64 only** | ✅ | Spyder's Qt wheels are x86_64-only |

```toml
# seedling-profile.toml -- PHYS-201, autumn term.

python = ["3.12"]

editor = "spyder"

[[venv]]
name = "phys201"
packages = [
    "numpy==2.1.3",
    "scipy==1.14.1",
    "matplotlib==3.9.2",
    "pandas==2.2.3",
]
default = true
# Only the four pinned packages above -- not seedling's usual ipython/ruff/
# ipykernel. Everyone gets the same list, and the marker's machine matches.
default_packages = false
```

**Why it's shaped this way**

- Exact `==` pins so results reproduce in week twelve as they did in week one.
- `default_packages = false` keeps the environment to exactly what's listed.
  Note that `seed spyder` still adds `spyder-kernels` — that's required for
  its console to connect at all, not an extra.
- Rebuilding a broken machine is `seed remove-venv phys201 && seed apply` --
  or, with the [custom command](CUSTOM-COMMANDS.md) below, `seed reset`.

**`seed reset`, so a student never has to remember the two-command recipe.**
This is the [`script` shape](CUSTOM-COMMANDS.md#the-script-shape) rather
than `run`, because it chains two `seed` operations rather than running a
single fixed one — and `toplevel = true`
([making a command top-level](CUSTOM-COMMANDS.md#making-a-command-top-level))
means it really is just the one word to type, not `seed custom reset`:

```toml
# custom-commands.toml -- next to seedling-profile.toml
[[command]]
name = "reset"
script = "reset.py"
description = "Rebuild the phys201 venv from scratch"
toplevel = true
```

```python
# reset.py, next to custom-commands.toml
import subprocess, sys

def main(argv):
    subprocess.run(["seed", "remove-venv", "phys201", "-y"], check=True)
    subprocess.run(["seed", "apply"], check=True)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

```sh
# seedling.conf
SEEDLING_CUSTOM_COMMANDS="custom-commands.toml"
```

No SDK, no special orchestration API — the script shells out to `seed`
itself, the same two commands from the bullet point above, just one word for
a student to type and remember: `seed reset`.

**Vendor folder:** none, assuming the lab machines have internet during setup.
If they don't, build a bundle instead — see
[Air-gapped (everything)](#air-gapped-everything) and take only the pieces you
need.

---

## Internal mirrors

The middle ground, and the most common enterprise shape: **no public
internet, but working internal mirrors.** An Artifactory or Nexus proxying
PyPI, a conda-forge mirror, an internal GitLab, and a TLS-inspecting proxy in
front of all of it.

This needs **no offline bundle at all** — the mirrors are reachable, so
seedling installs from them the same way it would from the public ones. It is
a different situation from an air gap, and treating it like one costs you a
build step you don't need.

**Assumes**

| Needs | ? | Detail |
|---|:-:|---|
| Internet on the machines | ❌ | no public PyPI, no Marketplace, no GitHub |
| Internal package index | ✅ | **this is the point** -- Artifactory/Nexus/devpi over HTTPS |
| Official VS Code + Marketplace | ❌ | the update API and Marketplace are blocked |
| Spyder (from PyPI) | ✅ | installs from the internal index like any other package |
| conda-forge tools | ✅ | from an internal conda-forge mirror |
| Corporate CA certificate | ✅ | **required** -- the proxy re-signs HTTPS |
| Bundled git (MinGit) | ❌ | system git, pointed at the internal host |
| A reachable git host | ✅ | internal GitHub/GitLab |
| Multi-user share root | ❌ | per-user installs |
| Offline bundle to build | ❌ | **no bundle needed** -- the mirrors are reachable |
| **x86_64 only** | ✅ | Spyder's Qt wheels are x86_64-only |

```toml
# seedling-profile.toml -- the standard environment.

python = ["3.12"]

tools = ["ripgrep", "pandoc"]

# Spyder comes from the internal index like any other package -- no
# Marketplace, no update API, nothing that has to reach microsoft.com.
editor = "spyder"

[[venv]]
name = "work"
packages = ["pandas", "numpy", "requests", "pytest"]
default = true

[[repo]]
url = "https://gitlab.corp.example/data/toolkit.git"
install = "work"

[config]
default_venv = "work"
```

The mirrors and the CA go in `seedling.conf`, because they must be right
before seed-cli exists:

```sh
# seedling.conf -- in the copy you distribute.

# A URL, not a directory: these are reachable services, not a share.
SEEDLING_PACKAGE_INDEX="https://artifactory.corp.example/api/pypi/pypi/simple"
SEEDLING_CONDA_CHANNEL="https://artifactory.corp.example/api/conda/conda-forge"
SEEDLING_PYTHON_MIRROR="https://artifactory.corp.example/generic/python-build-standalone"

# Install seedling itself from the internal git host.
SEEDLING_REPO_URL="https://gitlab.corp.example/platform/seedling.git"

# The proxy re-signs HTTPS. Either trust the OS store, if IT installed the
# corporate root machine-wide...
SEEDLING_NATIVE_TLS="true"
# ...or leave that false and ship the PEM in vendor/certs/ instead.

# No VS Code: the update API and Marketplace are blocked, so an attempted
# install would fail rather than fall back.
SEEDLING_AUTO_VSCODE="false"

SEEDLING_PROFILE="seedling-profile.toml"
```

**Why it's shaped this way**

- **`package_index` as a URL, not a directory.** seedling treats the two
  differently: a URL becomes uv's default index, a directory becomes a flat
  file index with the internet disabled. Here the mirror is a live service,
  so it's a URL.
- **`SEEDLING_NATIVE_TLS="true"` is usually the right answer** on a managed
  fleet — IT has already pushed the corporate root into the OS store, so
  seedling can use it and you ship no certificate at all. Fall back to
  `vendor/certs/` only when that isn't true.
- **Spyder rather than VS Code**, because VS Code's download and its
  Marketplace are both external services that a restricted network typically
  blocks. Spyder is a PyPI package, so it arrives through the mirror you
  already have. If your proxy *does* allow the Marketplace, use `editor =
  "vscode"` and set `extension_gallery` to your Open VSX mirror.
- **`SEEDLING_AUTO_VSCODE="false"`** is belt-and-braces: the profile's
  `editor` already suppresses it, but stating it in the conf documents the
  intent for whoever reads this file next.

**Check it before rollout.** `seed health-check` verifies the mirrors and the
CA bundle are actually reachable and valid, which is the failure this shape is
prone to:

```
seed health-check
```

**Make that check run for every user, every terminal, automatically.** This
is the shape's real failure mode day-to-day: someone's VPN drops, or a
mirror goes down for maintenance, and their `seed install` just times out
with no obvious cause. A [startup command](CUSTOM-COMMANDS.md) turns
"check it before rollout" into "it's already been checked by the time you
notice something's wrong":

```toml
# custom-commands.toml -- next to seedling-profile.toml
[[command]]
name = "check-mirror"
run = ["seed", "health-check"]
description = "Verify the internal mirrors and CA bundle are reachable"
```

```sh
# seedling.conf
SEEDLING_CUSTOM_COMMANDS="custom-commands.toml"
SEEDLING_STARTUP_COMMANDS="check-mirror"
```

Every new terminal now runs it automatically. If a mirror is unreachable,
the shell still opens — a failing startup command warns and moves on, never
locks anyone out — but the warning is right there when they open the
terminal, not buried in a confusing `seed install` failure five minutes
later.

---

**Vendor folder:** none — and that is the distinction worth understanding.

This network has **no internet but working internal mirrors**, so nothing
needs bundling: `package_index` and `conda_channel` are URLs your machines
can already reach, and seedling installs from them exactly as it would from
the public ones. `vendor/` exists only for a bundle, and there is no bundle
here.

The one thing you *do* supply by hand is the CA, because a TLS-inspecting
proxy is what makes those internal URLs work at all. Two ways:

- `SEEDLING_NATIVE_TLS="true"` if IT already installed the corporate root
  machine-wide — seedling then uses the OS trust store and you ship nothing.
- Otherwise put the PEM in `vendor/certs/` in the copy you distribute, which
  is the one case where a non-bundle deployment still has a `vendor/` folder.

**What a cert file looks like.** Any PEM-encoded certificate, one or more per
file. The installer concatenates *every* `.pem` and `.crt` in the folder into
`~/seedling/system/certs/ca-bundle.pem`, so a root and an intermediate can be
separate files:

```
vendor/certs/
├── corp-root-ca.pem
└── corp-issuing-ca.pem
```

```
-----BEGIN CERTIFICATE-----
MIIDdzCCAl+gAwIBAgIEAgAAuTANBgkqhkiG9w0BAQUFADBaMQswCQYDVQQGEwJJ
... base64, usually 20-30 lines ...
c2VkbGluZyBleGFtcGxlIC0tIG5vdCBhIHJlYWwgY2VydGlmaWNhdGU=
-----END CERTIFICATE-----
```

Export it from your browser or from IT as **Base-64 encoded X.509**, not DER.
A DER file (binary, often `.cer`) gets concatenated as bytes and quietly
breaks the bundle — if HTTPS fails after install, check this first. The bundle
is rebuilt on every install, so rotating a certificate is a re-run rather than
a manual edit.

---

## Internal PyPI only

The awkward middle: IT runs an Artifactory that proxies **PyPI and only
PyPI**. No conda-forge mirror, no python-build-standalone mirror, no Marketplace,
and a proxy that re-signs HTTPS on the way through.

This is a **partial bundle**, and it is the case that shows seedling's offline
pieces are independent of each other. Each source is configured separately, so
you point the one you have at a URL and bundle the three you don't:

| Needs | Comes from |
|---|---|
| Python packages | 🌐 the internal PyPI, over HTTPS |
| Interpreters | 📦 bundled `python-builds/` |
| conda-forge tools | 📦 bundled `conda-channel/` |
| VS Code | 📦 bundled `vendor/vscode/` |
| **Spyder** | 🌐 the internal PyPI — it *is* a Python package |
| CA certificate | ✋ you supply it, in `vendor/certs/` |

**Assumes**

| Needs | ? | Detail |
|---|:-:|---|
| Internet on the machines | ❌ | no public internet; one live internal service |
| Internal package index | ✅ | **the only thing reachable** -- Artifactory proxying PyPI |
| Official VS Code + Marketplace | ❌ | Marketplace blocked, so VS Code is **bundled** instead |
| Spyder (from PyPI) | ✅ | installs from the internal PyPI -- no bundling needed |
| conda-forge tools | ✅ | no conda-forge mirror, so a **bundled** conda channel |
| Corporate CA certificate | ✅ | **required** -- the proxy re-signs HTTPS |
| Bundled git (MinGit) | ✅ | `--mingit`; no git host to clone from either |
| A reachable git host | ❌ | no `[[repo]]` entries |
| Multi-user share root | ❌ | per-user installs from the share |
| Offline bundle to build | ⚠️ | **partial** -- everything except the wheels |
| **x86_64 only** | ✅ | the Spyder half pins the whole profile to x86_64 |

```toml
# seedling-profile.toml -- the standard environment.

python = ["3.12"]

# No conda-forge mirror here, so these come from the bundled channel.
tools = ["ripgrep", "pandoc"]

# Two editors, sourced two different ways: VS Code is pre-seeded into the
# bundle because the Marketplace is unreachable, while Spyder installs from
# the internal PyPI like any other package. Neither needs the internet.
editor = ["vscode", "spyder"]

[[venv]]
name = "work"
packages = ["pandas", "numpy", "requests", "pytest"]
default = true
```

The conf is where this shape becomes visible — **a URL and directory paths
side by side**:

```sh
# seedling.conf -- in the copy on the share.

# Install seedling itself from the share: no git, no network.
SEEDLING_REPO_URL="S:\seedling\seedling"

# The one live service: a URL, so uv treats it as an index and resolves
# against it normally. Spyder arrives through here.
SEEDLING_PACKAGE_INDEX="https://artifactory.corp.example/api/pypi/pypi/simple"

# The two that aren't mirrored: directories in the bundle, so uv reads them
# as local sources with the internet disabled.
SEEDLING_PYTHON_MIRROR="S:\seedling\python-builds"
SEEDLING_CONDA_CHANNEL="S:\seedling\conda-channel"

# The proxy re-signs HTTPS and IT has NOT pushed the root machine-wide, so
# ship the PEM in vendor/certs/ and leave native_tls off.
SEEDLING_NATIVE_TLS="false"

SEEDLING_PROFILE="seedling-profile.toml"
```

**Building it.** The wheel step is the one you can skip, because the mirror
already serves packages. `build-offline` is a walkthrough, so run it *without*
`--yes` and answer **no** at "Download the wheels now?", then yes to the rest:

```
build-offline.cmd --profile seedling-profile.toml ^
                  --python 3.12 ^
                  --tools ripgrep,pandoc ^
                  --mingit ^
                  --deploy-root "S:\seedling" ^
                  --accept-third-party-terms
```

Staging the wheels anyway is harmless and gives you a fallback if the mirror
goes down — but then `package_index` must point at `S:\seedling\wheels`
instead of the URL, since only one of the two can be the package source.

**Why it's shaped this way**

- **A URL and a directory in the same conf is normal**, not a workaround.
  seedling resolves each source independently: `package_index` as a URL
  becomes uv's default index, while `python_mirror` and `conda_channel` as
  directories become local sources. Nothing requires them to agree.
- **Spyder needs no bundling** on this network, which is the quiet advantage
  of an editor that ships as a Python package. VS Code has to be pre-seeded
  because its download endpoint and its Marketplace are both external
  services; Spyder just resolves from the index you already have.
- **`--accept-third-party-terms` is still required**, because the bundle
  contains the official VS Code and its Marketplace extensions even though
  the packages come from your mirror. What you are acknowledging is the
  *staging on the share*, not where the wheels came from.
- **The CA is the piece nobody can build for you.** A TLS-inspecting proxy is
  precisely what makes the internal PyPI URL work; without the root in
  `vendor/certs/`, every HTTPS call — uv's index requests included — fails
  certificate verification, and the symptom looks like a broken mirror rather
  than a missing certificate.

**Check it on the first machine**, since this shape has two independent ways
to fail — the URL and the bundled directories:

```
seed health-check
```

It verifies the CA bundle exists and parses, that the mirror directories are
present, and that the index is reachable.

---

**What the bundle looks like**

Note what is *absent*: no `wheels/`, because the internal PyPI serves those.

```
offline-bundle/                    -> copied to S:\seedling
├── MANIFEST.json
├── seedling/                      users run install.cmd from here
│   ├── seedling.conf              the mixed URL + directory conf above
│   ├── seedling-profile.toml
│   └── vendor/
│       ├── uv/
│       │   ├── uv.exe
│       │   └── uvx.exe
│       ├── vscode/                official VS Code -- the Marketplace is
│       │   └── app/               unreachable, so it is pre-seeded
│       │       ├── Code.exe
│       │       ├── bin/code.cmd
│       │       └── data/          settings + extensions
│       ├── micromamba/
│       │   └── micromamba.exe
│       ├── git/                   MinGit, from --mingit
│       │   └── cmd/git.exe
│       └── certs/                 <- YOU fill this one
│           └── corp-root-ca.pem
├── python-builds/                 no PBS mirror internally, so bundled
│   └── 20250115/
│       └── cpython-3.12.8+2025...-x86_64-pc-windows-msvc-install_only.tar.gz
├── conda-channel/                 no conda-forge mirror internally, so bundled
│   ├── noarch/repodata.json
│   └── win-64/
│       ├── repodata.json
│       ├── ripgrep-14.1.1-h.....conda
│       └── pandoc-3.5-h.....conda
└── (no wheels/ -- SEEDLING_PACKAGE_INDEX is the Artifactory URL)
```

Spyder is the interesting absence too: it never appears in the bundle,
because `seed apply` installs it from the internal index at provisioning
time, the same way it installs `pandas`.

Where each lands on the target:

| Bundle folder | Installed to |
|---|---|
| `vendor/uv/` | `system/bin/` |
| `vendor/micromamba/` | `system/bin/` |
| `vendor/vscode/` | `extensions/vscode/` |
| `vendor/git/` | `extensions/git/` |
| `vendor/certs/` | concatenated into `system/certs/ca-bundle.pem` |

**What a cert file looks like.** Any PEM-encoded certificate, one or more per
file. The installer concatenates *every* `.pem` and `.crt` in the folder into
`~/seedling/system/certs/ca-bundle.pem`, so a root and an intermediate can be
separate files:

```
vendor/certs/
├── corp-root-ca.pem
└── corp-issuing-ca.pem
```

```
-----BEGIN CERTIFICATE-----
MIIDdzCCAl+gAwIBAgIEAgAAuTANBgkqhkiG9w0BAQUFADBaMQswCQYDVQQGEwJJ
... base64, usually 20-30 lines ...
c2VkbGluZyBleGFtcGxlIC0tIG5vdCBhIHJlYWwgY2VydGlmaWNhdGU=
-----END CERTIFICATE-----
```

Export it from your browser or from IT as **Base-64 encoded X.509**, not DER.
A DER file (binary, often `.cer`) gets concatenated as bytes and quietly
breaks the bundle — if HTTPS fails after install, check this first. The bundle
is rebuilt on every install, so rotating a certificate is a re-run rather than
a manual edit.

---

## Air-gapped (VSCodium)

A network with no internet, and a review that will ask what you redistributed.
Pairs with an [offline bundle](OFFLINE.md).

**Assumes**

| Needs | ? | Detail |
|---|:-:|---|
| Internet on the machines | ❌ | **none** on the target network |
| Internal package index | ✅ | a *directory* of wheels on the share, not a URL |
| Official VS Code + Marketplace | ❌ | **no rights to redistribute it** -- this is the whole point |
| Spyder (from PyPI) | ❌ | VSCodium only |
| conda-forge tools | ✅ | `ripgrep`, `pandoc`, bundled as a conda channel |
| Corporate CA certificate | ⚠️ | if a proxy inspects TLS -- you supply the root |
| Bundled git (MinGit) | ⚠️ | pass `--mingit` if the targets have no git |
| A reachable git host | ❌ | no `[[repo]]` entries |
| Multi-user share root | ❌ | per-user installs from the share |
| Offline bundle to build | ✅ | built once on a connected machine |
| **x86_64 only** | ❌ | VSCodium ships arm64 builds |

```toml
# seedling-profile.toml -- distributed on the share, applied at install.

python = ["3.12"]

tools = ["ripgrep", "pandoc"]

editor = "vscode"

[[venv]]
name = "work"
packages = ["pandas", "numpy", "requests", "pytest"]
default = true
```

**Which editor build is decided in `seedling.conf`, not here.** The bundler
stages the editor *before* any profile is applied, so it reads the conf on
the build machine:

```sh
# seedling.conf, in the copy you distribute
SEEDLING_VSCODE_FLAVOR="vscodium"
SEEDLING_VSCODE_EXTENSIONS="ms-python.python,ms-toolsai.jupyter,charliermarsh.ruff"
```

**Why it's shaped this way**

- VSCodium is the licensing decision, not a preference: staging the official
  VS Code binaries on a share is redistribution under Microsoft's terms.
  It's MIT-licensed, already points at Open VSX, and needs no
  acknowledgement to bundle.
- **The tradeoff is Pylance** — proprietary, and absent from Open VSX by
  design — so the Python extension falls back to its bundled Jedi server.
  If your organization *does* hold Marketplace rights, see
  [the next example](#air-gapped-vs-code).
- The bundler reads the *profile* for everything else, so `build-offline`
  stages wheels for every package listed and a conda channel for every tool
  — no second hand-kept list. Build it with
  `build-offline.cmd --profile seedling-profile.toml`.
- Nothing here mentions the share's paths: those live in `seedling.conf`
  (`SEEDLING_PACKAGE_INDEX` and friends), which is install-time configuration
  a profile deliberately can't override.

**What the bundle looks like**

```
offline-bundle/
├── MANIFEST.json            what was staged, and under what licence
├── seedling/                users run install.cmd from here
│   ├── seedling.conf            written with your --deploy-root paths
│   ├── seedling-profile.toml    the profile above
│   └── vendor/
│       ├── uv/                  uv.exe, uvx.exe
│       ├── vscode/              app/  (portable VSCodium + Open VSX exts)
│       ├── micromamba/          micromamba.exe
│       ├── certs/               <- YOU fill this one
│       └── git/                 only with --mingit
├── python-builds/           SEEDLING_PYTHON_MIRROR
├── wheels/                  SEEDLING_PACKAGE_INDEX
└── conda-channel/           SEEDLING_CONDA_CHANNEL
```

Where each lands on the target:

| Bundle folder | Installed to |
|---|---|
| `vendor/uv/` | `system/bin/` |
| `vendor/micromamba/` | `system/bin/` |
| `vendor/vscode/` | `extensions/vscode/` |
| `vendor/git/` | `extensions/git/` |
| `vendor/certs/` | concatenated into `system/certs/ca-bundle.pem` |

**What a cert file looks like.** Any PEM-encoded certificate, one or more per
file. The installer concatenates *every* `.pem` and `.crt` in the folder into
`~/seedling/system/certs/ca-bundle.pem`, so a root and an intermediate can be
separate files:

```
vendor/certs/
├── corp-root-ca.pem
└── corp-issuing-ca.pem
```

```
-----BEGIN CERTIFICATE-----
MIIDdzCCAl+gAwIBAgIEAgAAuTANBgkqhkiG9w0BAQUFADBaMQswCQYDVQQGEwJJ
... base64, usually 20-30 lines ...
c2VkbGluZyBleGFtcGxlIC0tIG5vdCBhIHJlYWwgY2VydGlmaWNhdGU=
-----END CERTIFICATE-----
```

Export it from your browser or from IT as **Base-64 encoded X.509**, not DER.
A DER file (binary, often `.cer`) gets concatenated as bytes and quietly
breaks the bundle — if HTTPS fails after install, check this first. The bundle
is rebuilt on every install, so rotating a certificate is a re-run rather than
a manual edit.

---

## Air-gapped (VS Code)

The same disconnected network, but this organization has the agreements in
place to redistribute the official VS Code build and Marketplace extensions
internally — so it keeps **Pylance**, and with it the type checking and
completions the openly-licensed stack can't offer.

The profile is unremarkable; the licensing decision lives in the conf.

**Assumes**

| Needs | ? | Detail |
|---|:-:|---|
| Internet on the machines | ❌ | **none** on the target network |
| Internal package index | ✅ | a *directory* of wheels on the share, not a URL |
| Official VS Code + Marketplace | ✅ | **you hold redistribution rights** -- keeps Pylance |
| Spyder (from PyPI) | ❌ | VS Code only |
| conda-forge tools | ✅ | `ripgrep`, `pandoc`, bundled as a conda channel |
| Corporate CA certificate | ⚠️ | if a proxy inspects TLS -- you supply the root |
| Bundled git (MinGit) | ⚠️ | pass `--mingit` if the targets have no git |
| A reachable git host | ❌ | no `[[repo]]` entries |
| Multi-user share root | ❌ | per-user installs from the share |
| Offline bundle to build | ✅ | built once, with `--accept-third-party-terms` |
| **x86_64 only** | ❌ | VS Code ships arm64 builds |

```toml
# seedling-profile.toml -- distributed on the share, applied at install.

python = ["3.12"]

tools = ["ripgrep", "pandoc"]

editor = "vscode"

[[venv]]
name = "work"
packages = ["pandas", "numpy", "requests", "pytest", "mypy"]
default = true
```

```sh
# seedling.conf, in the copy you distribute.
# "microsoft" is the default, but state it explicitly here -- this file is
# what a reviewer reads to see which build was staged.
SEEDLING_VSCODE_FLAVOR="microsoft"
SEEDLING_VSCODE_EXTENSIONS="ms-python.python,ms-python.vscode-pylance,ms-python.debugpy,ms-toolsai.jupyter,charliermarsh.ruff"
```

Build it with the acknowledgement, which is deliberately **not** covered by
`--yes`:

```
build-offline.cmd --profile seedling-profile.toml --accept-third-party-terms
```

**Why it's shaped this way**

- `ms-python.vscode-pylance` is the whole point of this variant. It is
  licensed to run only in official Microsoft products, so it belongs with
  `SEEDLING_VSCODE_FLAVOR="microsoft"` and nowhere else — pairing it with
  VSCodium gets you an extension that refuses to load.
- `--accept-third-party-terms` is required because VS Code and Marketplace
  extensions are marked **restricted**: staging them on a share is
  redistribution *you* are performing. seedling grants no rights; the flag is
  you asserting you hold them. It resists `--yes` on purpose, so an
  unattended build can't acknowledge licence terms on your behalf.
- The bundle's `MANIFEST.json` lists every component with its licence and
  whether it was staged. That file is what to hand a security review rather
  than re-deriving the answer.
- `mypy` in the venv rather than relying on Pylance alone: Pylance checks in
  the editor, but CI and pre-commit need a checker they can run headlessly.

**What the bundle looks like**

The same shape as the previous example, with two differences: `vendor/vscode/`
holds the **official** build with Marketplace extensions (Pylance included),
and `MANIFEST.json` records those as `restricted` — which is exactly what
`--accept-third-party-terms` acknowledges.

```
offline-bundle/
├── MANIFEST.json            lists VS Code + extensions as RESTRICTED
├── seedling/
│   ├── seedling.conf
│   ├── seedling-profile.toml
│   └── vendor/
│       ├── uv/                  uv.exe, uvx.exe
│       ├── vscode/
│       │   └── app/             official VS Code, portable
│       │       ├── Code.exe
│       │       ├── bin/code.cmd     the CLI entry point seedling drives
│       │       └── data/            portable-mode settings AND extensions,
│       │                            incl. ms-python.vscode-pylance-*
│       ├── micromamba/          micromamba.exe
│       └── certs/               <- YOU fill this one
├── python-builds/
├── wheels/
└── conda-channel/
```

Extensions live under `app/data/` rather than `~/.vscode` — that is portable
mode, and it is why `seed purge` leaves nothing behind.

**What a cert file looks like.** Any PEM-encoded certificate, one or more per
file. The installer concatenates *every* `.pem` and `.crt` in the folder into
`~/seedling/system/certs/ca-bundle.pem`, so a root and an intermediate can be
separate files:

```
vendor/certs/
├── corp-root-ca.pem
└── corp-issuing-ca.pem
```

```
-----BEGIN CERTIFICATE-----
MIIDdzCCAl+gAwIBAgIEAgAAuTANBgkqhkiG9w0BAQUFADBaMQswCQYDVQQGEwJJ
... base64, usually 20-30 lines ...
c2VkbGluZyBleGFtcGxlIC0tIG5vdCBhIHJlYWwgY2VydGlmaWNhdGU=
-----END CERTIFICATE-----
```

Export it from your browser or from IT as **Base-64 encoded X.509**, not DER.
A DER file (binary, often `.cer`) gets concatenated as bytes and quietly
breaks the bundle — if HTTPS fails after install, check this first. The bundle
is rebuilt on every install, so rotating a certificate is a re-run rather than
a manual edit.

---

## Air-gapped (everything)

A disconnected multi-user site that wants the lot: both editors, conda-forge
tools, several interpreters, cloned repos, a corporate CA, and no internet
anywhere. This is the maximal case — most deployments need a fraction of it,
so read it as a menu rather than a template.

Three files do the work. **The profile** describes the environment:

**Assumes**

| Needs | ? | Detail |
|---|:-:|---|
| Internet on the machines | ❌ | **none** anywhere; one connected build machine, once |
| Internal package index | ✅ | a *directory* of wheels on the share |
| Official VS Code + Marketplace | ✅ | rights held; Pylance included |
| Spyder (from PyPI) | ✅ | from the bundled wheels (`--packages spyder`) |
| conda-forge tools | ✅ | `ripgrep`, `pandoc`, `gh` |
| Corporate CA certificate | ✅ | **required** -- a proxy re-signs HTTPS on this network |
| Bundled git (MinGit) | ✅ | `--mingit`, for Windows targets with no git |
| A reachable git host | ✅ | internal host, reachable from the target network |
| Multi-user share root | ✅ | `S:\users\{user}\seedling`, enabling the `admin-*` commands |
| Offline bundle to build | ✅ | the full build, every flag |
| **x86_64 only** | ✅ | the Spyder half pins the whole profile to x86_64 |

```toml
# seedling-profile.toml -- the standard environment, applied at install and
# re-applied with `seed apply` whenever this file changes.

schema = 1

# Every interpreter anyone needs. Each is mirrored into the bundle, and the
# wheel set is resolved once per interpreter, so platform/abi wheels match
# all of them.
python = ["3.12", "3.11"]

# Non-Python programs, from conda-forge. Bundled as a local conda channel.
tools = ["ripgrep", "pandoc", "gh"]

# Both editors: engineers open VS Code, analysts open Spyder.
editor = ["vscode", "spyder"]

# --- environments ---------------------------------------------------------

[[venv]]
name = "dev"
python = "312"
packages = ["pytest", "pytest-cov", "mypy", "ruff", "ipython"]
default = true

[[venv]]
name = "analysis"
python = "312"
packages = ["pandas", "numpy", "scipy", "matplotlib", "jupyterlab", "openpyxl"]

# Pinned to 3.11 for the service that hasn't migrated, and given nothing but
# what it lists -- no ipython/ruff/ipykernel on top.
[[venv]]
name = "legacy"
python = "311"
packages = ["requests==2.32.3", "flask==3.0.3"]
default_packages = false

# --- internal repos -------------------------------------------------------
# Cloned from the internal git host (or a share path), never the internet.

[[repo]]
url = "https://git.corp.example/platform/toolkit.git"
install = "dev"

# Each repo names the environment it belongs in, rather than following
# whichever venv happens to be the default.
[[repo]]
url = "https://git.corp.example/platform/analysis-lib.git"
install = "analysis"

# --- settings pushed to every machine -------------------------------------

[config]
# Every key a profile is allowed to set. The install-time settings -- the
# mirror, the index, TLS, the update source -- belong in seedling.conf
# instead: they have to be right before seed-cli runs at all.
default_base = "312"
default_venv = "dev"
venv_default_packages = ["ipython", "ruff", "ipykernel"]
vscode_flavor = "microsoft"
extension_gallery = "https://openvsx.corp.example/vscode"
vscode_extensions = [
    "ms-python.python",
    "ms-python.vscode-pylance",
    "ms-python.debugpy",
    "ms-toolsai.jupyter",
    "charliermarsh.ruff",
]
```

**`seedling.conf`** carries everything that must be true *before* seed-cli
exists — the share paths, TLS, and the multi-user layout:

```sh
# seedling.conf -- shipped in the copy on the share.

# Install from the share itself: a directory, not a git URL, so neither git
# nor a network is needed to install, or to `seed update-commands` later.
SEEDLING_REPO_URL="S:\seedling\seedling"

# One root, a private folder per person. The {user} token is also what
# enables the elevated admin-* commands for cross-user teardown.
SEEDLING_HOME_DIR="S:\users\{user}\seedling"

# The three offline sources the bundle provides.
SEEDLING_PYTHON_MIRROR="S:\seedling\python-builds"
SEEDLING_PACKAGE_INDEX="S:\seedling\wheels"
SEEDLING_CONDA_CHANNEL="S:\seedling\conda-channel"

# The editor build and extension set the BUNDLE contains -- decided here, on
# the build machine, not in the profile.
SEEDLING_VSCODE_FLAVOR="microsoft"
SEEDLING_EXTENSION_GALLERY="https://openvsx.corp.example/vscode"
SEEDLING_VSCODE_EXTENSIONS="ms-python.python,ms-python.vscode-pylance,ms-python.debugpy,ms-toolsai.jupyter,charliermarsh.ruff"

# A TLS-inspecting proxy re-signs HTTPS here, so the corporate root goes in
# vendor/certs/ and the installer trusts it for uv, git and seedling's own
# downloads. Set this to "true" instead if IT installed the CA machine-wide.
SEEDLING_NATIVE_TLS="false"

# Apply the profile automatically at install.
SEEDLING_PROFILE="seedling-profile.toml"
```

**Building it**, once, on a connected machine:

```
build-offline.cmd --profile seedling-profile.toml ^
                  --python 3.12,3.11 ^
                  --tools ripgrep,pandoc,gh ^
                  --packages spyder ^
                  --mingit ^
                  --deploy-root "S:\seedling" ^
                  --accept-third-party-terms
```

**What each piece buys**

| Piece | What it makes work with no internet |
|---|---|
| `python-builds/` | `seed python 3.12` — interpreters |
| `wheels/` | `seed install`, every venv's packages, **and `seed app-install`** |
| `conda-channel/` + vendored micromamba | `seed tool-install ripgrep` |
| `vendor/vscode/` | VS Code and its extensions, pre-seeded |
| `vendor/git/` (`--mingit`) | `seed repo-clone` on Windows with no system git |
| `vendor/certs/` | HTTPS through a TLS-inspecting proxy |
| `vendor/uv/` | all of it — uv itself is bundled |

**The parts worth getting right**

- **`--packages spyder`** is what makes the Spyder half of `editor` work.
  Spyder is a PyPI application, so it resolves from `wheels/` like anything
  else — there is no separate artifact for it, but its wheels do have to be
  staged. Without this, `seed apply` reaches the Spyder step and finds
  nothing to install from.
- **`--deploy-root`** writes the bundle's `seedling.conf` with the paths the
  *target* will see, which are not where you built it. Get it wrong and every
  path in the shipped conf points at your build machine.
- **`extension_gallery` appears in both files on purpose.** The conf value is
  what the bundle is built against; the profile value is what lands in each
  user's settings afterwards.
- **Verify before carrying it in.** The build finishes by installing from the
  finished bundle with the network refused and a cold cache. Re-run that
  against the copy on the share to prove the transfer was complete too:

  ```
  build-offline.cmd --verify-only -o S:\seedling
  ```

- **`MANIFEST.json`** records every component, its source, its licence, and
  whether it was staged — the file to hand a security review rather than
  reconstructing the answer.

**What still needs the internet:** nothing, once the bundle is on the share.
Users install from `S:\seedling\seedling`, `seed apply` provisions entirely
from the bundled sources, and `seed update-commands` re-reads that same
directory — so updating the fleet is copying a new bundle over the old one.

**What the bundle looks like**

Everything the builder can produce, plus the one folder it can't:

```
offline-bundle/                       -> copied to S:\seedling
├── MANIFEST.json                     every component, its source and licence
├── seedling/                         users run install.cmd from here
│   ├── install.cmd                   what users actually run
│   ├── installers/                   install.ps1, install.sh
│   ├── seedling.conf                 the conf above, --deploy-root applied
│   ├── seedling-profile.toml         the profile above
│   ├── src/                          seedling's own source
│   └── vendor/
│       ├── uv/
│       │   ├── uv.exe
│       │   └── uvx.exe
│       ├── vscode/
│       │   └── app/                  official VS Code + extensions
│       │       ├── Code.exe
│       │       ├── bin/code.cmd
│       │       └── data/             settings + installed extensions
│       ├── micromamba/
│       │   └── micromamba.exe
│       ├── git/                      MinGit, from --mingit
│       │   ├── cmd/git.exe
│       │   └── mingw64/
│       └── certs/                    <- YOU fill this one
│           ├── corp-root-ca.pem
│           └── corp-issuing-ca.pem
├── python-builds/
│   └── 20250115/                     the release tag uv asked for
│       ├── cpython-3.12.8+2025...-x86_64-pc-windows-msvc-install_only.tar.gz
│       └── cpython-3.11.11+2025...-x86_64-pc-windows-msvc-install_only.tar.gz
├── wheels/                           flat, one folder, every interpreter
│   ├── hatchling-1.27.0-py3-none-any.whl
│   ├── spyder-6.1.5-py3-none-any.whl
│   ├── PyQt5-5.15.11-cp38-abi3-win_amd64.whl
│   ├── numpy-2.1.3-cp312-cp312-win_amd64.whl
│   ├── numpy-2.1.3-cp311-cp311-win_amd64.whl      <- per-interpreter
│   └── ... a few hundred more
└── conda-channel/
    ├── noarch/repodata.json
    └── win-64/
        ├── repodata.json             synthesized from the solve
        ├── ripgrep-14.1.1-h.....conda
        ├── pandoc-3.5-h.....conda
        └── gh-2.63.2-h.....conda
```

Where each lands on the target:

| Bundle folder | Installed to |
|---|---|
| `vendor/uv/` | `system/bin/` |
| `vendor/micromamba/` | `system/bin/` |
| `vendor/vscode/` | `extensions/vscode/` |
| `vendor/git/` | `extensions/git/` |
| `vendor/certs/` | concatenated into `system/certs/ca-bundle.pem` |

Note `numpy` appearing twice: the wheel set is resolved **once per mirrored
interpreter**, because compiled dependencies ship `cp312`/`cp311`-tagged
wheels. A flat folder holds every tag happily, and this is what makes
`seed venv --python 311` work offline.

**What a cert file looks like.** Any PEM-encoded certificate, one or more per
file. The installer concatenates *every* `.pem` and `.crt` in the folder into
`~/seedling/system/certs/ca-bundle.pem`, so a root and an intermediate can be
separate files:

```
vendor/certs/
├── corp-root-ca.pem
└── corp-issuing-ca.pem
```

```
-----BEGIN CERTIFICATE-----
MIIDdzCCAl+gAwIBAgIEAgAAuTANBgkqhkiG9w0BAQUFADBaMQswCQYDVQQGEwJJ
... base64, usually 20-30 lines ...
c2VkbGluZyBleGFtcGxlIC0tIG5vdCBhIHJlYWwgY2VydGlmaWNhdGU=
-----END CERTIFICATE-----
```

Export it from your browser or from IT as **Base-64 encoded X.509**, not DER.
A DER file (binary, often `.cer`) gets concatenated as bytes and quietly
breaks the bundle — if HTTPS fails after install, check this first. The bundle
is rebuilt on every install, so rotating a certificate is a re-run rather than
a manual edit.

Check what actually landed once a target is installed:

```
seed summary --json
seed health-check
```

---

## Just Python

No editor, no repos. For people who already have their own setup and want
seedling only for interpreters and environments.

**Assumes**

| Needs | ? | Detail |
|---|:-:|---|
| Internet on the machines | ✅ | reaches PyPI |
| Internal package index | ❌ | public PyPI |
| Official VS Code + Marketplace | ❌ | you bring your own editor |
| Spyder (from PyPI) | ❌ | you bring your own editor |
| conda-forge tools | ❌ | none |
| Corporate CA certificate | ❌ | default trust store |
| Bundled git (MinGit) | ❌ | not needed |
| A reachable git host | ❌ | no `[[repo]]` entries |
| Multi-user share root | ❌ | per-user installs |
| Offline bundle to build | ❌ | installs straight from the internet |
| **x86_64 only** | ❌ | no editor, so no Qt constraint |

```toml
# seedling-profile.toml

python = ["3.13"]

[[venv]]
name = "work"
packages = ["ipython", "requests"]
default = true
```

Omitting `editor` means `seed apply` installs none. Whether the installer
sets up VS Code is then `SEEDLING_AUTO_VSCODE`'s decision in `seedling.conf`
— set it to `"false"` for a genuinely editor-free install.

Point your own editor at the environment with the interpreter path:

```
seed which work
```

**Vendor folder:** none.

---

## Checking one before you ship it

`--preview` prints the plan and changes nothing, so a profile can be checked
on your own machine before it reaches anyone else:

```
seed apply ./seedling-profile.toml --preview
```

An invalid profile exits `2` and names the problem. That matters more than it
sounds: a profile goes to a whole fleet, so a typo should fail once for you
rather than quietly for everyone.
