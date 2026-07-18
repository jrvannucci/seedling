"""Safety property: in a shared-root install (SEEDLING_HOME_DIR with a
{user} token), one user's `seed purge` / `seed remove-user` must delete
ONLY their own subfolder -- never a sibling user's folder, the shared
parent, or another user's profile hook."""

from __future__ import annotations

import pathlib

import pytest

import conftest


def _make_user(shared_root, os_homes, name):
    """A full mini seedling home for `name` under the shared root, plus a
    separate per-user OS home with a profile hook pointing at it."""
    home = shared_root / name
    for sub in ("system/bin", "system/config", "system/shell",
                "python/venvs/dev", "repo/proj", "extensions"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    (home / "system/config/settings.json").write_text('{"default_venv": "dev"}')
    (home / "python/venvs/dev/marker.txt").write_text(f"{name}'s venv")
    (home / "repo/proj/code.py").write_text(f"{name}'s repo")
    (home / "system/shell/seed.ps1").write_text("# hook target")

    oshome = os_homes / name
    profile = oshome / "Documents" / "WindowsPowerShell"
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "Microsoft.PowerShell_profile.ps1").write_text(
        "unrelated config line\n"
        "# seedling\n"
        f'. "{home}\\system\\shell\\seed.ps1"\n')
    return home, oshome


@pytest.fixture
def three_users(tmp_path, monkeypatch):
    """alice/bob/carol sharing one root. Returns the homes plus a helper to
    'become' a given user (rebind seedling paths + Path.home())."""
    shared = tmp_path / "shared"          # the C:\seedling equivalent
    os_homes = tmp_path / "oshomes"       # the C:\Users\<user> equivalents
    users = {name: _make_user(shared, os_homes, name)
             for name in ("alice", "bob", "carol")}

    for var in conftest._ISOLATED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SEEDLING_NO_LOG", "1")
    monkeypatch.setenv("SEEDLING_YES", "1")  # skip the confirmation prompt

    from seedling.commands import kill_cmd
    monkeypatch.setattr(kill_cmd, "kill_python_and_vscode", lambda: [])

    def become(name):
        home, oshome = users[name]
        conftest._rebind_paths(home)
        monkeypatch.setenv("SEEDLING_HOME", str(home))
        monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: oshome))

    yield shared, os_homes, users, become
    conftest._restore_paths()


def _assert_intact(home):
    assert home.exists()
    assert (home / "python/venvs/dev/marker.txt").exists()
    assert (home / "repo/proj/code.py").read_text().endswith("repo")


def test_purge_deletes_only_current_user(three_users):
    from seedling import cli
    shared, os_homes, users, become = three_users
    alice_home = users["alice"][0]
    bob_home = users["bob"][0]
    carol_home = users["carol"][0]

    become("alice")
    assert cli.main(["purge"]) == 0

    # alice gone; the shared parent and both siblings fully intact
    assert not alice_home.exists()
    assert shared.exists()
    _assert_intact(bob_home)
    _assert_intact(carol_home)


def test_purge_only_strips_current_users_hook(three_users):
    from seedling import cli
    shared, os_homes, users, become = three_users

    become("alice")
    cli.main(["purge"])

    # bob's and carol's profiles (separate OS homes) are untouched
    for name in ("bob", "carol"):
        oshome = users[name][1]
        prof = (oshome / "Documents" / "WindowsPowerShell"
                / "Microsoft.PowerShell_profile.ps1").read_text()
        assert "seedling" in prof and users[name][0].name in prof


def test_remove_user_deletes_only_current_user(three_users):
    from seedling import cli
    shared, os_homes, users, become = three_users
    alice_home = users["alice"][0]

    become("alice")
    assert cli.main(["remove-user"]) == 0

    assert not alice_home.exists()
    assert shared.exists()
    _assert_intact(users["bob"][0])
    _assert_intact(users["carol"][0])


def test_preview_lists_only_current_user(three_users, capsys):
    from seedling import cli
    shared, os_homes, users, become = three_users
    become("alice")
    cli.main(["purge", "--preview"])
    out = capsys.readouterr().out
    assert str(users["alice"][0]) in out
    # no sibling paths leak into the preview
    assert str(users["bob"][0]) not in out
    assert str(users["carol"][0]) not in out


def test_repo_backup_stays_in_current_users_os_home(three_users):
    from seedling import cli
    shared, os_homes, users, become = three_users
    become("alice")
    cli.main(["purge", "--keep-repos"])
    # backup landed under alice's OS home, not the shared root or a sibling
    alice_os = users["alice"][1]
    backup = alice_os / "seedling-repo-backup"
    assert (backup / "proj" / "code.py").read_text().endswith("repo")
    assert not (os_homes / "bob" / "seedling-repo-backup").exists()
    assert not (shared / "seedling-repo-backup").exists()
