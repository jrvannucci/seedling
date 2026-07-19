"""Destructive commands: previews, confirmation gating, non-interactive
mode, actual deletion, purge screens (reinstall variants, backup cleanup),
and the confirm module itself."""

from __future__ import annotations


import pytest

from conftest import make_base_python, make_venv_dirs
from seedling import config, confirm, paths


# --- confirm module ---------------------------------------------------------

class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_auto_confirmed_via_flag_and_env(home, monkeypatch):
    assert confirm.auto_confirmed(_Args(yes=True))
    assert not confirm.auto_confirmed(_Args(yes=False))
    monkeypatch.setenv("SEEDLING_YES", "1")
    assert confirm.auto_confirmed(_Args(yes=False))


def test_non_interactive_refuses_prompt(home, monkeypatch, capsys):
    monkeypatch.setenv("SEEDLING_NONINTERACTIVE", "1")
    assert confirm.confirm(_Args(yes=False)) is False
    assert "refusing to prompt" in capsys.readouterr().out
    # -y still proceeds without prompting
    assert confirm.confirm(_Args(yes=True)) is True


def test_confirm_accepts_only_yes(home, answer):
    answer("yes")
    assert confirm.confirm(_Args(yes=False)) is True
    answer("y")
    assert confirm.confirm(_Args(yes=False)) is False


def test_preview_requested(home):
    assert confirm.preview_requested(_Args(preview=True))
    assert not confirm.preview_requested(_Args(preview=False))
    assert not confirm.preview_requested(_Args())


# --- venv removal -----------------------------------------------------------

def test_venv_remove_preview_deletes_nothing(run_cli, home):
    make_venv_dirs(home, "dev")
    code, out = run_cli("remove-venv", "dev", "--preview")
    assert code == 0
    assert "Preview" in out and "nothing was changed" in out
    assert (home / "python" / "venvs" / "dev").exists()


def test_venv_remove_non_interactive_aborts(run_cli, home):
    make_venv_dirs(home, "dev")
    code, out = run_cli("remove-venv", "dev", "--non-interactive")
    assert code == 1
    assert "Aborted" in out
    assert (home / "python" / "venvs" / "dev").exists()


def test_venv_remove_yes_deletes(run_cli, home):
    make_venv_dirs(home, "dev")
    code, out = run_cli("remove-venv", "dev", "-y")
    assert code == 0
    assert not (home / "python" / "venvs" / "dev").exists()


def test_venv_remove_missing(run_cli, home):
    code, out = run_cli("remove-venv", "ghost", "-y")
    assert code == 1 and "No venv named" in out


def test_venv_remove_all(run_cli, home):
    make_venv_dirs(home, "a", "b", "c")
    code, out = run_cli("remove-venv-all", "--preview")
    assert "3 venv(s)" in out
    code, out = run_cli("remove-venv-all", "-y")
    assert code == 0 and "Deleted 3 venv(s)" in out
    assert not any((home / "python" / "venvs").iterdir())


# --- python removal ----------------------------------------------------------

def test_python_remove_takes_dependent_venvs(run_cli, home):
    base = make_base_python(home, "312", "cpython-3.12.5-windows-x86_64-none")
    make_venv_dirs(home, "dev")
    (home / "python" / "venvs" / "dev" / "pyvenv.cfg").write_text(
        f"home = {base}\nversion = 3.12.5\n")
    make_venv_dirs(home, "unrelated")  # points nowhere near this base
    config.set_default_base("312")

    code, out = run_cli("remove-python", "312", "--preview")
    assert code == 0 and "dev" in out and "unrelated" not in out

    code, out = run_cli("remove-python", "312", "-y")
    assert code == 0
    assert not base.exists()
    assert not (home / "python" / "base" / "312.alias.json").exists()
    assert not (home / "python" / "venvs" / "dev").exists()
    assert (home / "python" / "venvs" / "unrelated").exists()
    assert config.get_default_base() is None  # cleared, nothing left


# --- remove-user / purge ------------------------------------------------------

def test_remove_user_preview_and_delete(run_cli, home):
    paths.ensure_layout()
    code, out = run_cli("remove-user", "--preview")
    assert code == 0 and str(home) in out and home.exists()
    code, out = run_cli("remove-user", "-y")
    assert code == 0
    assert not home.exists()


def test_purge_confirmation_screen_lists_guidance(run_cli, home, answer):
    paths.ensure_layout()
    (home / "repo" / "proj").mkdir(parents=True)
    answer("no")
    code, out = run_cli("purge")
    assert code == 1  # aborted
    assert "smaller hammers" in out
    assert "seed remove-venv <name>" in out
    assert "--keep-repos" in out
    assert "To reinstall seedling later" in out
    assert home.exists()


@pytest.mark.parametrize("source,expect", [
    ("https://github.com/cryocliff/seedling.git", "raw.githubusercontent.com"),
    (None, "raw.githubusercontent.com"),
    (r"S:\tools\seedling", r"S:\tools\seedling\install.cmd"),
    ("https://github.mycompany.com/t/seedling.git", 'git clone "https://github.mycompany.com/t/seedling.git"'),
])
def test_purge_reinstall_matches_install_origin(run_cli, home, answer, source, expect):
    paths.ensure_layout()
    if source:
        config.set_value("update_source", source)
    answer("no")
    code, out = run_cli("purge")
    assert expect in out


def test_purge_without_keep_repos_removes_old_backups(run_cli, home, monkeypatch, tmp_path):
    fake_userhome = tmp_path / "userhome"
    (fake_userhome / "seedling-repo-backup" / "old").mkdir(parents=True)
    (fake_userhome / "seedling-repo-backup-1").mkdir(parents=True)
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: fake_userhome))
    paths.ensure_layout()
    code, out = run_cli("purge", "-y")
    assert code == 0
    assert not (fake_userhome / "seedling-repo-backup").exists()
    assert not (fake_userhome / "seedling-repo-backup-1").exists()
    assert not home.exists()


def test_purge_keep_repos_moves_them_to_safety(run_cli, home, monkeypatch, tmp_path):
    fake_userhome = tmp_path / "userhome"
    fake_userhome.mkdir()
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: fake_userhome))
    paths.ensure_layout()
    (home / "repo" / "proj").mkdir(parents=True)
    (home / "repo" / "proj" / "file.txt").write_text("keep me")
    code, out = run_cli("purge", "-y", "--keep-repos")
    assert code == 0
    assert not home.exists()
    backup = fake_userhome / "seedling-repo-backup"
    assert (backup / "proj" / "file.txt").read_text() == "keep me"


def test_purge_strips_hook_lines_old_and_new_layouts(run_cli, home, monkeypatch, tmp_path):
    fake_userhome = tmp_path / "userhome"
    profile_dir = fake_userhome / "Documents" / "WindowsPowerShell"
    profile_dir.mkdir(parents=True)
    profile = profile_dir / "Microsoft.PowerShell_profile.ps1"
    profile.write_text(
        "unrelated line\n"
        f'. "{home}\\shell\\seed.ps1"\n'          # old layout
        "# seedling\n"
        f'. "{home}\\system\\shell\\seed.ps1"\n'  # current layout
    )
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: fake_userhome))
    paths.ensure_layout()
    code, out = run_cli("purge", "-y")
    assert code == 0
    remaining = profile.read_text()
    assert "seed.ps1" not in remaining
    assert "unrelated line" in remaining


# --- purge-and-reinstall ------------------------------------------------------

def test_purge_and_reinstall_preview_reports_reinstall(run_cli, home):
    paths.ensure_layout()
    (home / "repo" / "proj").mkdir(parents=True)
    config.set_value("update_source", "https://github.mycompany.com/t/seedling.git")
    from seedling.commands import purge_cmd
    marker = purge_cmd._reinstall_marker()
    marker.unlink(missing_ok=True)

    code, out = run_cli("purge-and-reinstall", "--preview")
    assert code == 0
    assert "Preview" in out and "nothing was changed" in out
    assert "reinstalled from" in out
    assert "github.mycompany.com" in out
    assert "restored into the fresh install" in out
    assert home.exists()               # preview touches nothing
    assert not marker.exists()          # ... and stages no script


def test_purge_and_reinstall_writes_script_and_keeps_repos(
        run_cli, home, monkeypatch, tmp_path):
    fake_userhome = tmp_path / "userhome"
    fake_userhome.mkdir()
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: fake_userhome))
    # Keep the staged reinstall script inside the sandbox.
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    paths.ensure_layout()
    (home / "repo" / "proj").mkdir(parents=True)
    (home / "repo" / "proj" / "file.txt").write_text("keep me")
    source = r"S:\tools\seedling"
    config.set_value("update_source", source)

    code, out = run_cli("purge-and-reinstall", "-y")
    assert code == 0
    assert not home.exists()                       # wiped
    assert "reinstalling now" in out.lower()

    # Repos moved aside, ready for the reinstall script to restore.
    backup = fake_userhome / "seedling-repo-backup"
    assert (backup / "proj" / "file.txt").read_text() == "keep me"

    from seedling.commands import purge_cmd
    marker = purge_cmd._reinstall_marker()
    content = marker.read_text()
    assert source in content                       # source baked in
    assert str(backup) in content                  # restore-from
    assert str(paths.REPO_DIR) in content          # restore-into
    assert "install" in content                    # runs the installer
    marker.unlink(missing_ok=True)


def test_purge_and_reinstall_no_source_aborts_without_wiping(run_cli, home, answer):
    paths.ensure_layout()
    from seedling.commands import purge_cmd
    purge_cmd._reinstall_marker().unlink(missing_ok=True)
    answer("no")                                   # decline the public-repo offer
    code, out = run_cli("purge-and-reinstall")
    assert code == 1
    assert "Aborted" in out
    assert "update_source" in out
    assert home.exists()                           # nothing deleted
    assert not purge_cmd._reinstall_marker().exists()


def test_purge_and_reinstall_no_source_yes_uses_public(
        run_cli, home, monkeypatch, tmp_path):
    fake_userhome = tmp_path / "userhome"
    fake_userhome.mkdir()
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: fake_userhome))
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    paths.ensure_layout()

    code, out = run_cli("purge-and-reinstall", "-y")   # -y auto-accepts public repo
    assert code == 0
    assert not home.exists()

    from seedling.commands import purge_cmd
    marker = purge_cmd._reinstall_marker()
    assert "github.com/cryocliff/seedling" in marker.read_text()
    marker.unlink(missing_ok=True)


# --- kill-processes (list/preview only; never actually kill in tests) --------

def test_kill_processes_preview_lists_matches(run_cli, home):
    code, out = run_cli("kill-processes", "--system", "--preview")
    assert code == 0 and "Preview" in out and "nothing was changed" in out


def test_kill_processes_defaults_to_seedling_only(run_cli, home):
    """No arguments = the narrow mode. 'Something of mine is stuck' must not
    close a colleague's editor or an unrelated long-running job."""
    code, out = run_cli("kill-processes", "--preview")
    assert code == 0
    assert "seedling's own processes" in out
    assert "ALL Python and VS Code" not in out


def test_kill_processes_system_flag_is_machine_wide(run_cli, home):
    code, out = run_cli("kill-processes", "--system", "--preview")
    assert code == 0
    assert "ALL Python and VS Code processes on this machine" in out


def test_kill_processes_all_still_means_system_wide(run_cli, home):
    """`all` was the old spelling. Keep it machine-wide rather than silently
    NARROWING what an existing script does, and point at the new flag."""
    code, out = run_cli("kill-processes", "all", "--preview")
    assert code == 0
    assert "ALL Python and VS Code processes on this machine" in out
    assert "--system" in out


def test_kill_processes_rejects_name_with_system(run_cli, home):
    code, out = run_cli("kill-processes", "node", "--system")
    assert code == 1
    assert "not both" in out


def test_kill_processes_by_name_is_still_supported(run_cli, home):
    code, out = run_cli("kill-processes", "definitely-not-running", "--preview")
    assert code == 0
    assert "definitely-not-running" in out
