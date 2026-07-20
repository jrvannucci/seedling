# seedling installer (PowerShell) -- mirrors how `uv` installs itself.
# Requires nothing pre-installed; works on a stock Windows PowerShell / pwsh.
#
# Usage (from a local checkout of this repo, either works):
#   .\install.cmd            (also handles the execution policy for you)
#   .\installers\install.ps1
#
# Usage (remote):
#   irm https://raw.githubusercontent.com/cryocliff/seedling/main/installers/install.ps1 | iex
#   $env:SEEDLING_REPO = "https://github.com/someone/fork.git"; irm .../installers/install.ps1 | iex

$ErrorActionPreference = "Stop"

# Built-in defaults. seedling.conf ships with these same values written
# out, so a conf that still matches them changes nothing -- only edited
# values have any effect. The baked-in copies exist for the piped
# one-liner install, where no local seedling.conf exists yet to consult.
$DefaultSeedlingRepo = "https://github.com/cryocliff/seedling.git"
$DefaultVenvPackages = "ipython,ruff,ipykernel"

function Info($msg)  { Write-Host "==> $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "!! $msg" -ForegroundColor Yellow }
function Die($msg)   {
    Write-Host "error: $msg" -ForegroundColor Red
    # The exit-code marker is what `seed logs-viewer` parses to show whether
    # this install completed; Stop-Transcript both finalizes the install log
    # and -- for piped `irm | iex` installs, where no process exit is coming
    # -- stops the transcript from silently recording the user's session
    # forever after. Guarded: transcription may never have started.
    Write-Host "seedling install FAILED (exit code 1)"
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

# seedling.conf is the deployment config: organizations distributing
# seedling from their own git host or a network drive set the source (and
# any install-time settings) there ONCE, and their users install with no
# flags or env vars. Standard internet installs ship a conf whose values
# match the baked-in defaults, so nothing changes for them.
function Read-SeedlingConf($path) {
    $conf = @{}
    if ($path -and (Test-Path $path)) {
        foreach ($line in Get-Content $path) {
            if ($line -match '^\s*([A-Z_]+)\s*=\s*"([^"]*)"\s*$') {
                $conf[$Matches[1]] = $Matches[2]
            }
        }
    }
    return $conf
}

# Resolve a usable git for the clone below: system git if present, else
# bootstrap a portable MinGit into $GitDir (extensions\git) -- the SAME
# location and mechanism `seed repo-clone` uses (see git_tool.py), so the
# copy is reused later and never downloaded twice. This is what lets the
# public/self-hosted URL one-liners live up to "requires nothing
# pre-installed" on a stock Windows box. Windows-only by nature: Git for
# Windows ships an official dependency-free portable build (MinGit); macOS
# and Linux have no equivalent, so install.sh keeps requiring system git.
function Resolve-SeedlingGit {
    param([string]$GitDir)

    $sys = Get-Command git -ErrorAction SilentlyContinue
    if ($sys) { return "git" }
    foreach ($rel in @("cmd\git.exe", "bin\git.exe")) {
        $existing = Join-Path $GitDir $rel
        if (Test-Path $existing) { return $existing }
    }

    Info "git isn't installed -- downloading a portable copy (MinGit) into $GitDir ..."
    New-Item -ItemType Directory -Force -Path $GitDir | Out-Null

    # GitHub's release API publishes a per-asset SHA-256 digest, so the zip
    # can be verified before it's extracted -- same policy as download.py.
    $api = "https://api.github.com/repos/git-for-windows/git/releases/latest"
    try {
        $release = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "seedling" }
    } catch {
        Die ("Could not reach GitHub's API to download MinGit ($($_.Exception.Message)). " +
             "Install git and re-run, or download the '...-64-bit.zip' asset from " +
             "https://github.com/git-for-windows/git/releases and extract it into $GitDir.")
    }
    # The 64-bit MinGit zip -- not the busybox variant, which lacks tools git
    # needs for cloning over https.
    $asset = $release.assets | Where-Object {
        $_.name -like "MinGit-*-64-bit.zip" -and $_.name -notlike "*busybox*"
    } | Select-Object -First 1
    if (-not $asset) { Die "Could not find a MinGit release asset to download." }

    $zip = Join-Path $GitDir "mingit-download.zip"
    Info "Downloading $($asset.name) ..."
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -Headers @{ "User-Agent" = "seedling" }

    if ($asset.digest) {
        $expected = ($asset.digest -replace '^sha256:', '').ToLower()
        $actual = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $expected) {
            Remove-Item -Force $zip -ErrorAction SilentlyContinue
            Die ("SHA-256 verification FAILED for MinGit (expected $expected, got $actual). " +
                 "The download was deleted -- try again on a trusted network.")
        }
        Info "Verified SHA-256 checksum for MinGit."
    } else {
        Warn "No published checksum was available for MinGit; skipping verification."
    }

    Expand-Archive -Path $zip -DestinationPath $GitDir -Force
    Remove-Item -Force $zip -ErrorAction SilentlyContinue

    foreach ($rel in @("cmd\git.exe", "bin\git.exe")) {
        $exe = Join-Path $GitDir $rel
        if (Test-Path $exe) { return $exe }
    }
    Die "MinGit was downloaded but its git.exe couldn't be located in $GitDir."
}

# ---------------------------------------------------------------------------
# 1. Locate the seedling source (local checkout next to this script, or clone)
# ---------------------------------------------------------------------------
# $MyInvocation.MyCommand.Path is $null when this script is run via
# `irm ... | iex` (there's no backing file for a piped-in script), so guard
# against that instead of calling Split-Path on a null value.
$ScriptPath = $MyInvocation.MyCommand.Path
$ScriptDir = if ($ScriptPath) { Split-Path -Parent $ScriptPath } else { $null }
# This script lives in installers\; the repo root (seedling.conf, src\) is
# one level up.
$RepoRoot = if ($ScriptDir) { Split-Path -Parent $ScriptDir } else { $null }

$HasLocalCheckout = $false
if ($RepoRoot) {
    if (Test-Path (Join-Path $RepoRoot "src\pyproject.toml")) {
        $HasLocalCheckout = $true
    }
}

$Conf = if ($RepoRoot) { Read-SeedlingConf (Join-Path $RepoRoot "seedling.conf") } else { @{} }

# Source resolution: SEEDLING_REPO env var (one-run override) beats
# seedling.conf, which beats the baked-in default.
$SeedlingRepo = if ($env:SEEDLING_REPO) {
    $env:SEEDLING_REPO
} elseif ($Conf["SEEDLING_REPO_URL"]) {
    $Conf["SEEDLING_REPO_URL"]
} else {
    $DefaultSeedlingRepo
}

# Home resolution follows the same order. A leading "~" in the conf value
# means the installing user's home directory.
$SeedlingHome = if ($env:SEEDLING_HOME) {
    $env:SEEDLING_HOME
} elseif ($Conf["SEEDLING_HOME_DIR"]) {
    $dir = $Conf["SEEDLING_HOME_DIR"]
    if ($dir -eq "~") { $HOME }
    elseif ($dir.StartsWith("~/") -or $dir.StartsWith("~\")) { Join-Path $HOME $dir.Substring(2) }
    else { $dir }
} else {
    Join-Path $HOME "seedling"
}

# {user} -> the installing user's login name, so a shared install root
# (e.g. C:\seedling\{user}) gives every user a private, conflict-free folder.
# When the token is used, record the shared root (the parent of the per-user
# home) so the elevated admin-* commands know this is a multi-user install.
$SeedlingSharedRoot = $null
if ($SeedlingHome -like "*{user}*") {
    $SeedlingHome = $SeedlingHome -replace [regex]::Escape("{user}"), $env:USERNAME
    $SeedlingSharedRoot = Split-Path -Parent $SeedlingHome
}

# Capture this whole install into the seedling logs, so `seed logs-viewer`
# shows the bootstrap alongside your `seed` commands. Start-Transcript records
# the console live WITHOUT redirecting any streams -- which matters because uv
# writes its normal progress to stderr, and redirecting a native command's
# stderr under $ErrorActionPreference='Stop' turns it into a fatal
# NativeCommandError (this broke the install once). Best-effort: never let
# logging break the install; the transcript auto-finalizes when the script exits.
try {
    $SeedLogDir = Join-Path $SeedlingHome "system\logs"
    New-Item -ItemType Directory -Force -Path $SeedLogDir -ErrorAction Stop | Out-Null
    $SeedInstallLog = Join-Path $SeedLogDir ("install-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
    Start-Transcript -Path $SeedInstallLog -Force -ErrorAction Stop | Out-Null
} catch { }

$InstalledFromDir = $null
$CloneMode = $false
if ($HasLocalCheckout) {
    $OriginalSrc = $RepoRoot
    $CleanupOriginalSrc = $false
} elseif ((Test-Path $SeedlingRepo -PathType Container) -and (Test-Path (Join-Path $SeedlingRepo "src\pyproject.toml"))) {
    # SEEDLING_REPO can be a plain directory instead of a git URL -- e.g. a
    # network drive holding a copy of this repo, on machines/networks with
    # no GitHub access at all.
    Info "Installing from directory $SeedlingRepo ..."
    $OriginalSrc = $SeedlingRepo
    $CleanupOriginalSrc = $false
    $InstalledFromDir = $SeedlingRepo
} else {
    # No system git? Bootstrap portable MinGit into extensions\git before the
    # clone, so a bare Windows box can still install from a URL.
    $Git = Resolve-SeedlingGit (Join-Path $SeedlingHome "extensions\git")
    $OriginalSrc = Join-Path ([System.IO.Path]::GetTempPath()) ("seedling-src-" + [System.Guid]::NewGuid())
    $CleanupOriginalSrc = $true
    $CloneMode = $true
    Info "Cloning $SeedlingRepo ..."
    & $Git clone --depth 1 $SeedlingRepo $OriginalSrc
}

# ---------------------------------------------------------------------------
# 2. Lay out the folder structure
# ---------------------------------------------------------------------------
Info "Setting up $SeedlingHome"
$null = New-Item -ItemType Directory -Force -Path `
    "$SeedlingHome\system\bin", `
    "$SeedlingHome\system\config", `
    "$SeedlingHome\system\shell", `
    "$SeedlingHome\python\base", `
    "$SeedlingHome\python\venvs", `
    "$SeedlingHome\extensions", `
    "$SeedlingHome\repo"

# ---------------------------------------------------------------------------
# 2b. Copy the source INTO seedling itself. This is what makes updates
#     explicit: seed-cli gets installed from $SeedlingHome\src, a copy that
#     nothing outside of `seed update-commands` ever touches again. Deleting,
#     moving, or `git pull`-ing wherever you originally downloaded this from
#     has zero effect on the installed commands after this point.
# ---------------------------------------------------------------------------
Info "Copying source into $SeedlingHome\system\src ..."
$SrcDir = Join-Path $SeedlingHome "system\src"
if (Test-Path $SrcDir) { Remove-Item -Recurse -Force $SrcDir }
Copy-Item -Recurse -Force $OriginalSrc $SrcDir
# No git checkout lives inside ~\seedling: updates re-download from the
# recorded update_source (see below) instead of `git pull`-ing, so the
# .git folder would be dead weight (and its read-only object files used
# to break deletion on Windows).
# The deployment profile travels with the source copy, so `seed apply` keeps
# working after the share it was installed from goes away. An absolute path
# in the conf is honoured as-is.
$ProfilePath = ""
if ($env:SEEDLING_PROFILE) {
    # User-supplied, for the piped one-liner (`$env:SEEDLING_PROFILE = ...;
    # irm ... | iex`), where there is no local conf to edit. Relative paths
    # resolve against the directory they ran the installer from -- they are
    # pointing at THEIR file.
    $rawProfile = $env:SEEDLING_PROFILE
    $profileSrc = if ([System.IO.Path]::IsPathRooted($rawProfile)) {
        $rawProfile
    } else {
        Join-Path (Get-Location).Path $rawProfile
    }
    # Fatal, unlike the conf case below: someone who explicitly named a
    # profile and silently got the default environment instead would not
    # find out until something they expected is missing.
    if (-not (Test-Path $profileSrc)) {
        Die "SEEDLING_PROFILE=$rawProfile was set, but no file exists at $profileSrc."
    }
    # Copy it in: the original may be a downloads folder, a mounted share or
    # a temp file, and `seed apply` has to keep working long after that goes
    # away -- the same reason the source itself is copied.
    $ProfilePath = Join-Path $SeedlingHome "system\config\profile.toml"
    Copy-Item -Force $profileSrc $ProfilePath
    Info "Using profile $profileSrc (copied to $ProfilePath)"
} elseif ($Conf["SEEDLING_PROFILE"]) {
    # Conf-supplied: ships inside the distributed copy, so it already lives
    # under the seedling home and `seed update-commands` refreshes it.
    $rawProfile = $Conf["SEEDLING_PROFILE"]
    if ([System.IO.Path]::IsPathRooted($rawProfile)) {
        $ProfilePath = $rawProfile
    } else {
        $ProfilePath = Join-Path $SrcDir $rawProfile
    }
    if (-not (Test-Path $ProfilePath)) {
        # Non-fatal, unlike the env case: a conf naming a profile that wasn't
        # distributed shouldn't brick installs across a whole fleet.
        Warn "SEEDLING_PROFILE=$rawProfile was set, but no profile was found at"
        Warn "$ProfilePath -- falling back to the default setup."
        $ProfilePath = ""
    }
}

$SrcGit = Join-Path $SrcDir ".git"
if (Test-Path $SrcGit) { Remove-Item -Recurse -Force $SrcGit }

# ---------------------------------------------------------------------------
# 2b-vendor. Offline binaries shipped inside the install source (see
#     docs/OFFLINE.md): a `vendor\` folder in the distributed copy can hold
#     the uv binary, a portable git, and a pre-seeded VS Code. Whatever is
#     present gets copied into place BEFORE the download steps below --
#     each of which skips itself when its target already exists -- so an
#     offline share needs no wrapper scripts and no extra configuration:
#     presence equals intent. Every payload is a folder whose CONTENTS go
#     to the destination:
#       vendor\uv\     (uv.exe, uvx too if present)     -> ~\seedling\system\bin\
#       vendor\git\    (an extracted MinGit)            -> ~\seedling\extensions\git\
#       vendor\vscode\ (a pre-seeded portable VS Code)  -> ~\seedling\extensions\vscode\
#       vendor\certs\  (PEM CA certificates)            -> concatenated into
#                       ~\seedling\system\certs\ca-bundle.pem and trusted for
#                       all HTTPS (uv, git, seedling's own downloads)
# ---------------------------------------------------------------------------
$CertBundle = $null
$VendorDir = Join-Path $SrcDir "vendor"
if (Test-Path $VendorDir) {
    $vendorUv = Join-Path $VendorDir "uv"
    if ((Test-Path $vendorUv) -and -not (Test-Path "$SeedlingHome\system\bin\uv.exe")) {
        Copy-Item "$vendorUv\*" -Destination "$SeedlingHome\system\bin" -Recurse -Force
        Info "Using vendored uv from the install source."
    }
    $vendorGit = Join-Path $VendorDir "git"
    if ((Test-Path $vendorGit) -and -not (Test-Path "$SeedlingHome\extensions\git")) {
        New-Item -ItemType Directory -Force -Path "$SeedlingHome\extensions\git" | Out-Null
        Copy-Item "$vendorGit\*" -Destination "$SeedlingHome\extensions\git" -Recurse -Force
        Info "Using vendored portable git from the install source."
    }
    $vendorVscode = Join-Path $VendorDir "vscode"
    if ((Test-Path $vendorVscode) -and -not (Test-Path "$SeedlingHome\extensions\vscode\app")) {
        New-Item -ItemType Directory -Force -Path "$SeedlingHome\extensions\vscode" | Out-Null
        Copy-Item "$vendorVscode\*" -Destination "$SeedlingHome\extensions\vscode" -Recurse -Force
        Info "Using vendored VS Code from the install source."
    }
    $vendorCerts = Join-Path $VendorDir "certs"
    if (Test-Path $vendorCerts) {
        # Unlike the binaries above, the bundle is REBUILT on every install
        # so certificate rotation propagates with a plain reinstall.
        $certFiles = @(Get-ChildItem -Path $vendorCerts -File | Where-Object { $_.Extension -in ".pem", ".crt" })
        if ($certFiles.Count -gt 0) {
            New-Item -ItemType Directory -Force -Path "$SeedlingHome\system\certs" | Out-Null
            $CertBundle = "$SeedlingHome\system\certs\ca-bundle.pem"
            ($certFiles | ForEach-Object { (Get-Content $_.FullName -Raw).TrimEnd() }) -join "`n" |
                Set-Content -Path $CertBundle -Encoding ASCII
            Info "Installed the vendored CA certificate bundle."
        } else {
            Warn "vendor\certs exists but holds no .pem/.crt files; no CA bundle installed."
        }
    }
    # The payloads live on the distribution source, not inside seedling's
    # private source copy -- a pre-seeded VS Code would otherwise bloat
    # system\src by hundreds of MB and get re-copied on every update.
    Remove-Item -Recurse -Force $VendorDir
}

if ($CleanupOriginalSrc) {
    Remove-Item -Recurse -Force $OriginalSrc -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# 2c. Seed seedling's settings from seedling.conf (first install only --
#     an existing settings.json is never touched, so reinstalls don't
#     clobber choices made later with `seed config set`).
# ---------------------------------------------------------------------------
# Piped installs have no local conf, but the clone we just copied does.
if ($Conf.Count -eq 0) {
    $Conf = Read-SeedlingConf (Join-Path $SrcDir "seedling.conf")
}

# Record where this install came from, so `seed update-commands` knows
# where to fetch newer versions (there's no git checkout inside ~\seedling
# to pull with -- updating re-downloads from this source instead):
#   - directory install  -> that directory
#   - cloned from a URL  -> that URL
#   - local checkout     -> env var / org-edited conf if given, else the
#                           checkout DIRECTORY itself, so updates re-copy from
#                           that working tree (a developer's local edits, or a
#                           `git pull` there, reach the install via
#                           `seed update-commands`)
$UpdateSourceSeed = $null
if ($InstalledFromDir) {
    $UpdateSourceSeed = $InstalledFromDir
} elseif ($CloneMode) {
    $UpdateSourceSeed = $SeedlingRepo
} else {
    if ($env:SEEDLING_REPO) {
        $UpdateSourceSeed = $SeedlingRepo
    } elseif ($Conf["SEEDLING_REPO_URL"] -and $Conf["SEEDLING_REPO_URL"] -ne $DefaultSeedlingRepo) {
        $UpdateSourceSeed = $Conf["SEEDLING_REPO_URL"]
    } else {
        # No explicit override: update straight from the checkout this was
        # installed from -- installing from a repo directory means updating
        # from that same directory (consistent with the directory-install
        # case above), which is what a developer iterating on the commands
        # wants. `git pull` there, then `seed update-commands`, to test edits.
        $UpdateSourceSeed = $RepoRoot
    }
}

$SettingsFile = Join-Path $SeedlingHome "system\config\settings.json"
if (-not (Test-Path $SettingsFile)) {
    $seed = @{}
    if ($UpdateSourceSeed) { $seed["update_source"] = "$UpdateSourceSeed" }
    # Only seed the package list when it was actually changed -- the conf
    # ships with the built-in default written out for discoverability.
    if ($Conf["SEEDLING_VENV_DEFAULT_PACKAGES"]) {
        $pkgs = @($Conf["SEEDLING_VENV_DEFAULT_PACKAGES"].Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        if ($pkgs.Count -gt 0 -and (($pkgs -join ",") -ne $DefaultVenvPackages)) {
            $seed["venv_default_packages"] = $pkgs
        }
    }
    # Offline sources (see docs/OFFLINE.md): recorded so every future
    # `seed` command applies them automatically -- users never set
    # environment variables themselves.
    if ($Conf["SEEDLING_PYTHON_MIRROR"]) { $seed["python_mirror"] = $Conf["SEEDLING_PYTHON_MIRROR"] }
    if ($Conf["SEEDLING_PACKAGE_INDEX"]) { $seed["package_index"] = $Conf["SEEDLING_PACKAGE_INDEX"] }
    if ($Conf["SEEDLING_NATIVE_TLS"] -and $Conf["SEEDLING_NATIVE_TLS"].ToLower() -eq "true") {
        $seed["native_tls"] = $true
    }
    if ($CertBundle) { $seed["ca_cert"] = "$CertBundle" }
    if ($SeedlingSharedRoot) { $seed["shared_root"] = "$SeedlingSharedRoot" }
    # Editor flavor/gallery/extensions. Only seeded when actually changed --
    # the conf ships with the built-in defaults written out, same as the
    # package list above.
    if ($Conf["SEEDLING_VSCODE_FLAVOR"]) {
        $flavor = $Conf["SEEDLING_VSCODE_FLAVOR"].Trim().ToLower()
        if ($flavor -and $flavor -ne "microsoft") { $seed["vscode_flavor"] = $flavor }
    }
    if ($Conf["SEEDLING_EXTENSION_GALLERY"]) {
        $seed["extension_gallery"] = $Conf["SEEDLING_EXTENSION_GALLERY"]
    }
    if ($ProfilePath) { $seed["profile"] = "$ProfilePath" }
    if ($Conf["SEEDLING_VSCODE_EXTENSIONS"]) {
        $extsRaw = $Conf["SEEDLING_VSCODE_EXTENSIONS"].Trim()
        if ($extsRaw.ToLower() -eq "none") {
            # A deliberate "install nothing", distinct from "unset".
            $seed["vscode_extensions"] = @()
        } else {
            $exts = @($extsRaw.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
            if ($exts.Count -gt 0) { $seed["vscode_extensions"] = $exts }
        }
    }
    if ($seed.Count -gt 0) {
        $seed | ConvertTo-Json | Set-Content -Path $SettingsFile -Encoding UTF8
        Info "Seeded seedling settings from seedling.conf"
    }
}

# ---------------------------------------------------------------------------
# 2d. Apply the offline sources to THIS installer's own uv/seed-cli calls
#     too (building seed-cli needs the package index; the default
#     environment setup needs both). Pre-set UV_* variables still win.
# ---------------------------------------------------------------------------
function To-FileUrl($value) {
    if ($value -match "://") { return $value }
    $u = $value -replace "\\", "/"
    if ($u -match "^[A-Za-z]:/") { return "file:///$u" }
    if ($u.StartsWith("/")) { return "file://$u" }
    return $value
}

# TLS first: the vendored CA bundle / native trust store must cover the
# uv bootstrap and everything after it.
if ($CertBundle -and -not $env:SSL_CERT_FILE) {
    $env:SSL_CERT_FILE = $CertBundle
    $env:GIT_SSL_CAINFO = $CertBundle
}
if ($Conf["SEEDLING_NATIVE_TLS"] -and $Conf["SEEDLING_NATIVE_TLS"].ToLower() -eq "true" -and -not $env:UV_NATIVE_TLS) {
    $env:UV_NATIVE_TLS = "1"
}

if ($Conf["SEEDLING_PYTHON_MIRROR"] -and -not $env:UV_PYTHON_INSTALL_MIRROR) {
    $env:UV_PYTHON_INSTALL_MIRROR = To-FileUrl $Conf["SEEDLING_PYTHON_MIRROR"]
}
if ($Conf["SEEDLING_PACKAGE_INDEX"]) {
    $idx = $Conf["SEEDLING_PACKAGE_INDEX"]
    if ($idx -match "://") {
        if (-not $env:UV_DEFAULT_INDEX) { $env:UV_DEFAULT_INDEX = $idx }
    } elseif (-not $env:UV_CONFIG_FILE) {
        # A directory of wheels: uv has no reliable env var for "flat
        # directory index, internet disabled", but honors a config file.
        # seed-cli generates the same file from settings later.
        $UvToml = Join-Path $SeedlingHome "system\config\uv.toml"
        @(
            "# Generated by seedling from the ``package_index`` setting. Do not edit;"
            "# change it with:  seed config set package_index <url-or-directory>"
            "[[index]]"
            'name = "seedling-offline"'
            "url = `"$(To-FileUrl $idx)`""
            'format = "flat"'
            "default = true"
        ) | Set-Content -Path $UvToml -Encoding UTF8
        $env:UV_CONFIG_FILE = $UvToml
    }
}


# ---------------------------------------------------------------------------
# 3. Install uv itself into seedling\bin
# ---------------------------------------------------------------------------
$UvExe = Join-Path $SeedlingHome "system\bin\uv.exe"
if (-not (Test-Path $UvExe)) {
    Info "Installing uv into $SeedlingHome\system\bin ..."
    $env:UV_INSTALL_DIR = "$SeedlingHome\system\bin"
    $env:UV_NO_MODIFY_PATH = "1"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
} else {
    Info "uv already present, skipping."
}

if (-not (Test-Path $UvExe)) { Die "uv install appears to have failed (not found at $UvExe)." }

# ---------------------------------------------------------------------------
# 4. Install the seedling CLI itself as an isolated uv tool
# ---------------------------------------------------------------------------
Info "Installing the seedling CLI ..."
$env:UV_TOOL_DIR = "$SeedlingHome\system\tool"
$env:UV_TOOL_BIN_DIR = "$SeedlingHome\system\bin"
$env:UV_CACHE_DIR = "$SeedlingHome\system\cache\uv"
& $UvExe tool install --force --reinstall (Join-Path $SrcDir "src")

$SeedCli = Join-Path $SeedlingHome "system\bin\seed-cli.exe"
if (-not (Test-Path $SeedCli)) { Die "seed-cli was not installed correctly." }

# ---------------------------------------------------------------------------
# 4b. Default environment: the newest stable Python plus a 'dev' venv (with
#     the default packages) that every new shell auto-activates -- so a
#     fresh install is immediately usable with plain `python`/`ipython`.
#     Skip with SEEDLING_AUTO_SETUP="false" (env var or seedling.conf). Never
#     fatal: a network hiccup here still leaves a working seedling.
# ---------------------------------------------------------------------------
$AutoSetup = if ($env:SEEDLING_AUTO_SETUP) {
    $env:SEEDLING_AUTO_SETUP
} elseif ($Conf["SEEDLING_AUTO_SETUP"]) {
    $Conf["SEEDLING_AUTO_SETUP"]
} else {
    "true"
}

$DevReady = $false
if ($AutoSetup.ToLower() -eq "false") {
    Info "Skipping default environment setup (SEEDLING_AUTO_SETUP=$AutoSetup)."
} else {
    # VS Code setup starts FIRST, as a background job: it's independent of
    # the python/venv steps and dominated by a ~300MB download, so it
    # overlaps them instead of adding its whole duration to the install.
    # SEEDLING_NO_LOG=1 keeps the background run from interleaving with the
    # foreground seed commands inside the daily log; its output is replayed
    # below (which also lands it in the install transcript). Idempotent
    # (skips if already present) and never fatal. Note: the job runs in its
    # own runspace where $ErrorActionPreference is the default 'Continue',
    # so uv/seed-cli writing progress to stderr can't become a fatal
    # NativeCommandError there.
    $AutoVscode = if ($env:SEEDLING_AUTO_VSCODE) {
        $env:SEEDLING_AUTO_VSCODE
    } elseif ($Conf["SEEDLING_AUTO_VSCODE"]) {
        $Conf["SEEDLING_AUTO_VSCODE"]
    } else {
        "true"
    }
    $VscodeJob = $null
    if ($AutoVscode.ToLower() -eq "false") {
        Info "Skipping VS Code install (SEEDLING_AUTO_VSCODE=$AutoVscode)."
    } else {
        Info "Setting up VS Code in the background (continues while Python is set up) ..."
        $VscodeJob = Start-Job -ScriptBlock {
            # NOT `param($cli, $home)`: $home is PowerShell's read-only
            # automatic variable, and binding a parameter to it kills the
            # job instantly ("Cannot overwrite variable home").
            param($cli, $seedHome)
            $env:SEEDLING_HOME = $seedHome
            $env:SEEDLING_NO_LOG = "1"
            & $cli vscode --no-open
            "SEEDVSC_EXIT=$LASTEXITCODE"
        } -ArgumentList $SeedCli, $SeedlingHome
    }

    if ($ProfilePath) {
        # A profile is the authoritative definition of this deployment's
        # environment, so it REPLACES the built-in single-'dev'-venv setup
        # rather than layering on top of it -- otherwise every machine would
        # carry a 'dev' venv the admin never asked for.
        Info "Applying deployment profile: $ProfilePath"
        $env:SEEDLING_HOME = $SeedlingHome
        & $SeedCli python
        if ($LASTEXITCODE -eq 0) { & $SeedCli apply $ProfilePath }
        if ($LASTEXITCODE -eq 0) {
            $DevReady = $true
        } else {
            Warn "The deployment profile didn't fully apply."
            Warn "Re-run it later with:  seed apply"
        }
    } elseif (Test-Path (Join-Path $SeedlingHome "python\venvs\dev")) {
        Info "Default 'dev' venv already exists, leaving it as-is."
        $DevReady = $true
    } else {
        Info "Setting up the default environment: newest Python + a 'dev' venv ..."
        $env:SEEDLING_HOME = $SeedlingHome
        & $SeedCli python
        if ($LASTEXITCODE -eq 0) { & $SeedCli venv dev }
        if ($LASTEXITCODE -eq 0) {
            # Make 'dev' the venv new shells auto-activate -- unless the user
            # already chose one (reinstall case).
            $env:SEEDLING_NO_LOG = "1"
            $existingDefault = & $SeedCli config get default_venv
            Remove-Item Env:SEEDLING_NO_LOG -ErrorAction SilentlyContinue
            if (-not $existingDefault) { & $SeedCli config set default_venv dev }
            $DevReady = $true
        } else {
            Warn "Default environment setup didn't finish (network problem?)."
            Warn "Set it up later with:  seed python; seed venv dev; seed config set default_venv dev"
        }
    }

    # Collect the background VS Code job: replay its buffered output, pick
    # out the exit-code sentinel, and warn -- never fail -- on a bad exit.
    # $ErrorActionPreference is relaxed JUST around Receive-Job: the job's
    # error stream can hold native-stderr records (uv progress etc.), and
    # receiving those under 'Stop' throws a fatal NativeCommandError
    # (verified); under 'Continue' the `*>&1` merge turns them into plain
    # replayable strings.
    if ($VscodeJob) {
        Info "Waiting for the background VS Code setup to finish ..."
        # Live status bar: seed-cli mirrors its progress into a one-line
        # status file ("<phase> <done> <total>"); poll it and repaint one
        # console line in place. Only repaint on change, so the install
        # transcript doesn't fill with duplicate frames.
        $StatusFile = Join-Path $SeedlingHome "extensions\vscode\setup-status"
        $lastBar = ""
        while ($VscodeJob.State -eq "Running") {
            Start-Sleep -Milliseconds 500
            $bar = "VS Code: setting up ..."
            if (Test-Path $StatusFile) {
                try {
                    $parts = (Get-Content $StatusFile -TotalCount 1 -ErrorAction Stop) -split " "
                    switch ($parts[0]) {
                        "downloading" {
                            $done = [long]$parts[1]; $total = [long]$parts[2]
                            if ($total -gt 0) {
                                $pct = [int](100 * $done / $total)
                                $filled = [int]($pct / 5)
                                $bar = ("VS Code: downloading [{0}{1}] {2,3}% of {3:N0} MB" -f
                                        ("#" * $filled), ("-" * (20 - $filled)), $pct, ($total / 1MB))
                            } else {
                                $bar = ("VS Code: downloading {0:N0} MB ..." -f ($done / 1MB))
                            }
                        }
                        "resolving"  { $bar = "VS Code: finding the latest build ..." }
                        "extracting" { $bar = "VS Code: extracting ..." }
                        "extensions" { $bar = "VS Code: installing extensions (Python, Jupyter, linting) ..." }
                    }
                } catch { }
            }
            if ($bar -ne $lastBar) {
                Write-Host -NoNewline ("`r" + $bar.PadRight(78))
                $lastBar = $bar
            }
        }
        if ($lastBar) { Write-Host ("`r" + (" " * 78) + "`r") -NoNewline }
        Wait-Job $VscodeJob | Out-Null
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $vscodeLines = @(Receive-Job $VscodeJob *>&1 | ForEach-Object { "$_" })
        $ErrorActionPreference = $prevEap
        Remove-Job $VscodeJob -Force -ErrorAction SilentlyContinue
        $vscodeExit = 1
        foreach ($line in $vscodeLines) {
            if ($line -match '^SEEDVSC_EXIT=(-?\d+)$') { $vscodeExit = [int]$Matches[1] }
            elseif ($line) { Write-Host $line }
        }
        if ($vscodeExit -ne 0) {
            Warn "VS Code setup didn't finish (network problem?). Install it later with:  seed vscode"
        }
    }
}

# ---------------------------------------------------------------------------
# 5. Write the `seed` PowerShell function and hook it into $PROFILE
# ---------------------------------------------------------------------------
Info "Writing shell integration ..."
$templatePath = Join-Path $SrcDir "src\seedling\shell\seed.ps1.template"
$content = Get-Content $templatePath -Raw
$content = $content -replace [regex]::Escape("__SEEDLING_HOME_PLACEHOLDER__"), $SeedlingHome
$seedPs1 = Join-Path $SeedlingHome "system\shell\seed.ps1"
Set-Content -Path $seedPs1 -Value $content -Encoding UTF8

$hookLine = ". `"$seedPs1`""
if (-not (Test-Path $PROFILE)) {
    New-Item -ItemType File -Force -Path $PROFILE | Out-Null
}
# Drop hook lines left by older seedling layouts (e.g. ~\seedling\shell\
# before it moved under system\) before adding the current one, so a
# reinstall never leaves a stale line erroring in every new shell.
$lines = @(Get-Content $PROFILE -ErrorAction SilentlyContinue)
$cleaned = @($lines | Where-Object {
    -not ($_.Contains($SeedlingHome) -and ($_ -match "seed\.(ps1|sh)") -and $_ -ne $hookLine)
})
if ($cleaned.Count -ne $lines.Count) {
    Set-Content -Path $PROFILE -Value $cleaned
    Info "Removed stale seedling hook line(s) from $PROFILE"
}
if (-not ($cleaned -contains $hookLine)) {
    Add-Content -Path $PROFILE -Value "`n# seedling`n$hookLine"
    Info "Added seedling to $PROFILE"
}

Info "seedling is installed."
Write-Host ""
if ($DevReady) {
    Write-Host "Open a new terminal (or run: . `"$seedPs1`") --"
    Write-Host "the 'dev' venv auto-activates there, so you can immediately try:"
    Write-Host "  python / ipython          # the newest Python, ready to go"
    Write-Host "  seed install <package>    # add packages to 'dev'"
    Write-Host "  seed venv myproject       # create another venv"
    Write-Host "  seed summary              # see everything seedling has installed"
} else {
    Write-Host "Open a new terminal (or run: . `"$seedPs1`") and try:"
    Write-Host "  seed python               # install the newest Python"
    Write-Host "  seed venv myproject"
    Write-Host "  seed activate myproject"
    Write-Host "  seed summary"
}
Write-Host ""
Write-Host "Note: seed-cli was installed from a private copy at $SrcDir."
Write-Host "Nothing updates it automatically -- run 'seed update-commands' whenever"
Write-Host "you want to pull in changes."

# Completion marker for `seed logs-viewer` (it parses the exit code out of
# this exact line), then finalize the install log. Stop-Transcript matters
# most for piped `irm | iex` installs: without it the transcript keeps
# recording the user's session long after the install finished. Guarded:
# transcription may never have started (locked logs dir).
Write-Host "seedling install completed (exit code 0)"
try { Stop-Transcript | Out-Null } catch { }
