# Profile examples

Complete, working [deployment profiles](PROFILES.md) for real situations.
Each one is a whole file — copy it, change the names, ship it. For what every
key means, see the [profile reference](PROFILES.md#reference).

Save any of these as `profile.toml` next to `global.conf` in the
copy you distribute, and everyone who installs from it gets that environment.

| Example | What it's for | Offline | Index | VS Code | Spyder | conda-forge | CA certs | Bundle | x86_64 only |
| --- | --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| **[Research group](profile-examples/research-group.md)** | Spyder, two venvs | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |
| **[Software team](profile-examples/software-team.md)** | VS Code, repos cloned | ❌ | ⚠️ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **[Both editors](profile-examples/both-editors.md)** | One shared venv | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| **[Classroom](profile-examples/classroom.md)** | Pinned, reproducible | ❌ | ❌ | ❌ | ✅ | ❌ | ⚠️ | ⚠️ | ✅ |
| **[Internal mirrors](profile-examples/internal-mirrors.md)** | No bundle needed | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ |
| **[Internal PyPI only](profile-examples/internal-pypi-only.md)** | Partial bundle | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ⚠️ | ✅ |
| **[Air-gapped (VSCodium)](profile-examples/air-gapped-vscodium.md)** | No redistribution rights | ✅ | ✅ | ❌ | ❌ | ✅ | ⚠️ | ✅ | ❌ |
| **[Air-gapped (VS Code)](profile-examples/air-gapped-vs-code.md)** | Keeps Pylance | ✅ | ✅ | ✅ | ❌ | ✅ | ⚠️ | ✅ | ❌ |
| **[Air-gapped (everything)](profile-examples/air-gapped-everything.md)** | Every capability at once | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **[Just Python](profile-examples/just-python.md)** | Interpreters and venvs only | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

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

```{toctree}
:maxdepth: 1
:hidden:

profile-examples/research-group
profile-examples/software-team
profile-examples/both-editors
profile-examples/classroom
profile-examples/internal-mirrors
profile-examples/internal-pypi-only
profile-examples/air-gapped-vscodium
profile-examples/air-gapped-vs-code
profile-examples/air-gapped-everything
profile-examples/just-python
```

---

## Checking one before you ship it

`--preview` prints the plan and changes nothing, so a profile can be checked
on your own machine before it reaches anyone else:

```
seed apply ./profile.toml --preview
```

An invalid profile exits `2` and names the problem. That matters more than it
sounds: a profile goes to a whole fleet, so a typo should fail once for you
rather than quietly for everyone.
