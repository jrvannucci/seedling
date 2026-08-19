# Command reference

Every `seed` command and flag, as currently implemented. For the guided
tour, start with **[Using seedling](GUIDE.md)**.

```{raw} html
:file: _include/command-explorer.html
```

---

Command names follow two rules: **a bare noun is the primary action and
`noun-verb` is management of that thing** (`python` installs, `python-list`
lists) — except **everything that deletes is a `remove-*` command**, so every
destructive action reads the same way (`remove-venv`, `remove-python`,
`remove-repo`, `remove-user`) and they group together in help's Danger Zone.

Grouped the same way `seed help` groups them, and split across a page per
group below — one 1,500-line reference was worse to search than eleven
shorter ones:

| Family | Commands |
|---|---|
| **[Python interpreters](commands/interpreters.md)** *(structural — the base installs venvs are built from)* | `python [ver]` *(install)*, `python-list`, `remove-python` |
| **[Venvs & packages](commands/venvs-and-packages.md)** *(day-to-day environment work)* | `venv <name>` *(create)*, `venv-list`, `activate`, `deactivate`, `run`, `which`, `venv-default`, `auto-activate`, `install`, `uninstall`, `package-list`, `show`, `remove-venv`, `remove-venv-all` |
| **[Python applications](commands/python-apps.md)** *(run, not imported — each in its own env)* | `tool-install <name>` *(install)*, `tool-list`, `tool-remove` |
| **[Command-line tools from conda-forge](commands/conda-forge-tools.md)** *(the non-Python tools)* | `forge <cmd>` *(run)*, `forge-install <name>` *(install)*, `forge-list`, `forge-remove` |
| **[Offline utilities](commands/offline-utilities.md)** *(stage packages/tools for an air-gapped machine)* | `download-whls <package...>`, `download-requirements <req.txt>`, `download-forge <name...>` |
| **[Repos](commands/repos.md)** | `repo-clone`, `repo-list`, `repo-cd`, `repo-open`, `repo-install`, `remove-repo` |
| **[Editors & IDEs](commands/editors.md)** *(installed on demand)* | `vscode`, `vscode-repo`, `spyder`, `spyder-repo` |
| **[Custom commands](commands/custom.md)** *(your organization's own — see [CUSTOM-COMMANDS.md](CUSTOM-COMMANDS.md))* | `custom <name>` *(run)* |
| **[Fleet & lifecycle](commands/lifecycle.md)** | `kill-processes`, `update-commands`, `remove-user`, `purge`, `purge-and-reinstall` |
| **[Status & profiles](commands/status.md)** | `summary`, `health-check`, `logs-viewer`, `config`, `apply`, `where`, `--version` |
| **[Scripting & automation](commands/scripting-and-automation.md)** *(the machine-facing surface, in one place)* | `seed run`, `seed which`, `--json`, never blocking on a prompt, concurrency |

```{toctree}
:maxdepth: 1
:hidden:

commands/interpreters
commands/venvs-and-packages
commands/python-apps
commands/conda-forge-tools
commands/offline-utilities
commands/repos
commands/editors
commands/custom
commands/lifecycle
commands/status
commands/scripting-and-automation
```
