"""The machine-readable surface: every read command's `--json` must put a
parseable document on stdout and nothing else, and must agree with
`seed summary --json` about what a venv or a base Python looks like."""

from __future__ import annotations

import json

from conftest import make_base_python, make_venv_dirs

from seedling import config, paths
from seedling.commands import list_cmd, status_cmd, summary_cmd


def _json_stdout(capsys, argv):
    """Run a command and parse stdout, which must be pure JSON."""
    from seedling import cli
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def test_venv_list_json(home, capsys):
    make_venv_dirs(home, "dev", "web")
    code, doc, _ = _json_stdout(capsys, ["venv-list", "--json"])
    assert code == 0
    assert doc["schema"] == list_cmd.SCHEMA_VERSION
    assert [v["name"] for v in doc["venvs"]] == ["dev", "web"]
    assert doc["venvs"][0]["python_executable"] == str(paths.venv_python("dev"))


def test_python_list_json(home, capsys):
    make_base_python(home, "312", "cpython-3.12.0")
    code, doc, _ = _json_stdout(capsys, ["python-list", "--json"])
    assert code == 0
    assert [p["tag"] for p in doc["pythons"]] == ["312"]
    assert doc["pythons"][0]["present"] is True


def test_json_venv_shape_matches_summary(home, capsys):
    """One definition of "a venv, as data". If these two ever disagree,
    something is building the payload twice."""
    make_venv_dirs(home, "dev")
    _, listed, _ = _json_stdout(capsys, ["venv-list", "--json"])
    _, summarized, _ = _json_stdout(capsys, ["summary", "--json"])
    assert listed["venvs"] == summarized["venvs"]


def test_json_python_shape_matches_summary(home, capsys):
    make_base_python(home, "312", "cpython-3.12.0")
    _, listed, _ = _json_stdout(capsys, ["python-list", "--json"])
    _, summarized, _ = _json_stdout(capsys, ["summary", "--json"])
    assert listed["pythons"] == summarized["pythons"]


def test_empty_install_still_emits_valid_json(home, capsys):
    """No venvs is a normal state, not a reason to print prose where a
    document belongs."""
    code, doc, _ = _json_stdout(capsys, ["venv-list", "--json"])
    assert code == 0
    assert doc["venvs"] == []


def test_health_check_json(home, capsys):
    code, doc, _ = _json_stdout(capsys, ["health-check", "--json"])
    assert code == 0
    assert doc["healthy"] is True
    assert doc["failures"] == 0
    assert {c["status"] for c in doc["checks"]} <= {"OK", "WARN", "FAIL"}
    assert all({"status", "area", "detail"} == set(c) for c in doc["checks"])


def test_health_check_json_keeps_the_exit_code(home, capsys):
    """--json changes the rendering, never the verdict."""
    config.set_value("default_venv", "ghost")
    code, doc, _ = _json_stdout(capsys, ["health-check", "--json"])
    assert code == 1
    assert doc["healthy"] is False
    assert doc["failures"] >= 1


def test_health_check_json_and_text_agree(home, run_cli):
    """The renderers are two views of one collect() -- a check may not
    appear in one and be missing from the other."""
    data = status_cmd.collect()
    code, out = run_cli("health-check")
    assert code == (0 if data["healthy"] else 1)
    for check in data["checks"]:
        assert check["area"] in out


def test_package_list_translates_json_to_uv_format(home, monkeypatch):
    """seedling spells it --json everywhere; uv spells it --format json.
    Callers shouldn't have to know which layer they're talking to."""
    seen = {}
    monkeypatch.setattr(list_cmd.uv_tool, "run",
                        lambda argv, **kw: seen.setdefault("argv", argv))
    from seedling import cli
    cli.main(["package-list", "--json"])
    assert seen["argv"] == ["pip", "list", "--format", "json"]


def test_package_list_leaves_an_explicit_format_alone(home, monkeypatch):
    seen = {}
    monkeypatch.setattr(list_cmd.uv_tool, "run",
                        lambda argv, **kw: seen.setdefault("argv", argv))
    from seedling import cli
    cli.main(["package-list", "--json", "--format", "freeze"])
    assert seen["argv"] == ["pip", "list", "--format", "freeze"]


def test_package_list_note_goes_to_stderr_under_json(home, monkeypatch, capsys):
    """The "no venv looks active" note is right for a person and fatal for a
    parser, so under --json it moves off stdout."""
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(list_cmd.uv_tool, "run", lambda argv, **kw: None)
    from seedling import cli
    cli.main(["package-list", "--json"])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no venv looks active" in captured.err


def test_package_list_note_stays_on_stdout_for_humans(home, monkeypatch, capsys):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(list_cmd.uv_tool, "run", lambda argv, **kw: None)
    from seedling import cli
    cli.main(["package-list"])
    assert "no venv looks active" in capsys.readouterr().out


def test_summary_collectors_are_the_shared_source(home):
    """Guards the reuse directly: if someone re-inlines a venv payload in
    list_cmd, this is what notices."""
    make_venv_dirs(home, "dev")
    assert summary_cmd.collect_venvs() == summary_cmd.collect()["venvs"]
    assert summary_cmd.collect_pythons() == summary_cmd.collect()["pythons"]
