# Air-gapped (VSCodium)

A network with no internet, and a review that will ask what you redistributed.
Pairs with an [offline bundle](../OFFLINE.md).

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

![The full offline-bundle/ pipeline -- six sources, each staged into its own bundle folder.](../diagrams/profile-build-air-gapped-vscodium.svg)

![One origin on the target: the share. Every capability -- packages, uv, interpreters, tools, the editor, git -- comes out of that single grouped box, one labeled arrow apiece.](../diagrams/profile-pull-air-gapped-vscodium.svg)

```toml
# profile.toml -- distributed on the share, applied at install.

python = ["3.12"]

tools = ["ripgrep", "pandoc"]

editor = "vscode"

[[venv]]
name = "work"
packages = ["pandas", "numpy", "requests", "pytest"]
default = true
```

The share declares its own contents, and the profile above is checked against
them:

```toml
# offline-bundle.toml -- what the share will hold. Sits next to global.conf;
# build-offline reads it by default.

pythons = ["3.12"]

# Everything any profile may name, plus what users may `seed install` later.
# hatchling/ipython/ruff/ipykernel/pip are always bundled -- no need to list.
packages = ["pandas", "numpy", "requests", "pytest", "httpx", "openpyxl"]

tools = ["ripgrep", "pandoc"]

[editor]
flavor = "vscodium"
extensions = ["ms-python.python", "ms-toolsai.jupyter", "charliermarsh.ruff"]

[git]
mingit = true
```

Build it, checking the profile against the declaration before anything
downloads — and again against what actually landed:

```sh
build-offline.cmd --check-profile profile.toml --deploy-root "S:\seedling"
```

**Which editor build gets staged is decided on the build machine.** The
bundler stages the editor *before* any profile is applied, and reads the
build machine's own seedling settings to do it — so the conf you distribute
sets it for your users, and `[editor] flavor` above records the intent:

```sh
# global.conf, in the copy you distribute
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
  [the next example](air-gapped-vs-code.md).
- **Set the flavor on the build machine too, not only in this conf.** The
  bundler stages whichever editor the *build machine's own* seedling settings
  name (`seed config get vscode_flavor`), because it drives seedling's own
  installer — a conf it never installed from doesn't reach it. Build with the
  flavor unset and you stage the **official** build and Marketplace
  extensions: the restricted components this whole example exists to avoid.
  Either install seedling on the builder from this copy (the installer seeds
  the setting from the conf) or run `seed config set vscode_flavor vscodium`
  first. See [the note in OFFLINE.md](../OFFLINE.md#7-vs-code-optional).
- **`offline-bundle.toml` declares the share; the profile conforms to it.**
  It lists more than this profile needs (`httpx`, `openpyxl`) because a user
  on an isolated network can't add one later. `--check-profile` proves the
  profile is a subset — a package it names that the share won't carry fails
  the build on the connected machine, and
  [`seed profile-check`](../commands/status.md#seed-profile-check-profile---bundle-path)
  answers the same question for a profile written later, from inside.
  Only `[editor] flavor`/`extensions` are declarative for now — see the
  previous bullet.
- Nothing here mentions the share's paths: those live in `global.conf`
  (`SEEDLING_PACKAGE_INDEX` and friends), which is install-time configuration
  a profile deliberately can't override.

**What the bundle looks like**

```
offline-bundle/
├── MANIFEST.json            what was staged, and under what licence
├── seedling/                users run install.cmd from here
│   ├── global.conf            written with your --deploy-root paths
│   ├── offline-bundle.toml    what the share holds (read back by profile-check)
│   ├── profile.toml           the profile above
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
