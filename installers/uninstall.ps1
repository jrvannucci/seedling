# Standalone seedling uninstaller (PowerShell) -- removes the managed folder
# AND the $PROFILE hook line.
#
# The normal way to uninstall is `seed purge` (more thorough, and it knows
# its own install location). This script is the FALLBACK for when seed-cli
# itself is broken and can't run. It resolves the install location the same
# way the installer did -- SEEDLING_HOME env override, else global.conf's
# SEEDLING_HOME_DIR with "~" and "{user}" expansion -- so relocated and
# shared multi-user installs are targeted correctly, not a hardcoded
# ~\seedling.
$ErrorActionPreference = "Stop"

# This script lives in installers\; the conf is in GET_STARTED\ alongside it.
# $MyInvocation.MyCommand.Path is $null when this is run via `irm ... | iex`
# (no backing file), so guard against that before Split-Path -- and fall
# back to SEEDLING_HOME / the default location when there's no local conf.
$ScriptPath = $MyInvocation.MyCommand.Path
$ScriptDir = if ($ScriptPath) { Split-Path -Parent $ScriptPath } else { $null }
$RepoRoot = if ($ScriptDir) { Split-Path -Parent $ScriptDir } else { $null }
$Conf = @{}
if ($RepoRoot) {
    $confPath = Join-Path $RepoRoot "GET_STARTED\global.conf"
    if (Test-Path $confPath) {
        foreach ($line in Get-Content $confPath) {
            if ($line -match '^\s*([A-Z_]+)\s*=\s*"([^"]*)"\s*$') { $Conf[$Matches[1]] = $Matches[2] }
        }
    }
}

# Home resolution -- identical to the installer.
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
# {user} -> current login name: removes THIS user's install, like `seed purge`.
if ($SeedlingHome -like "*{user}*") {
    $SeedlingHome = $SeedlingHome -replace [regex]::Escape("{user}"), $env:USERNAME
}

Write-Host "Uninstalling seedling at: $SeedlingHome"

if (Test-Path $PROFILE) {
    # Match any line sourcing a seed shell script from under the seedling
    # home -- not just the exact current hook text -- so hooks written by
    # older seedling layouts (e.g. ~\seedling\shell\ before it moved under
    # system\) are cleaned up too instead of erroring in every new shell.
    $lines = Get-Content $PROFILE | Where-Object {
        -not ($_.Contains($SeedlingHome) -and ($_ -match "seed\.(ps1|sh)")) -and $_.Trim() -ne "# seedling"
    }
    Set-Content -Path $PROFILE -Value $lines
    Write-Host "Removed seedling hook from $PROFILE"
}

if (Test-Path $SeedlingHome) {
    Remove-Item -Recurse -Force $SeedlingHome
    Write-Host "Removed $SeedlingHome"
}

Write-Host "seedling fully uninstalled. Open a new terminal for it to take effect."
