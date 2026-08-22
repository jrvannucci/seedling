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

[distribution]
# Everyone who installs from this share gets this profile. Others in
# installation-profile/ opt in by listing users instead.
default = true

[[venv]]
name = "work"
packages = ["pandas", "numpy", "requests", "pytest"]
default = true
```

The share declares its own contents, and the profile above is checked against
them:

```toml
# offline-bundle.toml -- what the share will hold. Lives in
# GET_STARTED_OFFLINE_BUNDLE/, and the builder reads it with no arguments.

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
GET_STARTED_OFFLINE_BUNDLE/offline-bundler.cmd
```

The `[editor] flavor` above is what gets staged. `global.conf` sets the same
choice for each installed machine, and the builder refuses to build if the two
disagree:

```sh
# GET_STARTED/global.conf, in the copy you distribute
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
- **The spec decides which editor is staged**, and the build stops if
  `global.conf` disagrees with it. Staging the official build here would mean
  redistributing the restricted components this example exists to avoid, so
  the mismatch is worth failing over rather than warning about.
- **`offline-bundle.toml` declares the share; the profile conforms to it.**
  It lists more than this profile needs (`httpx`, `openpyxl`) because a user
  on an isolated network can't add one later. `--check-profile` proves the
  profile is a subset — a package it names that the share won't carry fails
  the build on the connected machine, and
  [`seed profile-check`](../commands/status.md#seed-profile-check-profile---bundle-path)
  answers the same question for a profile written later, from inside.
- Nothing here mentions the share's paths: those live in `global.conf`
  (`SEEDLING_PACKAGE_INDEX` and friends), which is install-time configuration
  a profile deliberately can't override.

**What the bundle looks like**

```
offline-bundle/
├── MANIFEST.json            what was staged, and under what licence
├── seedling/                users run GET_STARTED/install.cmd from here
│   ├── GET_STARTED/                 install.cmd, and global.conf written
│   │                                with your --deploy-root paths
│   ├── GET_STARTED_OFFLINE_BUNDLE/  offline-bundle.toml -- what the share
│   │                                holds, read back by seed profile-check
│   ├── installation-profile/        the profile above
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
