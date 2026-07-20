"""Sphinx configuration for the seedling documentation site.

The docs are the same Markdown the repo already ships -- MyST-Parser renders
it, so there's no second source of truth to keep in sync:

  * ``docs/index.md`` is GENERATED from the top-level ``README.md`` at build
    time (see ``_generate_home`` below), so everything in the README is on the
    docs site and the two never drift. It's git-ignored -- don't edit it.
  * The rest are rendered as-is, in two tracks: ``GUIDE`` / ``COMMANDS`` /
    ``DESIGN`` for people using seedling, ``DEPLOYMENT`` / ``OFFLINE`` for
    people deploying it. ``DOCUMENTATION.md`` is the map that routes between
    them.

Diagrams are pre-rendered SVGs under ``docs/diagrams/`` (each carrying its own
mermaid source; regenerate with ``docs/diagrams/build.py``), so the build
needs no mermaid/JS/CDN and the pages render offline.

Build locally:

    uv venv && uv pip install -r docs/requirements.txt
    uv run sphinx-build -b html docs docs/_build/html
"""

from __future__ import annotations

import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
# Repo-root files the README links to (that aren't docs pages) point here.
_GH_BLOB = "https://github.com/cryocliff/seedling/blob/main/"

project = "seedling"
author = "seedling contributors"
copyright = "seedling contributors"

extensions = [
    "myst_parser",
    "sphinx_rtd_theme",
]

# GitHub-style heading anchors so the README's and DOCUMENTATION's in-page
# "Contents" links (e.g. #command-reference) resolve.
myst_heading_anchors = 4
myst_enable_extensions = ["colon_fence", "deflist"]

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_title = "seedling"


def _generate_home(*_args) -> None:
    """Write ``docs/index.md`` from the repo README, rewriting its
    repo-relative links so they resolve on the docs site: a ``docs/`` prefix
    is stripped (those targets ARE the docs pages / diagram SVGs, siblings of
    index.md), and links to any other repo file become absolute GitHub URLs.
    External URLs and in-page anchors are left alone."""
    readme = (_REPO / "README.md").read_text(encoding="utf-8")

    def _fix(m: re.Match) -> str:
        label, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://", "#", "mailto:")):
            new = target
        elif target.startswith("docs/"):
            new = target[len("docs/"):]
        else:
            new = _GH_BLOB + target
        return f"{label}({new})"

    body = re.sub(r"(!?\[[^\]]*\])\(([^)]+)\)", _fix, readme)

    toctree = (
        "\n\n```{toctree}\n:maxdepth: 2\n:hidden:\n:caption: Using seedling\n\n"
        "GUIDE\nCOMMANDS\nDESIGN\n```\n"
        "\n```{toctree}\n:maxdepth: 2\n:hidden:\n:caption: Deploying seedling\n\n"
        "DEPLOYMENT\nPROFILES\nOFFLINE\nLICENSING\n```\n"
        "\n```{toctree}\n:maxdepth: 1\n:hidden:\n:caption: More\n\n"
        "DOCUMENTATION\nCONTRIBUTING\n```\n"
    )
    (_HERE / "index.md").write_text(body + toctree, encoding="utf-8")


def setup(app):
    # config-inited fires before sources are read, so the generated index.md
    # is in place by the time Sphinx looks for it.
    app.connect("config-inited", _generate_home)
