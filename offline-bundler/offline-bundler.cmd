:; exec sh "$(dirname "$0")/offline-bundler.sh" "$@" # POSIX shells take this line; the trailing comment swallows the CR of the CRLF ending
@echo off
rem Build a self-contained, offline seedling bundle -- one file, every platform:
rem   Windows:     run `.\offline-bundler.cmd` (double-clicking works too)
rem   macOS/Linux: run `sh ./offline-bundler.cmd` (line 1 hands off to
rem                offline-bundler.sh; cmd.exe reads it as a label)
rem
rem Everything it needs is in offline-bundle.toml next to this file -- there
rem are no arguments to remember. This is NOT a `seed` command: it prepares
rem the distribution before seedling is installed anywhere. Needs Python
rem 3.12+ on THIS machine.
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0..\installers\build_offline.py" %*
    goto :seedling_done
)
where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0..\installers\build_offline.py" %*
    goto :seedling_done
)
echo.
echo Python 3.12+ is required to build the offline bundle, but none was found.
echo Install it from https://www.python.org/downloads/ and re-run this file.
exit /b 1
:seedling_done
if errorlevel 1 (
    pause
    exit /b 1
)
