"""The admin-* family: elevation gating, hidden help, cross-user targeting
under a shared root, ACL-busting force-delete, and preview/confirm.

`admin.take_ownership` (takeown/icacls) is stubbed everywhere -- test
files are owned by the test user, so robust_rmtree alone removes them; we
assert the ownership step is *invoked*, not that it does real ACL work."""

from __future__ import annotations


import pytest

import conftest
from seedling import admin


@pytest.fixture
def shared_install(tmp_path, monkeypatch):
    """A shared root with three user homes; the current process is 'admin'.
    Yields (root, users, become_elevated)."""
    root = tmp_path / "seedling"          # the shared root (C:\seedling)
    users = {}
    for name in ("alice", "bob", "carol"):
        home = root / name
        for sub in ("system/bin", "python/venvs/dev", "python/base",
                    "repo/proj"):
            (home / sub).mkdir(parents=True, exist_ok=True)
        (home / "python/venvs/dev/marker").write_text(f"{name}")
        (home / "repo/proj/code.py").write_text(f"{name}")
        users[name] = home

    # "become" the admin user, whose own home is a sibling under the root
    admin_home = root / "admin"
    (admin_home / "system").mkdir(parents=True)
    for var in conftest._ISOLATED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SEEDLING_NO_LOG", "1")
    monkeypatch.setenv("SEEDLING_YES", "1")
    conftest._rebind_paths(admin_home)
    # a shared-root install records this at install time; the admin family
    # refuses to run without it
    from seedling import config
    config.set_value("shared_root", str(root))
    from seedling.commands import kill_cmd
    monkeypatch.setattr(kill_cmd, "kill_python_and_vscode", lambda: [])

    # record take_ownership calls; skip the real takeown/icacls
    calls = []
    monkeypatch.setattr(admin, "take_ownership", lambda p: calls.append(p))

    yield root, users, calls
    conftest._restore_paths()


def _run(*argv):
    from seedling import cli
    return cli.main(list(argv))


# --- elevation gating -------------------------------------------------------

def test_admin_refuses_without_elevation(shared_install, monkeypatch, capsys):
    monkeypatch.setattr(admin, "is_elevated", lambda: False)
    code = _run("admin-purge-all-users", "-y")
    assert code == 1
    assert "must run" in capsys.readouterr().out


def test_admin_proceeds_when_elevated(shared_install, monkeypatch):
    root, users, calls = shared_install
    monkeypatch.setattr(admin, "is_elevated", lambda: True)
    assert _run("admin-remove-user", "alice", "-y") == 0
    assert not users["alice"].exists()


# --- hidden help ------------------------------------------------------------

def test_help_hides_admin_by_default(shared_install, capsys):
    _run("help")
    out = capsys.readouterr().out
    assert "admin-" not in out
    assert "seed help --admin" in out


def test_help_admin_reveals_family(shared_install, capsys):
    _run("help", "--admin")
    out = capsys.readouterr().out
    for cmd in ("admin-purge-all-users", "admin-remove-user",
                "admin-remove-venv", "admin-remove-python", "admin-remove-repo"):
        assert cmd in out


# --- cross-user targeting + isolation ---------------------------------------

def test_remove_user_targets_only_that_user(shared_install, monkeypatch):
    root, users, calls = shared_install
    monkeypatch.setattr(admin, "is_elevated", lambda: True)
    _run("admin-remove-user", "alice", "-y")
    assert not users["alice"].exists()
    assert users["bob"].exists() and users["carol"].exists()
    assert users["alice"] in calls  # ownership was taken before delete


def test_remove_user_unknown(shared_install, monkeypatch, capsys):
    monkeypatch.setattr(admin, "is_elevated", lambda: True)
    assert _run("admin-remove-user", "nobody", "-y") == 1
    assert "No seedling install for user 'nobody'" in capsys.readouterr().out


def test_venv_remove_one_user(shared_install, monkeypatch):
    root, users, calls = shared_install
    monkeypatch.setattr(admin, "is_elevated", lambda: True)
    _run("admin-remove-venv", "bob", "dev", "-y")
    assert not (users["bob"] / "python/venvs/dev").exists()
    assert users["bob"].exists()  # rest of bob's install intact
    assert (users["alice"] / "python/venvs/dev").exists()  # alice untouched


def test_repo_remove_one_user(shared_install, monkeypatch):
    root, users, calls = shared_install
    monkeypatch.setattr(admin, "is_elevated", lambda: True)
    _run("admin-remove-repo", "carol", "proj", "-y")
    assert not (users["carol"] / "repo/proj").exists()
    assert (users["bob"] / "repo/proj").exists()


def test_python_remove_takes_dependent_venvs(shared_install, monkeypatch):
    root, users, calls = shared_install
    monkeypatch.setattr(admin, "is_elevated", lambda: True)
    alice = users["alice"]
    base = alice / "python/base/cpython-3.12.5"
    base.mkdir(parents=True)
    (alice / "python/base/312.alias.json").write_text(
        '{"target": "cpython-3.12.5"}')
    (alice / "python/venvs/dev/pyvenv.cfg").write_text(
        f"home = {base.resolve()}\n")
    _run("admin-remove-python", "alice", "312", "-y")
    assert not base.exists()
    assert not (alice / "python/base/312.alias.json").exists()
    assert not (alice / "python/venvs/dev").exists()  # dependent venv gone


# --- preview ----------------------------------------------------------------

def test_purge_all_preview_lists_every_user(shared_install, monkeypatch, capsys):
    root, users, calls = shared_install
    monkeypatch.setattr(admin, "is_elevated", lambda: True)
    _run("admin-purge-all-users", "--preview")
    out = capsys.readouterr().out
    assert "Preview" in out and "nothing was changed" in out
    for name in ("alice", "bob", "carol"):
        assert str(users[name]) in out
    assert users["alice"].exists()  # preview deletes nothing


def test_purge_all_removes_all_users(shared_install, monkeypatch):
    root, users, calls = shared_install
    monkeypatch.setattr(admin, "is_elevated", lambda: True)
    assert _run("admin-purge-all-users", "-y") == 0
    for name in ("alice", "bob", "carol"):
        assert not users[name].exists()


# --- helpers ----------------------------------------------------------------

def test_list_user_homes_and_resolve(shared_install):
    root, users, calls = shared_install
    homes = {h.name for h in admin.list_user_homes()}
    assert {"alice", "bob", "carol"}.issubset(homes)
    assert admin.resolve_user_home("bob") == users["bob"]
    assert admin.resolve_user_home("ghost") is None


def test_non_shared_layout_refuses(tmp_path, monkeypatch, capsys):
    """A plain ~/seedling (no shared_root recorded) is not a shared install:
    admin commands must refuse, not guess."""
    lone = tmp_path / "home" / "seedling"
    (lone / "system").mkdir(parents=True)
    for var in conftest._ISOLATED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SEEDLING_NO_LOG", "1")
    monkeypatch.setenv("SEEDLING_YES", "1")
    conftest._rebind_paths(lone)
    monkeypatch.setattr(admin, "is_elevated", lambda: True)
    monkeypatch.setattr(admin, "take_ownership", lambda p: None)
    try:
        code = _run("admin-purge-all-users", "-y")
        assert code == 1
        assert "isn't a shared multi-user install" in capsys.readouterr().out
        assert lone.exists()  # nothing deleted
    finally:
        conftest._restore_paths()
