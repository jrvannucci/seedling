"""The `seed` shell functions rendered from both templates: repo-cd
directory changes, auto-deactivation when the active venv vanishes, the
purge wait-and-confirm flow, and PowerShell parse validity."""

from __future__ import annotations

import subprocess
import textwrap


from conftest import (POWERSHELL, REPO_ROOT, needs_bash,
                      needs_powershell, run_bash)

SH_TEMPLATE = REPO_ROOT / "src" / "seedling" / "shell" / "seed.sh.template"
PS_TEMPLATE = REPO_ROOT / "src" / "seedling" / "shell" / "seed.ps1.template"


def _render_sh(tmp_path, home) -> str:
    rendered = tmp_path / "seed.sh"
    rendered.write_text(
        SH_TEMPLATE.read_text().replace("__SEEDLING_HOME_PLACEHOLDER__",
                                        home.as_posix()))
    return rendered.as_posix()


def _stub_cli(home, body: str) -> None:
    bin_dir = home / "system" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "seed-cli"
    stub.write_text("#!/bin/sh\n" + body)
    stub.chmod(0o755)


@needs_bash
class TestBashFunction:
    def test_template_renders_and_parses(self, tmp_path):
        rendered = _render_sh(tmp_path, tmp_path / "seedling")
        assert run_bash(f"sh -n '{rendered}'").returncode == 0

    def test_repo_cd_changes_directory(self, tmp_path):
        home = tmp_path / "seedling"
        repo = home / "repo" / "myproj"
        repo.mkdir(parents=True)
        _stub_cli(home, textwrap.dedent(f"""\
            if [ "$1" = "repo-cd" ] && [ "$3" = "--print-path" ]; then
                if [ "$2" = "myproj" ]; then echo "{repo.as_posix()}"; exit 0; fi
                exit 1
            fi
            [ "$1" = "repo-cd" ] && echo "No repo named '$2'"
            exit 0
        """))
        rendered = _render_sh(tmp_path, home)
        result = run_bash(
            f"VIRTUAL_ENV=keep . '{rendered}'; cd /tmp; "
            f"seed repo-cd myproj >/dev/null; pwd; "
            f"seed repo-cd ghost >/dev/null 2>&1; echo exit=$?")
        # git-bash reports MSYS-translated paths; compare on the stable tail
        assert result.stdout.splitlines()[0].endswith("seedling/repo/myproj")
        assert "exit=1" in result.stdout

    def test_auto_activate_false_skips_startup_and_the_spawn(self, tmp_path):
        """`seed auto-activate False` is honoured by a plain grep of
        settings.json -- no seed-cli launch at all, and no activation."""
        home = tmp_path / "seedling"
        (home / "system" / "config").mkdir(parents=True)
        (home / "system" / "config" / "settings.json").write_text(
            '{\n  "auto_activate": false,\n  "default_venv": "dev"\n}\n')
        log = home / "system" / "bin" / "calls.log"
        _stub_cli(home, f'echo "$*" >> "{log.as_posix()}"\n'
                        f'[ "$1 $2 $3" = "config get default_venv" ] && echo dev\n'
                        f'exit 0\n')
        rendered = _render_sh(tmp_path, home)
        result = run_bash(
            f"unset VIRTUAL_ENV; . '{rendered}'; "
            f"echo \"VE=[${{VIRTUAL_ENV:-}}]\"")
        assert "VE=[]" in result.stdout                 # not activated
        assert not log.exists(), "seed-cli must not be spawned when off"

    def test_auto_activate_true_activates_at_startup(self, tmp_path):
        home = tmp_path / "seedling"
        (home / "system" / "config").mkdir(parents=True)
        (home / "system" / "config" / "settings.json").write_text(
            '{\n  "auto_activate": true,\n  "default_venv": "dev"\n}\n')
        activate = home / "python" / "venvs" / "dev" / "bin" / "activate"
        activate.parent.mkdir(parents=True)
        activate.write_text("VIRTUAL_ENV=ACTIVATED-DEV; export VIRTUAL_ENV\n"
                            "deactivate() { unset VIRTUAL_ENV; unset -f deactivate; }\n")
        _stub_cli(home, textwrap.dedent(f"""\
            [ "$1 $2 $3" = "config get default_venv" ] && echo dev
            if [ "$1" = "activate" ] && [ "$3" = "--print-path" ]; then
                echo "{activate.as_posix()}"
            fi
            exit 0
        """))
        rendered = _render_sh(tmp_path, home)
        result = run_bash(
            f"unset VIRTUAL_ENV; . '{rendered}'; echo \"VE=[${{VIRTUAL_ENV:-}}]\"")
        assert "VE=[ACTIVATED-DEV]" in result.stdout

    def test_auto_deactivate_when_active_venv_deleted(self, tmp_path):
        home = tmp_path / "seedling"
        venv = home / "python" / "venvs" / "dev"
        venv.mkdir(parents=True)
        _stub_cli(home, textwrap.dedent(f"""\
            [ "$1" = "remove-venv" ] && rm -rf "{venv.as_posix()}"
            exit 0
        """))
        rendered = _render_sh(tmp_path, home)
        result = run_bash(
            f"VIRTUAL_ENV='{venv.as_posix()}'; "
            f"deactivate() {{ unset VIRTUAL_ENV; unset -f deactivate; }}; "
            f". '{rendered}'; seed remove-venv dev; "
            f"echo \"after=${{VIRTUAL_ENV:-unset}}\"")
        assert "deactivated: the venv this shell had active" in result.stdout
        assert "after=unset" in result.stdout

    def test_purge_waits_for_cleanup_and_confirms(self, tmp_path):
        home = tmp_path / "seedling"
        home.mkdir(parents=True)
        marker = tmp_path / "seedling-cleanup.pending"
        _stub_cli(home, textwrap.dedent(f"""\
            if [ "$1" = "purge" ]; then
                touch "{marker.as_posix()}"
                ( sleep 2; rm -rf "{home.as_posix()}"; rm -f "{marker.as_posix()}" ) >/dev/null 2>&1 &
            fi
            exit 0
        """))
        rendered = _render_sh(tmp_path, home)
        result = run_bash(
            f"VIRTUAL_ENV=keep . '{rendered}'; "
            f"TMPDIR='{tmp_path.as_posix()}' seed purge")
        assert "Waiting for the background cleanup" in result.stdout
        assert "has been fully removed" in result.stdout

    def test_purge_skips_wait_when_nothing_deferred(self, tmp_path):
        home = tmp_path / "seedling"
        home.mkdir(parents=True)
        _stub_cli(home, 'exit 0\n')
        rendered = _render_sh(tmp_path, home)
        result = run_bash(
            f"VIRTUAL_ENV=keep . '{rendered}'; "
            f"TMPDIR='{tmp_path.as_posix()}' seed purge")
        assert "Waiting" not in result.stdout

    def test_purge_and_reinstall_runs_staged_script_after_wipe(self, tmp_path):
        home = tmp_path / "seedling"
        home.mkdir(parents=True)
        sentinel = tmp_path / "reinstalled.sentinel"
        reinstall = tmp_path / "seedling-reinstall.sh"
        reinstall.write_text(f'#!/bin/sh\ntouch "{sentinel.as_posix()}"\n')
        # Synchronous wipe, no deferred marker -- mirrors POSIX purge.
        _stub_cli(home, textwrap.dedent(f"""\
            if [ "$1" = "purge-and-reinstall" ]; then
                rm -rf "{home.as_posix()}"
            fi
            exit 0
        """))
        rendered = _render_sh(tmp_path, home)
        result = run_bash(
            f"VIRTUAL_ENV=keep . '{rendered}'; "
            f"TMPDIR='{tmp_path.as_posix()}' seed purge-and-reinstall")
        assert "Reinstalling seedling" in result.stdout
        assert sentinel.exists()               # reinstall script actually ran
        assert not reinstall.exists()          # ... and was cleaned up

    def test_purge_and_reinstall_skips_reinstall_if_home_survives(self, tmp_path):
        home = tmp_path / "seedling"
        home.mkdir(parents=True)
        sentinel = tmp_path / "reinstalled.sentinel"
        reinstall = tmp_path / "seedling-reinstall.sh"
        reinstall.write_text(f'#!/bin/sh\ntouch "{sentinel.as_posix()}"\n')
        # CLI reports success but the tree is NOT gone (e.g. a stuck file):
        # the installer must never run against a half-deleted tree.
        _stub_cli(home, 'exit 0\n')
        rendered = _render_sh(tmp_path, home)
        result = run_bash(
            f"VIRTUAL_ENV=keep . '{rendered}'; "
            f"TMPDIR='{tmp_path.as_posix()}' seed purge-and-reinstall")
        assert "Reinstalling seedling" not in result.stdout
        assert not sentinel.exists()


@needs_powershell
class TestPowerShellFunction:
    def _run_ps(self, script: str):
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=120)

    def test_template_parses(self, tmp_path):
        rendered = tmp_path / "seed.ps1"
        rendered.write_text(
            PS_TEMPLATE.read_text().replace("__SEEDLING_HOME_PLACEHOLDER__",
                                            str(tmp_path / "seedling")))
        result = self._run_ps(
            f"$e = $null; "
            f"[System.Management.Automation.PSParser]::Tokenize("
            f"(Get-Content '{rendered}' -Raw), [ref]$e) | Out-Null; "
            f"if ($e.Count) {{ exit 1 }} else {{ 'PARSE-OK' }}")
        assert "PARSE-OK" in result.stdout

    def test_install_forwards_dash_e_flag(self, tmp_path):
        """`seed install -e <path>` must reach the CLI verbatim. A bare `-e`
        used to die inside the `seed` function as an ambiguous prefix of the
        common params -ErrorAction/-ErrorVariable (the function was an advanced
        function); it's now a simple function whose $args passes flags through."""
        home = tmp_path / "seedling"
        home.mkdir(parents=True)
        rendered = tmp_path / "seed.ps1"
        rendered.write_text(
            PS_TEMPLATE.read_text().replace("__SEEDLING_HOME_PLACEHOLDER__", str(home)))
        # Simple stub (automatic $args, no param binding) that echoes what it got.
        stub = tmp_path / "stub.ps1"
        stub.write_text('Write-Output ("GOT:" + ($args -join "|"))\n')
        result = self._run_ps(
            f"$env:VIRTUAL_ENV = 'keep'; . '{rendered}'; "
            f"$script:SeedlingCli = '{stub}'; "
            f"seed install -e C:\\proj\\thing; "
            # --verbose would be SWALLOWED by the common -Verbose param if the
            # function were still advanced; assert it reaches the CLI too.
            f"seed install --verbose requests")
        assert "GOT:install|-e|C:\\proj\\thing" in result.stdout, \
            result.stdout + result.stderr
        assert "GOT:install|--verbose|requests" in result.stdout, \
            result.stdout + result.stderr

    def test_startup_activates_default_venv_without_launching_seed_cli(self, tmp_path):
        """Opening a shell auto-activates the default venv by reading
        settings.json and dot-sourcing the venv's Activate.ps1 directly -- it
        must NOT spawn seed-cli (a Python process, ~350ms cold), which used to
        run twice here and dominated terminal-open time. seed-cli.exe does not
        even exist in this test, so any attempt to invoke it would surface as a
        CommandNotFound error -- whose ABSENCE proves the fast path was taken."""
        home = tmp_path / "seedling"
        (home / "system" / "config").mkdir(parents=True)
        (home / "system" / "config" / "settings.json").write_text(
            '{ "default_venv": "dev" }', encoding="utf-8")
        scripts = home / "python" / "venvs" / "dev" / "Scripts"
        scripts.mkdir(parents=True)
        (scripts / "Activate.ps1").write_text(
            "$env:VIRTUAL_ENV = 'ACTIVATED-DEV'\n"
            "function global:deactivate { Remove-Item Env:VIRTUAL_ENV }\n")
        rendered = tmp_path / "seed.ps1"
        rendered.write_text(
            PS_TEMPLATE.read_text().replace("__SEEDLING_HOME_PLACEHOLDER__", str(home)))
        result = self._run_ps(
            f"Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue; "
            f". '{rendered}'; Write-Output \"VE=$env:VIRTUAL_ENV\"")
        out = result.stdout + result.stderr
        assert "VE=ACTIVATED-DEV" in out, out          # the venv was activated
        assert "seed-cli" not in out, out              # ...without invoking the CLI
        assert "CommandNotFound" not in out, out

    def test_auto_activate_false_skips_startup_activation(self, tmp_path):
        """`seed auto-activate False` leaves default_venv set but stops new
        shells activating it -- and still without launching seed-cli."""
        home = tmp_path / "seedling"
        (home / "system" / "config").mkdir(parents=True)
        (home / "system" / "config" / "settings.json").write_text(
            '{ "auto_activate": false, "default_venv": "dev" }', encoding="utf-8")
        scripts = home / "python" / "venvs" / "dev" / "Scripts"
        scripts.mkdir(parents=True)
        (scripts / "Activate.ps1").write_text("$env:VIRTUAL_ENV = 'ACTIVATED-DEV'\n")
        rendered = tmp_path / "seed.ps1"
        rendered.write_text(
            PS_TEMPLATE.read_text().replace("__SEEDLING_HOME_PLACEHOLDER__", str(home)))
        result = self._run_ps(
            f"Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue; "
            f". '{rendered}'; Write-Output \"VE=[$env:VIRTUAL_ENV]\"")
        out = result.stdout + result.stderr
        assert "VE=[]" in out, out                      # not activated
        assert "seed-cli" not in out, out               # ...and no spawn

    def test_absent_auto_activate_key_still_activates(self, tmp_path):
        """Older settings files predate the key; absence must mean ON."""
        home = tmp_path / "seedling"
        (home / "system" / "config").mkdir(parents=True)
        (home / "system" / "config" / "settings.json").write_text(
            '{ "default_venv": "dev" }', encoding="utf-8")
        scripts = home / "python" / "venvs" / "dev" / "Scripts"
        scripts.mkdir(parents=True)
        (scripts / "Activate.ps1").write_text("$env:VIRTUAL_ENV = 'ACTIVATED-DEV'\n")
        rendered = tmp_path / "seed.ps1"
        rendered.write_text(
            PS_TEMPLATE.read_text().replace("__SEEDLING_HOME_PLACEHOLDER__", str(home)))
        result = self._run_ps(
            f"Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue; "
            f". '{rendered}'; Write-Output \"VE=[$env:VIRTUAL_ENV]\"")
        assert "VE=[ACTIVATED-DEV]" in (result.stdout + result.stderr)

    def test_startup_falls_back_to_seed_cli_when_activate_script_missing(self, tmp_path):
        """If the venv isn't where the shortcut expects (custom layout, deleted
        venv), it still defers to `seed activate` so behavior is never lost."""
        home = tmp_path / "seedling"
        (home / "system" / "config").mkdir(parents=True)
        (home / "system" / "config" / "settings.json").write_text(
            '{ "default_venv": "ghost" }', encoding="utf-8")
        rendered = tmp_path / "seed.ps1"
        rendered.write_text(
            PS_TEMPLATE.read_text().replace("__SEEDLING_HOME_PLACEHOLDER__", str(home)))
        stub = tmp_path / "stub.ps1"
        stub.write_text(
            'param([Parameter(ValueFromRemainingArguments=$true)][string[]]$A)\n'
            'if ($A[0] -eq "activate") { Write-Output "FALLBACK-ACTIVATE"; exit 1 }\n'
            'exit 0\n')
        result = self._run_ps(
            f"Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue; "
            f". '{rendered}'; $script:SeedlingCli = '{stub}'; "
            f"seed activate ghost")
        assert "FALLBACK-ACTIVATE" in (result.stdout + result.stderr)

    def test_repo_cd_changes_directory(self, tmp_path):
        home = tmp_path / "seedling"
        repo = home / "repo" / "myproj"
        repo.mkdir(parents=True)
        rendered = tmp_path / "seed.ps1"
        rendered.write_text(
            PS_TEMPLATE.read_text().replace("__SEEDLING_HOME_PLACEHOLDER__", str(home)))
        stub = tmp_path / "stub.ps1"
        stub.write_text(textwrap.dedent(f"""\
            param([Parameter(ValueFromRemainingArguments = $true)][string[]]$A)
            if ($A[0] -eq "repo-cd" -and $A[-1] -eq "--print-path") {{
                if ($A[1] -eq "myproj") {{ "{repo}"; exit 0 }}
                exit 1
            }}
            exit 0
        """))
        result = self._run_ps(
            f"$env:VIRTUAL_ENV = 'keep'; . '{rendered}'; "
            f"Remove-Item Env:VIRTUAL_ENV; "
            f"$script:SeedlingCli = '{stub}'; "
            f"Set-Location $env:TEMP; seed repo-cd myproj | Out-Null; "
            f"(Get-Location).Path")
        assert str(repo) in result.stdout
