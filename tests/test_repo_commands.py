"""Repo family: name derivation, repo-cd resolution, clone against a local
bare repo (git file protocol -- the share-only workflow), repo-open /
repo-vscode validation, repo-install detection."""

from __future__ import annotations

import subprocess

import pytest

from conftest import GIT, needs_git
from seedling.commands import repo_cmd


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/you/some-project.git", "some-project"),
    ("git@host:group/name.git", "name"),
    ("git@host:name.git", "name"),
    ("S:/repos/project.git", "project"),
    (r"S:\repos\project.git", "project"),           # windows share path
    (r"C:\Users\me\upstream-project", "upstream-project"),
    ("./local/path/", "path"),
])
def test_derive_name(url, expected):
    assert repo_cmd._derive_name(url) == expected


def test_repo_cd_print_path_variants(run_cli, home):
    (home / "repo" / "myproj").mkdir(parents=True)
    code, out = run_cli("repo-cd", "myproj", "--print-path")
    assert code == 0 and out.strip() == str(home / "repo" / "myproj")
    code, out = run_cli("repo-cd", "--print-path")
    assert code == 0 and out.strip() == str(home / "repo")
    code, out = run_cli("repo-cd", "ghost", "--print-path")
    assert code == 1 and "No repo named 'ghost'" in out


def test_repo_cd_without_wrapper_explains(run_cli, home):
    (home / "repo" / "myproj").mkdir(parents=True)
    code, out = run_cli("repo-cd", "myproj")
    assert code == 0 and "shell function" in out


def test_repo_vscode_and_open_validate_missing(run_cli, home):
    code, out = run_cli("repo-vscode", "ghost")
    assert code == 1 and "No repo named" in out
    code, out = run_cli("repo-vscode")
    assert code == 1 and "Usage" in out
    code, out = run_cli("repo-open", "ghost")
    assert code == 1 and "No repo named" in out


def test_repo_open_launches_file_manager(run_cli, home, monkeypatch):
    (home / "repo" / "myproj").mkdir(parents=True)
    opened = {}
    monkeypatch.setattr(repo_cmd.os, "startfile",
                        lambda p: opened.setdefault("path", p), raising=False)
    monkeypatch.setattr(repo_cmd.platform, "system", lambda: "Windows")
    code, out = run_cli("repo-open", "myproj")
    assert code == 0
    assert opened["path"] == str(home / "repo" / "myproj")


def test_repo_install_requires_manifest(run_cli, home, monkeypatch):
    (home / "repo" / "bare").mkdir(parents=True)
    monkeypatch.setenv("VIRTUAL_ENV", "something")  # silence the note
    code, out = run_cli("repo-install", "bare")
    assert code == 1 and "Nothing to install" in out


def test_repo_install_picks_pyproject_over_requirements(run_cli, home, monkeypatch):
    repo = home / "repo" / "proj"
    repo.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n")
    (repo / "requirements.txt").write_text("requests\n")
    calls = []
    from seedling import uv_tool
    monkeypatch.setattr(uv_tool, "run", lambda args, **kw: calls.append(args))
    monkeypatch.setenv("VIRTUAL_ENV", "something")
    code, out = run_cli("repo-install", "proj")
    assert code == 0
    assert calls and calls[0][:3] == ["pip", "install", "-e"]


@needs_git
class TestGitFileProtocol:
    """The share-only story: bare repos on a plain path are full remotes."""

    def test_clone_from_bare_repo_keeps_git_dir(self, run_cli, home, tmp_path):
        upstream = tmp_path / "upstream-project"
        work = tmp_path / "work"
        work.mkdir()
        (work / "main.py").write_text("print('hi')\n")
        subprocess.run([GIT, "init", "-q", str(work)], check=True)
        subprocess.run([GIT, "-C", str(work), "add", "-A"], check=True)
        subprocess.run([GIT, "-C", str(work), "-c", "user.email=t@t",
                        "-c", "user.name=t", "commit", "-qm", "init"], check=True)
        subprocess.run([GIT, "clone", "-q", "--bare", str(work), str(upstream)],
                       check=True)

        code, out = run_cli("repo-clone", str(upstream))
        assert code == 0
        cloned = home / "repo" / "upstream-project"
        assert (cloned / "main.py").exists()
        assert (cloned / ".git").is_dir(), "cloned working repos must keep .git"

        code, out = run_cli("repo-list")
        assert "upstream-project" in out

        code, out = run_cli("repo-clone", str(upstream))
        assert code == 1 and "already exists" in out

        code, out = run_cli("remove-repo", "upstream-project", "-y")
        assert code == 0
        assert not cloned.exists()
