# The single source of truth for seedling's version: pyproject.toml reads it
# from here (dynamic = ["version"]), `seed --version` prints it, and the
# installers stamp nothing of their own. Bump this line and both follow.
__version__ = "0.8.0"

# Where seedling itself comes from, in ONE place for the same reason.
#
# Almost nothing should reach for these: an installed copy records where it
# came from as the `update_source` setting, and every runtime path (notably
# `seed update-commands` and `purge-and-reinstall`) reads THAT, so private
# forks, self-hosted git, and network-share deployments all work without
# knowing this project exists. These constants are only the last resort for
# a copy with no recorded source, and the yardstick for recognizing a
# public-GitHub install as such.
#
# The installers can't import Python, so install.sh/install.ps1 carry the
# same URL as their own baked-in default -- that's the true bootstrap, since
# a piped `curl ... | sh` has no seedling.conf beside it to read. A test
# asserts the three stay in agreement.
PUBLIC_REPO = "https://github.com/jrvannucci/seedling.git"
PUBLIC_RAW_BASE = "https://raw.githubusercontent.com/jrvannucci/seedling/main"
