"""seed download-whls / download-requirements -- the offline wheel-bundle
builders. uv's `pip download` is stubbed (monkeypatched uv_tool.run), so these
run offline and fast; what's under test is the command line seedling hands to
`uvx pip download` and how it wires into the offline `package_index` setting."""

from __future__ import annotations

import pytest

from seedling import config


@pytest.fixture
def uv_calls(monkeypatch):
    """Capture the argument list of every uv_tool.run call instead of running uv."""
    from seedling import uv_tool
    calls: list[list[str]] = []
    monkeypatch.setattr(uv_tool, "run", lambda args, **kw: calls.append(list(args)))
    return calls


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    """Run with cwd in a throwaway dir so the default ./wheelhouse lands there."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _tokens(calls):
    assert len(calls) == 1, f"expected one uv call, got {calls}"
    args = calls[0]
    assert args[:6] == ["tool", "run", "--from", "pip", "pip", "download"]
    return args[6:]


def test_download_whl_passes_through_and_injects_default_dest(run_cli, uv_calls, in_tmp):
    code, out = run_cli("download-whls", "pandas")
    assert code == 0
    tokens = _tokens(uv_calls)
    assert "pandas" in tokens
    # default destination injected and created
    dest = in_tmp / "wheelhouse"
    assert ["--dest", str(dest)] == tokens[:2]
    assert dest.is_dir()
    assert str(dest) in out  # next-step guidance names the folder


def test_download_whl_respects_user_dest(run_cli, uv_calls, in_tmp, tmp_path):
    custom = tmp_path / "mybundle"
    code, out = run_cli("download-whls", "pandas", "--dest", str(custom))
    assert code == 0
    tokens = _tokens(uv_calls)
    # our default was NOT injected; the user's --dest is the only one
    assert tokens.count("--dest") == 1
    assert not (in_tmp / "wheelhouse").exists()


def test_download_whl_forwards_pip_flags(run_cli, uv_calls, in_tmp):
    code, out = run_cli("download-whls", "numpy", "--only-binary=:all:",
                        "--platform", "manylinux2014_x86_64", "--python-version", "312")
    assert code == 0
    tokens = _tokens(uv_calls)
    for flag in ("--only-binary=:all:", "--platform", "manylinux2014_x86_64",
                 "--python-version", "312", "numpy"):
        assert flag in tokens


def test_download_whl_empty_is_usage_error(run_cli, uv_calls, in_tmp):
    code, out = run_cli("download-whls")
    assert code == 1
    assert "Usage: seed download-whls" in out
    assert not uv_calls


def test_package_index_url_becomes_index_url(run_cli, uv_calls, in_tmp):
    config.set_value("package_index", "https://nexus.corp/repository/pypi/simple")
    code, out = run_cli("download-whls", "pandas")
    assert code == 0
    tokens = _tokens(uv_calls)
    i = tokens.index("--index-url")
    assert tokens[i + 1] == "https://nexus.corp/repository/pypi/simple"


def test_package_index_dir_becomes_find_links(run_cli, uv_calls, in_tmp, tmp_path):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    config.set_value("package_index", str(wheels))
    code, out = run_cli("download-whls", "pandas")
    assert code == 0
    tokens = _tokens(uv_calls)
    assert "--no-index" in tokens
    i = tokens.index("--find-links")
    assert tokens[i + 1] == str(wheels)


def test_ca_cert_becomes_cert_flag(run_cli, uv_calls, in_tmp, tmp_path):
    cert = tmp_path / "corp-ca.pem"
    cert.write_text("-----BEGIN CERTIFICATE-----\n")
    config.set_value("ca_cert", str(cert))
    code, out = run_cli("download-whls", "pandas")
    assert code == 0
    tokens = _tokens(uv_calls)
    i = tokens.index("--cert")
    assert tokens[i + 1] == str(cert)


def test_download_requirements_uses_dash_r(run_cli, uv_calls, in_tmp, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("pandas==2.2.0\nrequests\n")
    code, out = run_cli("download-requirements", str(req))
    assert code == 0
    tokens = _tokens(uv_calls)
    i = tokens.index("-r")
    assert tokens[i + 1] == str(req)


def test_download_requirements_missing_file_errors(run_cli, uv_calls, in_tmp):
    code, out = run_cli("download-requirements", "nope.txt")
    assert code == 1
    assert "requirements file not found" in out
    assert not uv_calls


def test_download_requirements_empty_is_usage_error(run_cli, uv_calls, in_tmp):
    code, out = run_cli("download-requirements")
    assert code == 1
    assert "Usage: seed download-requirements" in out
    assert not uv_calls


# --- upload-whls: the other direction, into an internal index ---------------

@pytest.fixture
def twine_calls(monkeypatch):
    """Capture args AND kwargs -- the env is where the token has to travel,
    so a test that only saw argv couldn't tell the two apart."""
    import subprocess
    from seedling import uv_tool
    seen: list[tuple[list[str], dict]] = []

    def _run(args, **kw):
        seen.append((list(args), kw))
        return subprocess.CompletedProcess(list(args), 0)

    monkeypatch.setattr(uv_tool, "run", _run)
    return seen


def _wheelhouse(tmp_path, *names):
    d = tmp_path / "wheelhouse"
    d.mkdir(exist_ok=True)
    for n in names or ("pandas-2.1.4-py3-none-any.whl",):
        (d / n).write_text("", encoding="utf-8")
    return d


def test_upload_publishes_every_distribution_via_uvx_twine(
        run_cli, home, tmp_path, twine_calls):
    d = _wheelhouse(tmp_path, "pandas-2.1.4-py3-none-any.whl",
                    "numpy-1.26.4-cp312-win_amd64.whl", "legacy-1.0.tar.gz",
                    "notes.txt")
    config.set_value("package_upload_url", "https://pypi.corp/api/pypi/local/")
    code, out = run_cli("upload-whls", str(d))
    assert code == 0
    args, _ = twine_calls[0]
    assert args[:6] == ["tool", "run", "--from", "twine", "twine", "upload"]
    assert "--repository-url" in args
    assert sum(a.endswith(".whl") for a in args) == 2
    assert any(a.endswith("legacy-1.0.tar.gz") for a in args), "sdists count"
    assert not any(a.endswith("notes.txt") for a in args), "only distributions"


def test_the_token_travels_in_the_environment_not_argv(
        run_cli, home, tmp_path, twine_calls):
    """A command line is visible to `ps`, lands in shell history, and is
    echoed into seedling's own command log."""
    d = _wheelhouse(tmp_path)
    config.set_value("package_upload_url", "https://pypi.corp/api/pypi/local/")
    config.set_value("package_upload_token", "s3cret-token")
    code, out = run_cli("upload-whls", str(d))
    assert code == 0
    args, kwargs = twine_calls[0]
    assert "s3cret-token" not in " ".join(args)
    assert kwargs["env"]["TWINE_PASSWORD"] == "s3cret-token"
    assert kwargs["env"]["TWINE_USERNAME"] == "__token__"
    assert "s3cret-token" not in out, "and never printed"


def test_no_url_configured_explains_rather_than_guessing(
        run_cli, home, tmp_path, twine_calls):
    """package_index is deliberately NOT reused: the read and write endpoints
    differ on every server that has both."""
    d = _wheelhouse(tmp_path)
    config.set_value("package_index", "https://pypi.corp/api/pypi/pypi/simple")
    code, out = run_cli("upload-whls", str(d))
    assert code == 1
    assert "package_upload_url" in out
    assert not twine_calls


def test_the_flag_overrides_the_setting(run_cli, home, tmp_path, twine_calls):
    d = _wheelhouse(tmp_path)
    config.set_value("package_upload_url", "https://configured/")
    code, out = run_cli("upload-whls", str(d),
                        "--repository-url", "https://one-off/")
    assert code == 0
    args, _ = twine_calls[0]
    assert args[args.index("--repository-url") + 1] == "https://one-off/"


def test_an_empty_or_missing_directory_is_refused(
        run_cli, home, tmp_path, twine_calls):
    empty = tmp_path / "empty"
    empty.mkdir()
    config.set_value("package_upload_url", "https://pypi.corp/api/pypi/local/")
    code, out = run_cli("upload-whls", str(empty))
    assert code == 1 and "Nothing to upload" in out
    code, out = run_cli("upload-whls", str(tmp_path / "ghost"))
    assert code == 1 and "not a directory" in out
    assert not twine_calls


def test_upload_with_no_directory_is_a_usage_error(run_cli, home, twine_calls):
    code, out = run_cli("upload-whls")
    assert code == 1 and "Usage: seed upload-whls" in out
    assert not twine_calls
