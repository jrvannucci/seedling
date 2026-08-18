#!/usr/bin/env sh
# Standalone seedling uninstaller (bash/zsh/sh) -- removes the managed
# folder AND the shell hook line.
#
# The normal way to uninstall is `seed purge` (more thorough, and it knows
# its own install location). This script is the FALLBACK for when seed-cli
# itself is broken and can't run. It resolves the install location the same
# way the installer did -- SEEDLING_HOME env override, else global.conf's
# SEEDLING_HOME_DIR with "~" and "{user}" expansion -- so relocated and
# shared multi-user installs are targeted correctly, not a hardcoded
# ~/seedling.
set -eu

SEEDLING_HOME_FROM_ENV="${SEEDLING_HOME:-}"

# This script lives in installers/; global.conf is at the repo root above.
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SEEDLING_HOME_DIR=""
if [ -f "$REPO_ROOT/global.conf" ]; then
    . "$REPO_ROOT/global.conf"
elif [ -f "$REPO_ROOT/seedling.conf" ]; then
    . "$REPO_ROOT/seedling.conf"            # pre-rename name
fi

# Home resolution: env override, else conf's SEEDLING_HOME_DIR (leading "~"
# means $HOME), else the default -- identical to the installer.
if [ -n "$SEEDLING_HOME_FROM_ENV" ]; then
    SEEDLING_HOME="$SEEDLING_HOME_FROM_ENV"
elif [ -n "$SEEDLING_HOME_DIR" ]; then
    case "$SEEDLING_HOME_DIR" in
        "~")   SEEDLING_HOME="$HOME" ;;
        "~/"*) SEEDLING_HOME="$HOME/${SEEDLING_HOME_DIR#??}" ;;
        *)     SEEDLING_HOME="$SEEDLING_HOME_DIR" ;;
    esac
else
    SEEDLING_HOME="$HOME/seedling"
fi

# {user} -> the current login name: this removes THIS user's install, like
# `seed purge` (all-users teardown is `seed admin-purge-all-users`).
case "$SEEDLING_HOME" in
    *"{user}"*)
        _seed_user="${USER:-${USERNAME:-$(id -un 2>/dev/null || echo user)}}"
        SEEDLING_HOME=$(printf '%s' "$SEEDLING_HOME" | sed "s/{user}/$_seed_user/g")
        ;;
esac

echo "Uninstalling seedling at: $SEEDLING_HOME"

# Match any line sourcing a seed shell script from under the seedling home
# -- not just the exact current hook text -- so hooks written by older
# seedling layouts (e.g. ~/seedling/shell/ before it moved under system/)
# are cleaned up too instead of erroring in every new shell.
for profile in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile"; do
    [ -f "$profile" ] || continue
    awk -v home="$SEEDLING_HOME" '
        $0 == "# seedling" { next }
        index($0, home) && (index($0, "seed.sh") || index($0, "seed.ps1")) { next }
        { print }
    ' "$profile" > "$profile.tmp"
    if cmp -s "$profile" "$profile.tmp"; then
        rm -f "$profile.tmp"
    else
        mv "$profile.tmp" "$profile"
        echo "Removed seedling hook from $profile"
    fi
done

if [ -d "$SEEDLING_HOME" ]; then
    rm -rf "$SEEDLING_HOME"
    echo "Removed $SEEDLING_HOME"
fi

echo "seedling fully uninstalled. Open a new terminal for it to take effect."
