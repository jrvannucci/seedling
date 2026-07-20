#!/usr/bin/env sh
# seedling installer (bash/zsh/sh) -- mirrors how `uv` installs itself.
# Requires nothing pre-installed except a POSIX shell and curl/wget (both
# already present on essentially every macOS/Linux system).
#
# Usage (from a local checkout of this repo, either works):
#   sh ./install.cmd
#   sh installers/install.sh
#
# Usage (remote):
#   curl -fsSL https://raw.githubusercontent.com/cryocliff/seedling/main/installers/install.sh | sh
#   SEEDLING_REPO=https://github.com/someone/fork.git curl -fsSL .../installers/install.sh | sh

set -eu

# Built-in defaults. seedling.conf ships with these same values written
# out, so a conf that still matches them changes nothing -- only edited
# values have any effect. The baked-in copies exist for the piped
# one-liner install, where no local seedling.conf exists yet to consult.
DEFAULT_SEEDLING_REPO="https://github.com/cryocliff/seedling.git"
DEFAULT_VENV_PACKAGES="ipython,ruff,ipykernel"

SEEDLING_REPO_FROM_ENV="${SEEDLING_REPO:-}"
SEEDLING_HOME_FROM_ENV="${SEEDLING_HOME:-}"
SEEDLING_AUTO_SETUP_FROM_ENV="${SEEDLING_AUTO_SETUP:-}"
SEEDLING_AUTO_VSCODE_FROM_ENV="${SEEDLING_AUTO_VSCODE:-}"
# Captured before seedling.conf is sourced (which would overwrite it). This
# is what lets a user point the PIPED one-liner at their own profile, where
# there is no local conf to edit:
#   curl -fsSL .../install.sh | SEEDLING_PROFILE=./team.toml sh
SEEDLING_PROFILE_FROM_ENV="${SEEDLING_PROFILE:-}"
# The directory the user invoked from, captured before any `cd`, so a
# relative profile path resolves against where they actually are.
SEEDLING_INVOKED_FROM="$(pwd)"

info()  { printf '\033[1;32m==>\033[0m %s\n' "$1"; }
warn()  { printf '\033[1;33m!!\033[0m %s\n' "$1"; }
die()   { printf '\033[1;31merror:\033[0m %s\n' "$1" >&2; exit 1; }

# The AUTO_* / NATIVE_TLS conf settings are booleans -- "true" / "false"
# (any case). AUTO_* default to true, NATIVE_TLS to false.
is_false() { [ "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" = "false" ]; }
is_true()  { [ "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" = "true" ]; }

# ---------------------------------------------------------------------------
# 1. Locate the seedling source (local checkout next to this script, or clone)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# This script lives in installers/; the repo root (seedling.conf, src/) is
# one level up.
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# seedling.conf at the repo root is the deployment config: organizations
# distributing seedling from their own git host or a network drive set the
# source (and any install-time settings) there ONCE, and their users install
# with no flags or env vars. Standard internet installs ship a conf whose
# values match the baked-in defaults, so nothing changes for them.
SEEDLING_REPO_URL=""
SEEDLING_HOME_DIR=""
SEEDLING_VENV_DEFAULT_PACKAGES=""
SEEDLING_AUTO_SETUP=""
SEEDLING_AUTO_VSCODE=""
SEEDLING_PYTHON_MIRROR=""
SEEDLING_PACKAGE_INDEX=""
SEEDLING_NATIVE_TLS=""
SEEDLING_VSCODE_FLAVOR=""
SEEDLING_EXTENSION_GALLERY=""
SEEDLING_VSCODE_EXTENSIONS=""
SEEDLING_PROFILE=""
CONF_FILE=""
if [ -f "$REPO_ROOT/seedling.conf" ]; then
    CONF_FILE="$REPO_ROOT/seedling.conf"
    . "$CONF_FILE"
fi

# Source resolution: SEEDLING_REPO env var (one-run override) beats
# seedling.conf, which beats the baked-in default.
if [ -n "$SEEDLING_REPO_FROM_ENV" ]; then
    SEEDLING_REPO="$SEEDLING_REPO_FROM_ENV"
elif [ -n "$SEEDLING_REPO_URL" ]; then
    SEEDLING_REPO="$SEEDLING_REPO_URL"
else
    SEEDLING_REPO="$DEFAULT_SEEDLING_REPO"
fi

# Home resolution follows the same order. A leading "~" in the conf value
# means the installing user's home directory.
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

# {user} -> the installing user's login name, so a shared install root
# (e.g. C:\seedling\{user}) gives every user a private, conflict-free
# folder. git-bash may not set $USER, so fall back through $USERNAME/id.
# When the token is used, record the shared root (the parent of the
# per-user home) so the elevated admin-* commands know this is a
# multi-user deployment.
SEEDLING_SHARED_ROOT=""
case "$SEEDLING_HOME" in
    *"{user}"*)
        _seed_user="${USER:-${USERNAME:-$(id -un 2>/dev/null || echo user)}}"
        SEEDLING_HOME=$(printf '%s' "$SEEDLING_HOME" | sed "s/{user}/$_seed_user/g")
        SEEDLING_SHARED_ROOT=$(dirname "$SEEDLING_HOME")
        ;;
esac

# ---------------------------------------------------------------------------
# 1b. Capture this whole install into the seedling logs, so `seed logs-viewer`
#     shows the bootstrap alongside your `seed` commands. Everything from here
#     down is tee'd (ANSI-stripped, like the daily logs) into a per-install
#     log and still shown live. Best-effort: a logs dir we can't create just
#     means this install runs without a log.
# ---------------------------------------------------------------------------
SEED_INSTALL_LOG=""
if mkdir -p "$SEEDLING_HOME/system/logs" 2>/dev/null; then
    SEED_INSTALL_LOG="$SEEDLING_HOME/system/logs/install-$(date +%Y%m%d-%H%M%S).log"
    printf '=== [%s] installer (bootstrap)\n' "$(date '+%Y-%m-%d %H:%M:%S')" > "$SEED_INSTALL_LOG"
fi
_seed_rc_file="$(mktemp 2>/dev/null || echo "${TMPDIR:-/tmp}/seed-rc.$$")"
{
trap 'printf %s "$?" > "$_seed_rc_file" 2>/dev/null' EXIT

INSTALLED_FROM_DIR=""
CLONE_MODE=0
if [ -f "$REPO_ROOT/src/pyproject.toml" ]; then
    ORIGINAL_SRC="$REPO_ROOT"
    CLEANUP_ORIGINAL_SRC=0
elif [ -d "$SEEDLING_REPO" ] && [ -f "$SEEDLING_REPO/src/pyproject.toml" ]; then
    # SEEDLING_REPO can be a plain directory instead of a git URL -- e.g. a
    # network drive holding a copy of this repo, on machines/networks with
    # no GitHub access at all.
    info "Installing from directory $SEEDLING_REPO ..."
    ORIGINAL_SRC="$SEEDLING_REPO"
    CLEANUP_ORIGINAL_SRC=0
    INSTALLED_FROM_DIR="$SEEDLING_REPO"
else
    command -v git >/dev/null 2>&1 || die "git is required to clone $SEEDLING_REPO."
    ORIGINAL_SRC="$(mktemp -d)"
    CLEANUP_ORIGINAL_SRC=1
    CLONE_MODE=1
    info "Cloning $SEEDLING_REPO ..."
    git clone --depth 1 "$SEEDLING_REPO" "$ORIGINAL_SRC"
fi

# ---------------------------------------------------------------------------
# 2. Lay out the folder structure
# ---------------------------------------------------------------------------
info "Setting up $SEEDLING_HOME"
mkdir -p "$SEEDLING_HOME/system/bin" \
         "$SEEDLING_HOME/system/config" \
         "$SEEDLING_HOME/system/shell" \
         "$SEEDLING_HOME/python/base" \
         "$SEEDLING_HOME/python/venvs" \
         "$SEEDLING_HOME/extensions" \
         "$SEEDLING_HOME/repo"

# ---------------------------------------------------------------------------
# 2b. Copy the source INTO seedling itself. This is what makes updates
#     explicit: seed-cli gets installed from $SEEDLING_HOME/src, a copy that
#     nothing outside of `seed update-commands` ever touches again. Deleting,
#     moving, or `git pull`-ing wherever you originally downloaded this from
#     has zero effect on the installed commands after this point.
# ---------------------------------------------------------------------------
info "Copying source into $SEEDLING_HOME/system/src ..."
rm -rf "$SEEDLING_HOME/system/src"
cp -R "$ORIGINAL_SRC" "$SEEDLING_HOME/system/src"
SRC_DIR="$SEEDLING_HOME/system/src"
# No git checkout lives inside ~/seedling: updates re-download from the
# recorded update_source (see below) instead of `git pull`-ing, so the
# .git folder would be dead weight (and its read-only object files used
# to break deletion on Windows).
rm -rf "$SRC_DIR/.git"

# The deployment profile travels with the source copy, so `seed apply` keeps
# working after the share it was installed from goes away. An absolute path
# in the conf is honoured as-is.
PROFILE_PATH=""
if [ -n "$SEEDLING_PROFILE_FROM_ENV" ]; then
    # User-supplied, for the piped one-liner. Relative paths resolve against
    # the directory they ran the installer from, not the source copy -- they
    # are pointing at THEIR file.
    case "$SEEDLING_PROFILE_FROM_ENV" in
        /*|?:[\\/]*) PROFILE_SRC="$SEEDLING_PROFILE_FROM_ENV" ;;
        *)           PROFILE_SRC="$SEEDLING_INVOKED_FROM/$SEEDLING_PROFILE_FROM_ENV" ;;
    esac
    # A missing path here is FATAL, unlike the conf case below. Someone who
    # explicitly named a profile and silently got the default environment
    # instead would not find out until something they expected is missing.
    [ -f "$PROFILE_SRC" ] || die "SEEDLING_PROFILE=$SEEDLING_PROFILE_FROM_ENV was set, but no file exists at $PROFILE_SRC."
    # Copy it in: the original may be a downloads folder, a mounted share, or
    # a temp file, and `seed apply` has to keep working long after that goes
    # away -- the same reason the source itself is copied.
    PROFILE_PATH="$SEEDLING_HOME/system/config/profile.toml"
    cp "$PROFILE_SRC" "$PROFILE_PATH"
    info "Using profile $PROFILE_SRC (copied to $PROFILE_PATH)"
elif [ -n "$SEEDLING_PROFILE" ]; then
    # Conf-supplied: ships inside the distributed copy, so it already lives
    # under ~/seedling and `seed update-commands` refreshes it.
    case "$SEEDLING_PROFILE" in
        /*|?:[\\/]*) PROFILE_PATH="$SEEDLING_PROFILE" ;;
        *)           PROFILE_PATH="$SRC_DIR/$SEEDLING_PROFILE" ;;
    esac
    if [ ! -f "$PROFILE_PATH" ]; then
        # Non-fatal, unlike the env case: a conf naming a profile that wasn't
        # distributed shouldn't brick installs across a whole fleet.
        warn "SEEDLING_PROFILE=$SEEDLING_PROFILE was set, but no profile "
        warn "was found at $PROFILE_PATH -- falling back to the default setup."
        PROFILE_PATH=""
        SEEDLING_PROFILE=""
    fi
fi

# ---------------------------------------------------------------------------
# 2b-vendor. Offline binaries shipped inside the install source (see
#     docs/OFFLINE.md): a `vendor/` folder in the distributed copy can hold
#     the uv binary, a portable git, and a pre-seeded VS Code. Whatever is
#     present gets copied into place BEFORE the download steps below --
#     each of which skips itself when its target already exists -- so an
#     offline share needs no wrapper scripts and no extra configuration:
#     presence equals intent. Every payload is a folder whose CONTENTS go
#     to the destination:
#       vendor/uv/     (uv.exe / uv, uvx too if present) -> ~/seedling/system/bin/
#       vendor/git/    (an extracted MinGit)             -> ~/seedling/extensions/git/
#       vendor/vscode/ (a pre-seeded portable VS Code)   -> ~/seedling/extensions/vscode/
#       vendor/certs/  (PEM CA certificates)             -> concatenated into
#                       ~/seedling/system/certs/ca-bundle.pem and trusted for
#                       all HTTPS (uv, git, seedling's own downloads)
# ---------------------------------------------------------------------------
CERT_BUNDLE=""
if [ -d "$SRC_DIR/vendor" ]; then
    if [ -d "$SRC_DIR/vendor/uv" ] && [ ! -e "$SEEDLING_HOME/system/bin/uv" ] && [ ! -e "$SEEDLING_HOME/system/bin/uv.exe" ]; then
        cp -R "$SRC_DIR/vendor/uv/." "$SEEDLING_HOME/system/bin/"
        chmod +x "$SEEDLING_HOME/system/bin/"uv* 2>/dev/null || true
        info "Using vendored uv from the install source."
    fi
    if [ -d "$SRC_DIR/vendor/git" ] && [ ! -d "$SEEDLING_HOME/extensions/git" ]; then
        mkdir -p "$SEEDLING_HOME/extensions/git"
        cp -R "$SRC_DIR/vendor/git/." "$SEEDLING_HOME/extensions/git/"
        info "Using vendored portable git from the install source."
    fi
    if [ -d "$SRC_DIR/vendor/vscode" ] && [ ! -d "$SEEDLING_HOME/extensions/vscode/app" ]; then
        mkdir -p "$SEEDLING_HOME/extensions/vscode"
        cp -R "$SRC_DIR/vendor/vscode/." "$SEEDLING_HOME/extensions/vscode/"
        info "Using vendored VS Code from the install source."
    fi
    if [ -d "$SRC_DIR/vendor/certs" ]; then
        # Unlike the binaries above, the bundle is REBUILT on every install
        # so certificate rotation propagates with a plain reinstall.
        mkdir -p "$SEEDLING_HOME/system/certs"
        CERT_BUNDLE="$SEEDLING_HOME/system/certs/ca-bundle.pem"
        : > "$CERT_BUNDLE"
        for _cert in "$SRC_DIR/vendor/certs/"*.pem "$SRC_DIR/vendor/certs/"*.crt; do
            [ -f "$_cert" ] || continue
            cat "$_cert" >> "$CERT_BUNDLE"
            printf '\n' >> "$CERT_BUNDLE"
        done
        if [ -s "$CERT_BUNDLE" ]; then
            info "Installed the vendored CA certificate bundle."
        else
            rm -f "$CERT_BUNDLE"
            CERT_BUNDLE=""
            warn "vendor/certs exists but holds no .pem/.crt files; no CA bundle installed."
        fi
    fi
    # The payloads live on the distribution source, not inside seedling's
    # private source copy -- a pre-seeded VS Code would otherwise bloat
    # system/src by hundreds of MB and get re-copied on every update.
    rm -rf "$SRC_DIR/vendor"
fi

if [ "$CLEANUP_ORIGINAL_SRC" = "1" ]; then
    rm -rf "$ORIGINAL_SRC"
fi

# ---------------------------------------------------------------------------
# 2c. Seed seedling's settings from seedling.conf (first install only --
#     an existing settings.json is never touched, so reinstalls don't
#     clobber choices made later with `seed config set`).
# ---------------------------------------------------------------------------
# Piped installs have no local conf, but the clone we just copied does.
if [ -z "$CONF_FILE" ] && [ -f "$SRC_DIR/seedling.conf" ]; then
    . "$SRC_DIR/seedling.conf"
fi

# Record where this install came from, so `seed update-commands` knows
# where to fetch newer versions (there's no git checkout inside ~/seedling
# to pull with -- updating re-downloads from this source instead):
#   - directory install  -> that directory
#   - cloned from a URL  -> that URL
#   - local checkout     -> the checkout DIRECTORY itself, so updates re-copy
#                           from that working tree (local edits, or a
#                           `git pull` there, reach the install)
UPDATE_SOURCE_SEED=""
if [ -n "$INSTALLED_FROM_DIR" ]; then
    UPDATE_SOURCE_SEED="$INSTALLED_FROM_DIR"
elif [ "$CLONE_MODE" = "1" ]; then
    UPDATE_SOURCE_SEED="$SEEDLING_REPO"
else
    # Local checkout. An explicit env var or an org-edited conf states intent
    # and wins; otherwise update straight from the checkout directory this was
    # installed from -- re-copying its working tree -- which is what a
    # developer iterating on the commands wants (consistent with the
    # directory-install case above).
    if [ -n "$SEEDLING_REPO_FROM_ENV" ]; then
        UPDATE_SOURCE_SEED="$SEEDLING_REPO"
    elif [ -n "$SEEDLING_REPO_URL" ] && [ "$SEEDLING_REPO_URL" != "$DEFAULT_SEEDLING_REPO" ]; then
        UPDATE_SOURCE_SEED="$SEEDLING_REPO_URL"
    else
        UPDATE_SOURCE_SEED="$REPO_ROOT"
    fi
fi

SETTINGS_FILE="$SEEDLING_HOME/system/config/settings.json"
if [ ! -f "$SETTINGS_FILE" ]; then
    json_escape() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
    entries=""
    if [ -n "$UPDATE_SOURCE_SEED" ]; then
        entries="  \"update_source\": \"$(json_escape "$UPDATE_SOURCE_SEED")\""
    fi
    # Only seed the package list when it was actually changed -- the conf
    # ships with the built-in default written out for discoverability.
    pkgs_norm=$(printf '%s' "$SEEDLING_VENV_DEFAULT_PACKAGES" | tr -d ' ')
    if [ -n "$pkgs_norm" ] && [ "$pkgs_norm" != "$DEFAULT_VENV_PACKAGES" ]; then
        pkgs=""
        OLD_IFS=$IFS; IFS=,
        for p in $SEEDLING_VENV_DEFAULT_PACKAGES; do
            p=$(printf '%s' "$p" | sed -e 's/^ *//' -e 's/ *$//')
            [ -z "$p" ] && continue
            [ -n "$pkgs" ] && pkgs="$pkgs, "
            pkgs="$pkgs\"$(json_escape "$p")\""
        done
        IFS=$OLD_IFS
        if [ -n "$pkgs" ]; then
            [ -n "$entries" ] && entries="$entries,
"
            entries="$entries  \"venv_default_packages\": [$pkgs]"
        fi
    fi
    # Offline sources (see docs/OFFLINE.md): recorded so every future
    # `seed` command applies them automatically -- users never set
    # environment variables themselves.
    if [ -n "$SEEDLING_PYTHON_MIRROR" ]; then
        [ -n "$entries" ] && entries="$entries,
"
        entries="$entries  \"python_mirror\": \"$(json_escape "$SEEDLING_PYTHON_MIRROR")\""
    fi
    if [ -n "$SEEDLING_PACKAGE_INDEX" ]; then
        [ -n "$entries" ] && entries="$entries,
"
        entries="$entries  \"package_index\": \"$(json_escape "$SEEDLING_PACKAGE_INDEX")\""
    fi
    if is_true "$SEEDLING_NATIVE_TLS"; then
        [ -n "$entries" ] && entries="$entries,
"
        entries="$entries  \"native_tls\": true"
    fi
    # Editor flavor/gallery/extensions. Only seeded when actually changed --
    # the conf ships with the built-in defaults written out, same as the
    # package list above.
    flavor_norm=$(printf '%s' "$SEEDLING_VSCODE_FLAVOR" | tr '[:upper:]' '[:lower:]' | tr -d ' ')
    if [ -n "$flavor_norm" ] && [ "$flavor_norm" != "microsoft" ]; then
        [ -n "$entries" ] && entries="$entries,
"
        entries="$entries  \"vscode_flavor\": \"$(json_escape "$flavor_norm")\""
    fi
    if [ -n "$SEEDLING_EXTENSION_GALLERY" ]; then
        [ -n "$entries" ] && entries="$entries,
"
        entries="$entries  \"extension_gallery\": \"$(json_escape "$SEEDLING_EXTENSION_GALLERY")\""
    fi
    # Keyed off the RESOLVED path, not the conf variable: a profile supplied
    # by the SEEDLING_PROFILE env var (the piped one-liner) leaves the conf
    # variable empty, and would otherwise never be recorded -- so `seed
    # apply` with no arguments would find nothing afterwards.
    if [ -n "$PROFILE_PATH" ]; then
        [ -n "$entries" ] && entries="$entries,
"
        entries="$entries  \"profile\": \"$(json_escape "$PROFILE_PATH")\""
    fi
    exts_norm=$(printf '%s' "$SEEDLING_VSCODE_EXTENSIONS" | tr -d ' ')
    if [ "$exts_norm" = "none" ]; then
        [ -n "$entries" ] && entries="$entries,
"
        entries="$entries  \"vscode_extensions\": []"
    elif [ -n "$exts_norm" ]; then
        exts=""
        OLD_IFS=$IFS; IFS=,
        for e in $SEEDLING_VSCODE_EXTENSIONS; do
            e=$(printf '%s' "$e" | sed -e 's/^ *//' -e 's/ *$//')
            [ -z "$e" ] && continue
            [ -n "$exts" ] && exts="$exts, "
            exts="$exts\"$(json_escape "$e")\""
        done
        IFS=$OLD_IFS
        if [ -n "$exts" ]; then
            [ -n "$entries" ] && entries="$entries,
"
            entries="$entries  \"vscode_extensions\": [$exts]"
        fi
    fi
    if [ -n "$CERT_BUNDLE" ]; then
        [ -n "$entries" ] && entries="$entries,
"
        entries="$entries  \"ca_cert\": \"$(json_escape "$CERT_BUNDLE")\""
    fi
    if [ -n "$SEEDLING_SHARED_ROOT" ]; then
        [ -n "$entries" ] && entries="$entries,
"
        entries="$entries  \"shared_root\": \"$(json_escape "$SEEDLING_SHARED_ROOT")\""
    fi
    if [ -n "$entries" ]; then
        printf '{\n%s\n}\n' "$entries" > "$SETTINGS_FILE"
        info "Seeded seedling settings from seedling.conf"
    fi
fi

# ---------------------------------------------------------------------------
# 2d. Apply the offline sources to THIS installer's own uv/seed-cli calls
#     too (building seed-cli needs the package index; the default
#     environment setup needs both). Pre-set UV_* variables still win.
# ---------------------------------------------------------------------------
to_file_url() {
    _v=$(printf '%s' "$1" | tr '\\' '/')
    case "$_v" in
        *"://"*)     printf '%s' "$_v" ;;
        [A-Za-z]:/*) printf 'file:///%s' "$_v" ;;
        /*)          printf 'file://%s' "$_v" ;;
        *)           printf '%s' "$_v" ;;
    esac
}

# TLS first: the vendored CA bundle / native trust store must cover the
# uv bootstrap and everything after it.
if [ -n "$CERT_BUNDLE" ] && [ -z "${SSL_CERT_FILE:-}" ]; then
    SSL_CERT_FILE="$CERT_BUNDLE"
    GIT_SSL_CAINFO="$CERT_BUNDLE"
    export SSL_CERT_FILE GIT_SSL_CAINFO
fi
if is_true "$SEEDLING_NATIVE_TLS" && [ -z "${UV_NATIVE_TLS:-}" ]; then
    UV_NATIVE_TLS=1
    export UV_NATIVE_TLS
fi

if [ -n "$SEEDLING_PYTHON_MIRROR" ] && [ -z "${UV_PYTHON_INSTALL_MIRROR:-}" ]; then
    UV_PYTHON_INSTALL_MIRROR="$(to_file_url "$SEEDLING_PYTHON_MIRROR")"
    export UV_PYTHON_INSTALL_MIRROR
fi
if [ -n "$SEEDLING_PACKAGE_INDEX" ]; then
    case "$SEEDLING_PACKAGE_INDEX" in
        *"://"*)
            if [ -z "${UV_DEFAULT_INDEX:-}" ]; then
                UV_DEFAULT_INDEX="$SEEDLING_PACKAGE_INDEX"
                export UV_DEFAULT_INDEX
            fi
            ;;
        *)
            # A directory of wheels: uv has no reliable env var for "flat
            # directory index, internet disabled", but honors a config
            # file. seed-cli generates the same file from settings later.
            if [ -z "${UV_CONFIG_FILE:-}" ]; then
                UV_TOML="$SEEDLING_HOME/system/config/uv.toml"
                {
                    echo "# Generated by seedling from the \`package_index\` setting. Do not edit;"
                    echo "# change it with:  seed config set package_index <url-or-directory>"
                    echo "[[index]]"
                    echo "name = \"seedling-offline\""
                    echo "url = \"$(to_file_url "$SEEDLING_PACKAGE_INDEX")\""
                    echo "format = \"flat\""
                    echo "default = true"
                } > "$UV_TOML"
                UV_CONFIG_FILE="$UV_TOML"
                export UV_CONFIG_FILE
            fi
            ;;
    esac
fi


# ---------------------------------------------------------------------------
# 3. Install uv itself into seedling/bin (uv is the one true dependency, and
#    its own official installer has zero prerequisites, same as this script)
# ---------------------------------------------------------------------------
if [ ! -x "$SEEDLING_HOME/system/bin/uv" ]; then
    info "Installing uv into $SEEDLING_HOME/system/bin ..."
    if command -v curl >/dev/null 2>&1; then
        env UV_INSTALL_DIR="$SEEDLING_HOME/system/bin" UV_NO_MODIFY_PATH=1 \
            sh -c "$(curl -fsSL https://astral.sh/uv/install.sh)"
    elif command -v wget >/dev/null 2>&1; then
        env UV_INSTALL_DIR="$SEEDLING_HOME/system/bin" UV_NO_MODIFY_PATH=1 \
            sh -c "$(wget -qO- https://astral.sh/uv/install.sh)"
    else
        die "Neither curl nor wget is available; cannot bootstrap uv."
    fi
else
    info "uv already present, skipping."
fi

UV="$SEEDLING_HOME/system/bin/uv"
[ -x "$UV" ] || die "uv install appears to have failed (not found at $UV)."

# ---------------------------------------------------------------------------
# 4. Install the seedling CLI itself as an isolated uv tool, from the copy
#    living inside ~/seedling/src (not the original download location).
#    `seed update-commands` is the only thing that ever re-runs this step.
# ---------------------------------------------------------------------------
info "Installing the seedling CLI ..."
env UV_TOOL_DIR="$SEEDLING_HOME/system/tool" UV_TOOL_BIN_DIR="$SEEDLING_HOME/system/bin" \
    UV_CACHE_DIR="$SEEDLING_HOME/system/cache/uv" \
    "$UV" tool install --force --reinstall "$SRC_DIR/src"

[ -x "$SEEDLING_HOME/system/bin/seed-cli" ] || die "seed-cli was not installed correctly."
SEED_CLI="$SEEDLING_HOME/system/bin/seed-cli"

# ---------------------------------------------------------------------------
# 4b. Default environment: the newest stable Python plus a 'dev' venv (with
#     the default packages) that every new shell auto-activates -- so a
#     fresh install is immediately usable with plain `python`/`ipython`.
#     Skip with SEEDLING_AUTO_SETUP="false" (env var or seedling.conf). Never
#     fatal: a network hiccup here still leaves a working seedling.
# ---------------------------------------------------------------------------
if [ -n "$SEEDLING_AUTO_SETUP_FROM_ENV" ]; then
    AUTO_SETUP="$SEEDLING_AUTO_SETUP_FROM_ENV"
elif [ -n "$SEEDLING_AUTO_SETUP" ]; then
    AUTO_SETUP="$SEEDLING_AUTO_SETUP"
else
    AUTO_SETUP="true"
fi

DEV_READY=0
if is_false "$AUTO_SETUP"; then
    info "Skipping default environment setup (SEEDLING_AUTO_SETUP=$AUTO_SETUP)."
else
        # VS Code setup starts FIRST, in the background: it's independent of
        # the python/venv steps and dominated by a ~300MB download, so it
        # overlaps them instead of adding its whole duration to the install.
        # SEEDLING_NO_LOG=1 keeps the background run from interleaving with
        # the foreground seed commands inside the daily log; its output is
        # buffered to a file and replayed below (which also lands it in the
        # install log). Idempotent (skips if already present), never fatal.
        if [ -n "$SEEDLING_AUTO_VSCODE_FROM_ENV" ]; then
            AUTO_VSCODE="$SEEDLING_AUTO_VSCODE_FROM_ENV"
        elif [ -n "$SEEDLING_AUTO_VSCODE" ]; then
            AUTO_VSCODE="$SEEDLING_AUTO_VSCODE"
        else
            AUTO_VSCODE="true"
        fi
        VSCODE_PID=""
        VSCODE_OUT=""
        VSCODE_RC=""
        if is_false "$AUTO_VSCODE"; then
            info "Skipping VS Code install (SEEDLING_AUTO_VSCODE=$AUTO_VSCODE)."
        else
            info "Setting up VS Code in the background (continues while Python is set up) ..."
            VSCODE_OUT="$(mktemp 2>/dev/null || echo "${TMPDIR:-/tmp}/seed-vscode-out.$$")"
            VSCODE_RC="$(mktemp 2>/dev/null || echo "${TMPDIR:-/tmp}/seed-vscode-rc.$$")"
            ( env SEEDLING_HOME="$SEEDLING_HOME" SEEDLING_NO_LOG=1 \
                  "$SEED_CLI" vscode --no-open >"$VSCODE_OUT" 2>&1
              echo "$?" >"$VSCODE_RC" ) &
            VSCODE_PID=$!
        fi

        if [ -n "$PROFILE_PATH" ]; then
            # A profile is the authoritative definition of this deployment's
            # environment, so it REPLACES the built-in single-'dev'-venv
            # setup rather than layering on top of it -- otherwise every
            # machine would carry a 'dev' venv the admin never asked for.
            info "Applying deployment profile: $PROFILE_PATH"
            if env SEEDLING_HOME="$SEEDLING_HOME" "$SEED_CLI" python &&                env SEEDLING_HOME="$SEEDLING_HOME" "$SEED_CLI" apply "$PROFILE_PATH"; then
                DEV_READY=1
            else
                warn "The deployment profile didn't fully apply."
                warn "Re-run it later with:  seed apply"
            fi
        elif [ -d "$SEEDLING_HOME/python/venvs/dev" ]; then
            info "Default 'dev' venv already exists, leaving it as-is."
            DEV_READY=1
        else
            info "Setting up the default environment: newest Python + a 'dev' venv ..."
            if env SEEDLING_HOME="$SEEDLING_HOME" "$SEED_CLI" python && \
               env SEEDLING_HOME="$SEEDLING_HOME" "$SEED_CLI" venv dev; then
                # Make 'dev' the venv new shells auto-activate -- unless the
                # user already chose one (reinstall case).
                if [ -z "$(env SEEDLING_HOME="$SEEDLING_HOME" SEEDLING_NO_LOG=1 "$SEED_CLI" config get default_venv 2>/dev/null)" ]; then
                    env SEEDLING_HOME="$SEEDLING_HOME" "$SEED_CLI" config set default_venv dev
                fi
                DEV_READY=1
            else
                warn "Default environment setup didn't finish (network problem?)."
                warn "Set it up later with:  seed python && seed venv dev && seed config set default_venv dev"
            fi
        fi

        # Collect the background VS Code setup started above. `|| true`
        # because under `set -e` a non-zero child status from wait would
        # abort the whole install -- VS Code stays non-fatal.
        if [ -n "$VSCODE_PID" ]; then
            info "Waiting for the background VS Code setup to finish ..."
            # Live status bar: seed-cli mirrors its progress into a one-line
            # status file ("<phase> <done> <total>"); poll it and repaint one
            # line in place. Only repaint on change so the install log
            # doesn't fill with duplicate frames.
            _status_file="$SEEDLING_HOME/extensions/vscode/setup-status"
            _last_bar=""
            while kill -0 "$VSCODE_PID" 2>/dev/null; do
                _bar="VS Code: setting up ..."
                if [ -f "$_status_file" ]; then
                    _ph=""; _d=0; _t=0
                    read -r _ph _d _t < "$_status_file" 2>/dev/null || _ph=""
                    # Sanitize before arithmetic: $((...)) on a non-number is
                    # a FATAL shell error in dash, even without set -e.
                    case "$_d" in ''|*[!0-9]*) _d=0 ;; esac
                    case "$_t" in ''|*[!0-9]*) _t=0 ;; esac
                    case "$_ph" in
                        downloading)
                            if [ "$_t" -gt 0 ]; then
                                _pct=$(( _d * 100 / _t ))
                                _bar="VS Code: downloading ${_pct}% of $(( _t / 1048576 )) MB"
                            else
                                _bar="VS Code: downloading $(( _d / 1048576 )) MB ..."
                            fi ;;
                        resolving)  _bar="VS Code: finding the latest build ..." ;;
                        extracting) _bar="VS Code: extracting ..." ;;
                        extensions) _bar="VS Code: installing extensions (Python, Jupyter, linting) ..." ;;
                    esac
                fi
                if [ "$_bar" != "$_last_bar" ]; then
                    printf '\r%-70s' "$_bar"
                    _last_bar="$_bar"
                fi
                sleep 1
            done
            # Plain `[ -n ... ] && printf` would return 1 when no bar was
            # ever painted, and set -e would abort the install on that.
            if [ -n "$_last_bar" ]; then printf '\r%-70s\r' " "; fi
            wait "$VSCODE_PID" || true
            cat "$VSCODE_OUT" 2>/dev/null || true
            _vscode_rc="$(cat "$VSCODE_RC" 2>/dev/null || echo 1)"
            rm -f "$VSCODE_OUT" "$VSCODE_RC"
            if [ "$_vscode_rc" != "0" ]; then
                warn "VS Code setup didn't finish (network problem?). Install it later with:  seed vscode"
            fi
        fi
fi

# ---------------------------------------------------------------------------
# 5. Write the `seed` shell function and hook it into the user's shell
# ---------------------------------------------------------------------------
info "Writing shell integration ..."
sed "s#__SEEDLING_HOME_PLACEHOLDER__#$SEEDLING_HOME#g" \
    "$SRC_DIR/src/seedling/shell/seed.sh.template" > "$SEEDLING_HOME/system/shell/seed.sh"

HOOK_LINE=". \"$SEEDLING_HOME/system/shell/seed.sh\""

add_hook() {
    profile="$1"
    [ -f "$profile" ] || touch "$profile"
    # Drop hook lines left by older seedling layouts (e.g. ~/seedling/shell/
    # before it moved under system/) before adding the current one, so a
    # reinstall never leaves a stale line erroring in every new shell.
    awk -v home="$SEEDLING_HOME" -v keep="$HOOK_LINE" '
        index($0, home) && (index($0, "seed.sh") || index($0, "seed.ps1")) && $0 != keep { next }
        { print }
    ' "$profile" > "$profile.tmp"
    if cmp -s "$profile" "$profile.tmp"; then
        rm -f "$profile.tmp"
    else
        mv "$profile.tmp" "$profile"
        info "Removed stale seedling hook line(s) from $profile"
    fi
    if ! grep -qF "$HOOK_LINE" "$profile" 2>/dev/null; then
        {
            echo ""
            echo "# seedling"
            echo "$HOOK_LINE"
        } >> "$profile"
        info "Added seedling to $profile"
    fi
}

case "${SHELL:-}" in
    */zsh)  add_hook "$HOME/.zshrc" ;;
    */bash) add_hook "$HOME/.bashrc" ;;
    *)      add_hook "$HOME/.profile" ;;
esac

info "seedling is installed."
echo
if [ "$DEV_READY" = "1" ]; then
    echo "Open a new terminal (or run: . \"$SEEDLING_HOME/system/shell/seed.sh\") --"
    echo "the 'dev' venv auto-activates there, so you can immediately try:"
    echo "  python / ipython          # the newest Python, ready to go"
    echo "  seed install <package>    # add packages to 'dev'"
    echo "  seed venv myproject       # create another venv"
    echo "  seed summary              # see everything seedling has installed"
else
    echo "Open a new terminal (or run: . \"$SEEDLING_HOME/system/shell/seed.sh\") and try:"
    echo "  seed python               # install the newest Python"
    echo "  seed venv myproject"
    echo "  seed activate myproject"
    echo "  seed summary"
fi
echo
echo "Note: seed-cli was installed from a private copy at $SEEDLING_HOME/system/src."
echo "Nothing updates it automatically -- run 'seed update-commands' whenever"
echo "you want to pull in changes."
# sed strips ANSI codes from the combined stream before tee displays and
# records it. Deliberate: the logs stay plain text end to end, so they can
# be shipped to a server, grepped, or displayed anywhere with zero
# escape-code handling (the live install output loses its colors in this
# captured region -- that's the accepted cost).
} 2>&1 | sed "s/$(printf '\033')\[[0-9;]*[A-Za-z]//g" | { if [ -n "$SEED_INSTALL_LOG" ]; then tee -a "$SEED_INSTALL_LOG"; else cat; fi; }

# Close the install-capture block opened in step 1b: record the exit code in
# the log (block format, so `seed logs-viewer` parses it like a `seed`
# command) and exit with the installer's real status.
_seed_rc="$(cat "$_seed_rc_file" 2>/dev/null || echo 0)"
rm -f "$_seed_rc_file" 2>/dev/null || true
if [ -n "$SEED_INSTALL_LOG" ]; then
    printf '=== [%s] exit code %s\n' "$(date '+%H:%M:%S')" "$_seed_rc" >> "$SEED_INSTALL_LOG"
fi
exit "${_seed_rc:-0}"
