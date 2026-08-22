# seedling 🌱

[![CI](https://github.com/jrvannucci/seedling/actions/workflows/ci.yml/badge.svg)](https://github.com/jrvannucci/seedling/actions/workflows/ci.yml)

![seedling: a tidy, single-folder global Python distributor and local environment manager -- zero-touch config, offline-first, safe by default, built for scale, and scriptable, all on top of one removable folder.](docs/diagrams/mission.svg)

**Go from nothing to writing Python in one command.** No prior setup, no
tools to install first, nothing to learn about how Python is packaged. Run one
line, open a terminal, type `python`. Everything lives in a single folder you
can delete — `seed purge` leaves your machine exactly as it was.

---

## Why this is easier

![The usual way means hours of setup before your first line of code; with seedling, one command and you're writing Python.](docs/diagrams/why-vs-usual.svg)

Setting Python up yourself means choosing an installer, learning virtual
environments, wiring up PATH, and finding an editor — before you write a line
of code. Every one of those is a place to get stuck, and they're all handled
here:

- **You don't need Python to install it.** The one-liner brings its own.
- **An environment is already waiting.** Open a terminal and `python` works,
  in a venv, with common packages in it.
- **An editor comes with it.** `seed vscode` — or `seed spyder` — already
  wired to the environment you're in.
- **It's one folder, and it's undoable.** Nothing touches the registry,
  `%APPDATA%`, or `~/.local`. One command removes all of it.

Already fluent in Python? The same install gives you every interpreter, venv
and cloned repo in one predictable place instead of sprawled across your
machine — and it's the fastest way to hand a whole team an identical setup.

---

## Install

Nothing needs to be pre-installed — not Python, not uv, nothing.

**macOS / Linux:**
```sh
curl -fsSL https://raw.githubusercontent.com/jrvannucci/seedling/main/installers/install.sh | sh
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/jrvannucci/seedling/main/installers/install.ps1 | iex
```

![Run the one-liner, seedling sets up everything Python needs, open a new terminal, and python just works.](docs/diagrams/install-flow.svg)

> On Windows you can also download the repo and double-click `GET_STARTED/install.cmd`.
> Skip the ready-made environment with `SEEDLING_AUTO_SETUP=false`.
>
> **Given a profile by your admin?** Point the same one-liner at it and you get
> their exact environment in one step:
> `curl -fsSL ... | SEEDLING_PROFILE=./team.toml sh`. See
> [deployment profiles](docs/PROFILES.md).

---

## The everyday workflow

Open a new terminal. You're already in a working environment, so the loop is
short:

```sh
python                     # the newest Python, in a venv, ready
seed install requests      # add packages to the environment you're in
seed venv myproject        # a separate environment for a separate project
seed activate myproject    # switch to it (new terminals remember the default)
seed run -- pytest         # run something in a venv without switching
```

That's the whole day-to-day. The rest is there when you need it: `seed vscode`
opens the bundled editor, `seed repo-clone <url>` pulls a project into
`~/seedling/repo`, `seed summary` shows everything installed, and
`seed health-check` verifies it.

Names are predictable: a bare noun does the thing (`python` installs, `venv`
creates), `noun-list` shows them, and **anything that deletes is `remove-*`**.

🔎 **[Browse every command](docs/COMMANDS.md)** — all 59 in one filterable
list; click any one to open its full documentation.

### It changes only when you ask

![Install with the one-liner, use seed to manage venvs and packages, update only when you ask, and uninstall cleanly with seed purge.](docs/diagrams/lifecycle.svg)

seedling runs from its own private copy of the source in `~/seedling`. New
commits upstream change nothing until you run `seed update-commands`. When
you're done with it, `seed purge` removes the folder and the shell hook.

---

## For organizations 🏢

seedling is also built to be **deployed** — by one person, to everyone else,
including on networks where the usual Python setup path doesn't work at all.

- **No internet, no admin rights.** Point installs at a self-hosted git
  server, an internal index, or a plain file share. For a fully disconnected
  network, `GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd` assembles the whole bundle — uv,
  interpreters, wheels, the editor — on a connected machine.
- **Nothing for your users to configure.** Set the values once in
  [`global.conf`](GET_STARTED/global.conf) in the copy you distribute; everyone who
  installs from it inherits them.
- **One folder defines the environments.** Each profile in
  `installation-profile/` lists the interpreters, venvs, packages and repos a
  group should end up with, and says who gets it — one for everyone, others
  opt-in by name.
- **Auditable and reversible.** Every command is logged in plain text,
  downloads are checksum-verified, `--preview` shows what a removal would
  delete, and nothing third-party is vendored — each bundle carries a
  `MANIFEST.json` naming every component and its licence, down to each
  individual wheel.

📘 Start with the **[deployment guide](docs/DEPLOYMENT.md)**, or
**[offline networks](docs/OFFLINE.md)** for a disconnected fleet.

---

## Documentation

| | |
|---|---|
| [Using seedling](docs/GUIDE.md) | Installing, the folder layout, the update model, troubleshooting |
| [Command reference](docs/COMMANDS.md) | Every command and flag |
| [Design and safety](docs/DESIGN.md) | Why deletion is defensive, what's logged, how downloads are verified |
| [Deployment guide](docs/DEPLOYMENT.md) | `global.conf`, shared machines, rollout, security review |
| [Deployment profiles](docs/PROFILES.md) | The file describing what users end up with, and who gets it |
| [Profile examples](docs/PROFILE-EXAMPLES.md) | Complete profiles: research group, software team, classroom, air-gapped fleet |
| [Custom commands](docs/CUSTOM-COMMANDS.md) | Add your organization's own verbs to `seed` |
| [Offline networks](docs/OFFLINE.md) | Running with no internet at all |
| [Licensing](docs/LICENSING.md) | What seedling downloads, and under what terms |

🗺️ Not sure where to look? The [documentation map](docs/DOCUMENTATION.md)
routes you from what you're trying to do to the right page.

**Working on seedling itself?** The
[contributor guide](docs/CONTRIBUTING.md) covers the edit →
`seed update-commands` loop, the source layout, and the tests (`uvx pytest`
from the repo root).

---

## License

Apache 2.0. seedling has no third-party runtime dependencies and bundles no
third-party software; the tools it downloads for you come from their
publishers under their own licenses — see
[THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES.md) and, for what you may
redistribute in an offline bundle, [docs/LICENSING.md](docs/LICENSING.md).
