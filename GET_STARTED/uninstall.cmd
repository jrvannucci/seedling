:; exec sh "$(dirname "$0")/../installers/uninstall.sh" # POSIX shells take this line; the comment also swallows the CR of the CRLF line ending
@echo off
rem The generic seedling uninstaller -- one file, every platform:
rem   Windows:     double-click this file, or run `.\GET_STARTED\uninstall.cmd`
rem   macOS/Linux: run `sh ./GET_STARTED/uninstall.cmd` (line 1 hands off to
rem                installers/uninstall.sh; cmd.exe reads that same line as
rem                a label and skips it)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\installers\uninstall.ps1" %*
if errorlevel 1 pause
