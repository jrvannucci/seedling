"""GitHub-compatible heading slugs for the MyST-rendered docs.

These pages are read in TWO places -- rendered by GitHub in the repo, and
built into the docs site -- and every in-page link in them was written for
GitHub's slugger. MyST's differs on exactly the characters seedling's
headings are full of: it maps `offline-bundle.toml` to "offline-bundle-toml"
where GitHub gives "offline-bundletoml", and collapses the doubled hyphen
that dropping an "&" or an em dash leaves behind. The result was ~35
cross-page links that worked on GitHub and landed at the top of the page on
the site.

Rewriting the links would have broken them on GitHub, so the slugger moves
rather than the prose.

It lives HERE, not in conf.py, because Sphinx pickles its build environment
and a function defined in conf.py belongs to __main__ -- unpicklable, which
fails the build at the very last step, after the HTML is already written.
"""

from __future__ import annotations

import re


def github_slug(text: str) -> str:
    """Lowercase, drop everything that isn't a letter/digit/space/hyphen/
    underscore, then spaces to hyphens -- GitHub's algorithm."""
    slug = text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.UNICODE)
    return re.sub(r"\s", "-", slug)
