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

Diagrams are pre-rendered SVGs under ``docs/diagrams/``, every one of them a
hand-authored, pure-Python generator script with no dependency beyond the
stdlib and each other -- ``generate_profile_flows.py``,
``generate_command_map.py``, ``generate_family_commands.py``,
``generate_marketing_flows.py``. That makes them all safe to run on every
build, so ``_generate_diagrams`` below does exactly that: their SVGs are
always fresh, never a stale committed artifact someone forgot to regenerate
after editing a generator's data. (There used to be a third kind -- three
mermaid diagrams rendered by Node's mermaid-cli via a since-removed
``build.py`` -- but hand-authoring is no more work for something this
simple, and it means the docs build needs no mermaid/JS/CDN of any kind,
committed or not, and the pages render offline.)

Build locally:

    uv venv && uv pip install -r docs/requirements.txt
    uv run sphinx-build -b html docs docs/_build/html
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent

# Repo-root files the README links to (that aren't docs pages) point here.
# Derived from seedling's own PUBLIC_REPO rather than spelled out again, so a
# fork or a repo rename doesn't leave the docs site linking at the old owner.
# Imported straight from the source tree (no install needed), the same way
# installers/build_offline.py borrows seedling's helpers.
sys.path.insert(0, str(_REPO / "src"))
from seedling import PUBLIC_REPO  # noqa: E402

_GH_BLOB = PUBLIC_REPO.removesuffix(".git") + "/blob/main/"

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


# See docs/github_slug.py for why this exists and why it lives there. The
# path insert is what makes it importable BY NAME at unpickle time too, which
# is the whole reason it isn't defined inline here.
sys.path.insert(0, str(_HERE))
from github_slug import github_slug  # noqa: E402

myst_heading_slug_func = github_slug

# The slug function above is a function object, which Sphinx can't pickle into
# its config cache -- a warning about a cache it simply won't use, on every
# build. Nothing else about the build changes.
suppress_warnings = ["config.cache"]

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_title = "seedling"

# custom.css widens the content column and lets table cells wrap, so the
# wide reference tables (the profile comparison matrix, the command
# reference) render without a horizontal scrollbar. See the file for why
# each rule is there.
html_static_path = ["_static"]
html_css_files = ["custom.css"]


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
        "DEPLOYMENT\nPROFILES\nPROFILE-EXAMPLES\nCUSTOM-COMMANDS\nOFFLINE\n"
        "LICENSING\n```\n"
        "\n```{toctree}\n:maxdepth: 1\n:hidden:\n:caption: More\n\n"
        "DOCUMENTATION\nCONTRIBUTING\n```\n"
    )
    (_HERE / "index.md").write_text(body + toctree, encoding="utf-8")


def _generate_diagrams(*_args) -> None:
    """Regenerate every SVG diagram (command-map, per-family command
    breakdowns, profile-flow, the marketing flow diagrams embedded in
    README.md) before Sphinx reads any sources, so a build always embeds
    current output rather than a possibly-stale committed SVG. Every
    generator module is self-contained (stdlib only, aside from importing
    shared helpers from generate_profile_flows), so this adds no build
    dependency."""
    diagrams_dir = _HERE / "diagrams"
    sys.path.insert(0, str(diagrams_dir))
    import generate_command_map
    import generate_family_commands
    import generate_marketing_flows
    import generate_profile_flows

    generate_profile_flows.main()
    generate_command_map.build()
    generate_family_commands.build()
    generate_marketing_flows.build()


def setup(app):
    # config-inited fires before sources are read, so the generated index.md
    # and diagram SVGs are in place by the time Sphinx looks for them.
    app.connect("config-inited", _generate_home)
    app.connect("config-inited", _generate_diagrams)
