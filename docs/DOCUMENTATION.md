# seedling documentation

seedling is a single `seed` command that wraps [`uv`](https://astral.sh/uv)
and keeps every Python interpreter, virtual environment, VS Code install,
and cloned repo it manages inside one folder: `~/seedling`. Nothing it does
touches your system Python, `%APPDATA%`, `~/.vscode`, or any of the other
places these tools normally scatter files into.

This page is the map. The documentation is split into two tracks — one for
people **using** seedling, one for people **deploying** it to others.

---

## Using seedling

Start here if seedling is installed on your own machine, or about to be.

| | |
|---|---|
| **[Using seedling](GUIDE.md)** | How installation works, the folder layout, why `seed` is a shell function, the update model, uninstalling, and troubleshooting. |
| **[Command reference](COMMANDS.md)** | Every command and flag in detail. |
| **[Design and safety](DESIGN.md)** | Why deletion is so defensive, what gets logged, how downloads are verified, and how to run seedling unattended. |

---

## Deploying seedling

Start here if you are setting seedling up **for other people** — a team, a
lab, a restricted network.

| | |
|---|---|
| **[Deployment guide](DEPLOYMENT.md)** | `seedling.conf`, shared-machine installs, the elevated `admin-*` teardown family, a rollout checklist, and the answers to a security review. |
| **[Deployment profiles](PROFILES.md)** | One file describing the environment your users should end up with — interpreters, named venvs and their packages, repos — applied at install and re-applied with `seed apply`. |
| **[Offline / air-gapped networks](OFFLINE.md)** | Running with no internet at all: mirrors, vendored binaries, wheel directories, corporate CAs, and `build-offline.cmd`. |
| **[Licensing and redistribution](LICENSING.md)** | seedling ships no third-party software. What it downloads, under what terms, and what changes when you stage a bundle for a share. |

---

## Working on seedling itself

**[Contributor guide](CONTRIBUTING.md)** — the edit → `seed update-commands`
loop (including `--from-branch` for tracking a fork's branch), the source
layout, and running the tests.

---

## Quick answers

| I want to… | Go to |
|---|---|
| Install seedling | [Using seedling → How installation works](GUIDE.md#how-installation-works) |
| Look up a command | [Command reference](COMMANDS.md) |
| Understand where files go | [Using seedling → The folder layout](GUIDE.md#the-folder-layout) |
| Update or repair an install | [Using seedling → The update model](GUIDE.md#the-update-model) |
| Remove seedling completely | [Using seedling → Uninstalling](GUIDE.md#uninstalling) |
| Fix something that broke | [Using seedling → Troubleshooting](GUIDE.md#troubleshooting) |
| Standardize a team's setup | [Deployment profiles](PROFILES.md) |
| Give everyone the same venvs and packages | [Deployment profiles](PROFILES.md) |
| Point installs at an internal source | [Deployment guide → `seedling.conf`](DEPLOYMENT.md#deployment-configuration-seedlingconf) |
| Install with no internet | [Offline networks](OFFLINE.md) |
| Put many users on one machine | [Deployment guide → Shared-machine installs](DEPLOYMENT.md#shared-machine-multi-user-installs) |
| Tear down another user's install | [Deployment guide → Admin commands](DEPLOYMENT.md#admin-commands-shared-root-teardown) |
| Answer a security questionnaire | [Deployment guide → What a security review will ask](DEPLOYMENT.md#what-a-security-review-will-ask) |
| Know what I'm allowed to redistribute | [Licensing and redistribution](LICENSING.md) |
| Know what seedling can't do | [Using seedling → Known limits](GUIDE.md#known-limits) |
