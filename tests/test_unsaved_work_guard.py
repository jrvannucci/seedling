"""Destructive commands must warn before deleting a repo that holds work
which exists nowhere else (uncommitted changes, or commits never pushed)."""

from __future__ import annotations

import subprocess

from conftest import GIT, needs_git
from seedling import git_tool, paths


def _init_repo(path, *, commit=True):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "init", "-q", str(path)], check=True)
    subprocess.run([GIT, "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run([GIT, "-C", str(path), "config", "user.name", "t"], check=True)
    if commit:
        (path / "tracked.txt").write_text("v1")
        subprocess.run([GIT, "-C", str(path), "add", "-A"], check=True)
        subprocess.run([GIT, "-C", str(path), "commit", "-qm", "init"], check=True)
    return path


@needs_git
def test_clean_repo_reports_nothing(tmp_path):
    """A warning that fires on every clean repo trains people to ignore it."""
    repo = _init_repo(tmp_path / "clean")
    assert git_tool.unsaved_work(repo) is None


@needs_git
def test_detects_uncommitted_changes(tmp_path):
    repo = _init_repo(tmp_path / "dirty")
    (repo / "tracked.txt").write_text("edited")
    assert "1 uncommitted change" in git_tool.unsaved_work(repo)


@needs_git
def test_detects_untracked_files(tmp_path):
    repo = _init_repo(tmp_path / "untracked")
    (repo / "new.txt").write_text("brand new")
    assert "1 untracked file" in git_tool.unsaved_work(repo)


@needs_git
def test_detects_unpushed_commits(tmp_path):
    """Committed but never pushed still only exists on this machine."""
    upstream = _init_repo(tmp_path / "upstream")
    clone = tmp_path / "clone"
    subprocess.run([GIT, "clone", "-q", str(upstream), str(clone)], check=True)
    subprocess.run([GIT, "-C", str(clone), "config", "user.email", "t@t"], check=True)
    subprocess.run([GIT, "-C", str(clone), "config", "user.name", "t"], check=True)
    (clone / "tracked.txt").write_text("local work")
    subprocess.run([GIT, "-C", str(clone), "commit", "-qam", "local"], check=True)
    assert "1 unpushed commit" in git_tool.unsaved_work(clone)


@needs_git
def test_no_upstream_is_not_reported_as_unpushed(tmp_path):
    """A branch with no remote can't be judged -- guessing would cry wolf."""
    repo = _init_repo(tmp_path / "noremote")
    assert git_tool.unsaved_work(repo) is None


def test_non_repo_directory_is_ignored(tmp_path):
    plain = tmp_path / "notarepo"
    plain.mkdir()
    (plain / "file.txt").write_text("x")
    assert git_tool.unsaved_work(plain) is None


def test_missing_git_reports_nothing(tmp_path, monkeypatch):
    """No git => can't check. Must degrade quietly, never block a delete."""
    monkeypatch.setattr(git_tool, "find_git", lambda: None)
    assert git_tool.unsaved_work(tmp_path) is None
    assert git_tool.scan_for_unsaved_work(tmp_path) == []


@needs_git
def test_scan_lists_only_repos_with_work_at_risk(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root / "clean")
    dirty = _init_repo(root / "dirty")
    (dirty / "tracked.txt").write_text("edited")
    (root / "loose-file.txt").write_text("not a dir")
    found = git_tool.scan_for_unsaved_work(root)
    assert [name for name, _ in found] == ["dirty"]


def test_scan_of_missing_directory_is_empty(tmp_path):
    assert git_tool.scan_for_unsaved_work(tmp_path / "nope") == []


@needs_git
def test_remove_repo_warns_before_deleting_dirty_work(run_cli, home, monkeypatch):
    repo = _init_repo(paths.repo_dir("work"))
    (repo / "tracked.txt").write_text("unsaved edits")
    monkeypatch.setattr("seedling.commands.kill_cmd.kill_python_and_vscode",
                        lambda: [])
    code, out = run_cli("remove-repo", "work", "--preview")
    assert code == 0
    assert "would destroy" in out
    assert "1 uncommitted change" in out
    assert repo.exists()  # preview changed nothing


@needs_git
def test_purge_preview_names_repos_that_would_lose_work(run_cli, home):
    repo = _init_repo(paths.repo_dir("work"))
    (repo / "tracked.txt").write_text("unsaved edits")
    code, out = run_cli("purge", "--preview")
    assert code == 0
    assert "would destroy" in out and "work" in out


@needs_git
def test_purge_keep_repos_does_not_warn(run_cli, home):
    """--keep-repos moves them to safety, so nothing is at risk."""
    repo = _init_repo(paths.repo_dir("work"))
    (repo / "tracked.txt").write_text("unsaved edits")
    code, out = run_cli("purge", "--keep-repos", "--preview")
    assert code == 0
    assert "would destroy" not in out


@needs_git
def test_warning_still_prints_under_yes(run_cli, home, monkeypatch):
    """-y skips prompts, but the record of what was destroyed must survive."""
    repo = _init_repo(paths.repo_dir("work"))
    (repo / "tracked.txt").write_text("unsaved edits")
    monkeypatch.setattr("seedling.commands.kill_cmd.kill_python_and_vscode",
                        lambda: [])
    code, out = run_cli("remove-user", "-y")
    assert "would destroy" in out
    assert "1 uncommitted change" in out
