:; exec sh "$(dirname "$0")/installers/build_offline.sh" "$@" # POSIX shells take this line; the trailing comment swallows the CR of the CRLF ending
@echo off
rem Build a self-contained, offline seedling bundle -- one file, every platform:
rem   Windows:     run `.\build-offline.cmd` (double-clicking works too)
rem   macOS/Linux: run `sh ./build-offline.cmd` (line 1 hands off to
rem                installers/build_offline.sh; cmd.exe reads it as a label)
rem This is NOT a `seed` command -- it prepares the distribution before
rem seedling is installed anywhere. It needs Python 3.12+ on THIS machine.
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0installers\build_offline.py" %*
    goto :seedling_done
)
where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0installers\build_offline.py" %*
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
