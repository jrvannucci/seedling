#!/bin/sh
# POSIX launcher for the offline bundle builder (invoked by build-offline.cmd's
# line 1 on macOS/Linux). Finds a Python 3 and hands off to build_offline.py.
# This is NOT a `seed` command -- it prepares the distribution before seedling
# is installed anywhere.
set -e

DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

# Pick the first interpreter that actually RUNS and is 3.12+ (the builder
# imports seedling's own modules, so it shares seedling's requires-python
# floor). The `-c` probe matters on Windows/git-bash, where `python3` is often
# a Microsoft Store stub that only prints an ad and exits non-zero --
# command -v would still "find" it.
PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 12) else 1)' >/dev/null 2>&1; then
        PY="$cand"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "Python 3.12+ is required to build the offline bundle, but none was found."
    echo "Install python3 through your package manager and re-run this file."
    exit 1
fi

exec "$PY" "$DIR/build_offline.py" "$@"
