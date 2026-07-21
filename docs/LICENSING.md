# Licensing and redistribution

**Short version: seedling is a fetcher, not a distributor. It ships no
third-party software. When you stage a bundle for an offline network, you
are the one redistributing — and you are responsible for holding the rights
to do so.**

This page states seedling's position so it is on the record, and tells you
which components carry restrictions worth checking before you distribute
them internally.

> **seedling's own code is [Apache-2.0](https://github.com/cryocliff/seedling/blob/main/LICENSE)**
> (patent grant included), with no third-party runtime dependencies. This
> page is about the *other* software seedling downloads for you; for the
> component inventory see
> [THIRD-PARTY-NOTICES](https://github.com/cryocliff/seedling/blob/main/THIRD-PARTY-NOTICES.md).

---

## Contents

- [seedling's position](#seedlings-position)
- [What seedling downloads, and under what terms](#what-seedling-downloads-and-under-what-terms)
- [What changes when you build an offline bundle](#what-changes-when-you-build-an-offline-bundle)
- [The openly-licensed path](#the-openly-licensed-path)
- [The bundle manifest](#the-bundle-manifest)

---

## seedling's position

1. **seedling contains no third-party software.** Nothing is vendored into
   this repository — no interpreters, no editor, no binaries of any kind.
   `vendor/` and `offline-bundle/` are git-ignored and always empty in a
   fresh clone.
2. **Downloads come from the publisher, at your direction.** When you run
   `seed python` or `seed vscode`, seedling fetches from the vendor's own
   servers. Your relationship is with that vendor, on their terms, exactly
   as if you had downloaded it yourself.
3. **seedling grants you no rights to anything it downloads,** and makes no
   representation that you have them. Whether you may install, copy, or
   redistribute a given component is between you and its publisher.
4. **If you redistribute, that is your act, not seedling's.** Copying a
   bundle to a share, imaging it onto machines, or handing it to another
   team are all distribution. seedling is the tool you used; the
   distribution is yours.

This is the same posture package managers take: Homebrew casks download from
vendor servers rather than mirroring them, and the AUR ships build recipes
rather than binaries. It is a deliberate design choice, not an oversight.

> **What this does and does not do.** It keeps seedling out of the
> redistribution chain and makes sure the choice is yours and visible. It
> does **not** grant you a licence, and it is not a defence if you stage
> something you had no right to stage. If you are unsure, that is a question
> for your organization's legal or compliance function — not one this
> document can answer.

---

## What seedling downloads, and under what terms

| Component | Source | Licence | Redistribution |
|---|---|---|---|
| [uv](https://astral.sh/uv) | astral-sh releases | Apache-2.0 / MIT | Permissive |
| [Python interpreters](https://github.com/astral-sh/python-build-standalone) | python-build-standalone | PSF and assorted upstream | Permissive |
| Python packages | PyPI or your index | Per package | Per package — check your set |
| [MinGit](https://github.com/git-for-windows/git) *(Windows, optional)* | git-for-windows | **GPL-2.0** | Copyleft — carries a source-offer obligation |
| [Visual Studio Code](https://code.visualstudio.com) *(optional)* | Microsoft | **Proprietary** | **Restricted** — the MIT licence on `microsoft/vscode` covers the source, not these branded builds |
| Marketplace extensions *(optional)* | Visual Studio Marketplace | Per extension, under the Marketplace's own Terms of Use | **Restricted** |
| [VSCodium](https://vscodium.com) *(optional alternative)* | VSCodium releases | MIT | Permissive |
| [Open VSX](https://open-vsx.org) extensions *(optional alternative)* | Eclipse Foundation | Per extension, openly licensed | Permissive |

Everything seedling needs to do its actual job — manage interpreters, venvs,
and packages — is in the permissive rows. Every restricted row is optional.

---

## What changes when you build an offline bundle

Day-to-day use raises few questions: each machine downloads from the vendor
for itself, which is what the vendor's terms anticipate.

`build-offline.cmd` is different. It assembles those downloads into a folder
you carry to a share, from which many machines install. **That is
redistribution**, and it is the point at which the restricted rows above
start to matter.

Because of that, the builder asks you to acknowledge the restricted
components before staging any of them:

```
build-offline.cmd                            # prompts before staging them
build-offline.cmd --accept-third-party-terms # for unattended/CI builds
```

`--yes` deliberately does **not** answer this prompt. It exists to skip
routine confirmations; acknowledging someone else's licence terms is not
routine, so it needs its own explicit flag.

A bundle containing only permissively-licensed components — the default when
you pass `--no-vscode` and omit `--mingit` — is not gated at all.

---

## The openly-licensed path

If you would rather not have this conversation with your legal team, you can
avoid the restricted components entirely:

```
SEEDLING_VSCODE_FLAVOR="vscodium"
```

VSCodium is the same source as VS Code, built without Microsoft's branding
and telemetry, under the MIT licence — and it already points at Open VSX,
whose content is openly licensed. Combined with omitting MinGit (or relying
on the system git your machines already have), this yields a bundle you can
redistribute internally without asking anyone's permission.

The cost is Pylance, which is licensed to official Microsoft products only
and therefore cannot be on Open VSX. See
[Choosing an editor build and registry](DEPLOYMENT.md#choosing-an-editor-build-and-registry)
for the full tradeoff.

---

## The bundle manifest

Every bundle `build-offline.cmd` produces carries a `MANIFEST.json` at its
root, recording what was staged: each component's version, the URL it came
from, its licence, and its redistribution category.

It exists so you can answer "what is in this thing, and under what terms"
without re-deriving it by hand — for a security review, an internal
compliance process, or an SBOM pipeline. It is written even when the build
is partial, so it reflects what is actually in the folder rather than what
was intended.

```
offline-bundle/
├── MANIFEST.json        <- what was staged, and under what licence
├── seedling/            <- users run install.cmd from here
├── python-builds/
└── wheels/
```
