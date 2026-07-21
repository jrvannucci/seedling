# Third-party notices

seedling is licensed under the Apache License, Version 2.0 — see
[LICENSE](LICENSE). This file documents third-party software in relation to
seedling: what it bundles (nothing), and what it downloads on your behalf.

For the redistribution question specifically — what *you* may copy onto a
share when you build an offline bundle — see
[docs/LICENSING.md](docs/LICENSING.md), which this file complements.

---

## seedling bundles no third-party code

- **seedling's runtime has no third-party dependencies.** It runs on the
  Python standard library alone (`dependencies = []` in
  [`src/pyproject.toml`](src/pyproject.toml)); there is nothing to vendor and
  nothing to attribute here.
- **Nothing third-party is committed to this repository.** The `vendor/` and
  `offline-bundle/` directories are git-ignored and empty in a fresh clone; a
  test asserts no binary payload is ever tracked.

So there is no bundled third-party software carrying its own license into
seedling's distribution.

---

## Software seedling downloads at your direction

seedling is a fetcher: at your command it downloads and manages the tools
below from their publishers. It does **not** redistribute them, and it grants
you no rights to them — your relationship is with each publisher, on their
terms. They are listed here so you know what is involved and under what
license.

| Component | Source | License |
|---|---|---|
| [uv](https://github.com/astral-sh/uv) | astral-sh releases | Apache-2.0 OR MIT |
| [Python interpreters](https://github.com/astral-sh/python-build-standalone) | python-build-standalone | PSF-2.0, and assorted upstream licenses |
| Python packages | PyPI, or your configured index | Per package — determined by what you install |
| [MinGit](https://github.com/git-for-windows/git) *(Windows, optional)* | git-for-windows | GPL-2.0 |
| [Visual Studio Code](https://code.visualstudio.com) *(optional)* | Microsoft | Microsoft Software License (proprietary) |
| Visual Studio Marketplace extensions *(optional)* | Microsoft | Per extension, under the Marketplace Terms of Use |
| [VSCodium](https://github.com/VSCodium/vscodium) *(optional alternative)* | VSCodium releases | MIT |
| [Open VSX](https://open-vsx.org) extensions *(optional alternative)* | Eclipse Foundation | Per extension, openly licensed |

Everything in the first three rows is required for seedling's core job of
managing interpreters, environments, and packages; every other row is
optional. See [docs/LICENSING.md](docs/LICENSING.md) for which of these
restrict redistribution and how `build-offline` handles them.

---

## Build and development tooling

These are used to build or develop seedling and are **not** distributed with
it or downloaded by it at runtime:

- [Hatchling](https://github.com/pypa/hatch) (MIT) — the build backend that
  produces the `seed-cli` distribution.
- The documentation site is built with [Sphinx](https://www.sphinx-doc.org)
  (BSD-2-Clause), [MyST-Parser](https://github.com/executablebooks/MyST-Parser)
  (MIT), and the [Read the Docs theme](https://github.com/readthedocs/sphinx_rtd_theme)
  (MIT); see [`docs/requirements.txt`](docs/requirements.txt).
