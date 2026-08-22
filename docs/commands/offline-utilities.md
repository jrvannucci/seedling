# Offline utilities

![What each offline-staging command does: download-whls, download-requirements, download-forge, and upload-whls.](../diagrams/commands-offline-utilities.svg)

## `seed download-forge <name>[=version]... [--dest <dir>]`

The conda-forge counterpart of `download-whls`: on a connected machine, resolve
a tool **and all its dependencies** and write them into a local **conda
channel** — a directory you carry to an air-gapped machine (or a share) and
install from offline.

```
(connected)  seed download-forge ripgrep pandoc
(copy the ./conda-channel folder to the offline machine or a share)
(offline)    seed config set conda_channel <that-folder>
             seed forge-install ripgrep
```

seedling solves the request with micromamba, downloads each package
(checksum-verified), and synthesizes the channel's `repodata.json` from the
solve — so no `conda index` or network is needed on the offline side. When
`conda_channel` points at a local folder, `forge-install` runs fully offline
automatically.

Lands in `./conda-channel` unless you pass `--dest`. Pin versions with `=`
(`seed download-forge pandoc=3.2`).

## `seed download-whls <package...>`

Downloads a package **and all of its dependencies** as `.whl` files (plus any
source archives) into a flat folder — the offline-bundle builder. Run it on a
connected machine, carry the folder to an air-gapped one, and point
`package_index` at it:

```
seed download-whls pandas
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
seed download-whls numpy --only-binary=:all: \
    --platform manylinux2014_x86_64 --python-version 312 --dest ./linux-wheels
```

If `package_index` (an Artifactory/Nexus/devpi URL, or a wheels directory) or
`ca_cert` are configured, they're applied automatically as `--index-url` /
`--find-links --no-index` / `--cert`, so a bundle can itself be built from an
internal index without setting any environment variables.

## `seed download-requirements <requirements.txt>`

Same as `download-whls`, but reads package specifiers from a `requirements.txt`
(forwarded to `pip download -r`). Everything else — default `./wheelhouse`
destination, flag passthrough, `package_index`/`ca_cert` handling — is identical.

```
seed download-requirements requirements.txt
seed download-requirements requirements.txt --dest ./bundle --python-version 311
```

---

## `seed whl-licenses <dir> [--all] [--json] [--fail-on FAMILY,...]`

What is every wheel in a directory licensed under? Point it at a wheelhouse
from `seed download-whls`, or at an offline bundle (its `wheels/` is found
for you).

This is the one an admin runs **before** copying a bundle to a share:

```
seed whl-licenses S:	ools\wheels
```

```
Licences in S:	ools\wheels  (170 packages)

  copyleft               2   recipients get source and the same rights; matters when distributing outside your organization
  copyleft-weak          7   publish changes if you MODIFY the library itself
  unknown                1   nobody declared one; resolve it by hand
  permissive           160   keep the copyright notice and licence text with the copy

Needs a decision (10):
  copyleft         PyQt6              6.7.1     GPL-3.0-only        License-Expression
  copyleft         PyQt6-WebEngine    6.7.0     GPL-3.0-only        License-Expression
  ...
  unknown          clr_loader         0.2.6     -                   none
```

The two GPL entries are Spyder's dependency chain: any profile with
`editor = "spyder"` puts them in the wheelhouse. That is exactly the kind of
thing worth knowing on the connected machine rather than after the share is
built.

## `seed forge-licenses [<channel-dir>] [--all] [--json] [--fail-on ...]`

The same question for a bundled conda channel, read from its `repodata.json`
(the archives are zstd-compressed, which the standard library can't open —
and the licence is in the index anyway). With no argument it uses the
configured `conda_channel` when that's a local directory.

Three commands, one report, because the question arrives from three
directions: a developer asking what they're running, an admin asking what is
about to go onto a share, and the same admin asking it of the non-Python
half. All take the same flags:

- `--all` lists every package rather than just the ones needing a decision.
- `--json` gives the machine-readable form (schema-versioned, like every
  other read command).
- `--fail-on copyleft,unknown` exits `1` if anything lands in those families
  — a policy you can put in CI, or run before copying a bundle to a share.

Nothing here touches the network, and nothing is installed to answer it: a
wheel is a zip and its `METADATA` is plain key-value text. The licence is
resolved from the best source each package offers, and the report says which
one it used — `License-Expression` (PEP 639, SPDX, unambiguous), a
`License ::` classifier (coarser), or the free-text `License` field (whatever
the author typed). A package declaring none is reported as `unknown` rather
than assumed permissive.

Families, most serious first: `proprietary`, `copyleft-network` (AGPL),
`copyleft` (GPL), `copyleft-weak` (LGPL/MPL), `unknown`, `unclassified`,
`public-domain`, `permissive`. What matters for an offline bundle is that
copying wheels onto a share is *redistribution*, which is the act licences
govern — see [LICENSING.md](../LICENSING.md).

## `seed upload-whls <dir> [--repository-url URL]`

The other direction: publish a directory of wheels **into** your
organization's package index. For the networks where the air gap has a door —
an internal PyPI (Artifactory / Nexus / devpi) that users *can* reach, which
just doesn't have the packages yet. Resolve the set on a connected machine,
publish it once, and every user installs from the index they already have:
no share to mount, no directory index to configure.

```
seed download-whls pandas polars        # resolve on a connected machine
seed upload-whls ./wheelhouse           # publish to the internal index
```

It also takes a bundle's wheel folder directly, which is the
[internal-PyPI deployment](../profile-examples/internal-pypi-only.md) in one
line:

```
seed upload-whls S:\seedling\wheels
```

- Uploads every `.whl` **and** source archive in the directory, ignoring
  anything else. Non-recursive: one flat wheelhouse, like `pip download`
  writes.
- Runs `uvx twine upload` — the same ephemeral-tool pattern as
  `download-whls`, so nothing is installed permanently.
- `--repository-url` overrides the `package_upload_url` setting for one run.
  Unknown flags pass straight through to twine (`--skip-existing` is the
  useful one when re-publishing a mostly-unchanged set).
- `ca_cert` is honored, since an internal index behind a TLS-inspecting proxy
  is exactly where this runs.

**The upload URL is its own setting, not `package_index`.** Servers that do
both use different paths for reading and writing, so one can't be derived
from the other:

```
package_index        https://pypi.corp.example/api/pypi/pypi/simple    (read)
package_upload_url   https://pypi.corp.example/api/pypi/pypi-local/    (write)
```

**Credentials.** `package_upload_token` is used if set; otherwise twine's own
`TWINE_USERNAME`/`TWINE_PASSWORD` or `~/.pypirc` apply, and twine prompts if
it finds neither. The token is passed to twine through the environment,
never on a command line — a command line is visible to `ps`, lands in shell
history, and is echoed into seedling's own log — and it is masked wherever
seedling prints settings.

> **A publish token is an admin credential.** Every value in `global.conf` is
> seeded into every user's `settings.json` at install time, so putting
> `SEEDLING_PACKAGE_UPLOAD_TOKEN` in the copy you distribute grants your
> whole fleet write access to the index. Leave it empty there and set it only
> on the machine that publishes:
>
> ```
> seed config set package_upload_token <token>
> ```

Exit codes: `0` published, `1` nothing to upload, no URL configured, or twine
failed (a token without write permission, the wrong endpoint, or a
distribution that already exists — twine refuses to overwrite by default).
