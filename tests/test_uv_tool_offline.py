"""uv_tool env construction and the OFFLINE package/interpreter sources --
including real-uv end-to-end proof that a wheels directory fully replaces
pypi.org (installs succeed from the folder, everything else fails fast
with no network attempt)."""

from __future__ import annotations

import os
import subprocess
import time

import pytest

from conftest import UV, needs_uv
from seedling import config, paths, uv_tool


def test_build_env_sets_cache_dir(home):
    env = uv_tool._build_env(None)
    assert env["UV_CACHE_DIR"] == str(paths.UV_CACHE_DIR)


def test_build_env_caller_env_and_user_env_win(home, monkeypatch):
    monkeypatch.setenv("UV_CACHE_DIR", "user-cache")
    env = uv_tool._build_env({"EXTRA": "1"})
    assert env["UV_CACHE_DIR"] == "user-cache"
    assert env["EXTRA"] == "1"


@pytest.mark.parametrize("value,expected", [
    ("https://mirror.internal/pbs", "https://mirror.internal/pbs"),
    (r"S:\tools\python-builds", "file:///S:/tools/python-builds"),
    ("/mnt/tools/pbs", "file:///mnt/tools/pbs"),
])
def test_mirror_url_conversion(value, expected):
    assert uv_tool._as_mirror_url(value) == expected


def test_python_mirror_setting_becomes_env(home):
    config.set_value("python_mirror", r"S:\tools\python-builds")
    env = uv_tool._build_env(None)
    assert env["UV_PYTHON_INSTALL_MIRROR"] == "file:///S:/tools/python-builds"


def test_url_index_becomes_default_index(home):
    config.set_value("package_index", "https://pypi.internal/simple")
    env = uv_tool._build_env(None)
    assert env["UV_DEFAULT_INDEX"] == "https://pypi.internal/simple"
    assert "UV_CONFIG_FILE" not in env


def test_directory_index_generates_uv_toml(home):
    config.set_value("package_index", r"S:\tools\wheels")
    env = uv_tool._build_env(None)
    cfg = env["UV_CONFIG_FILE"]
    content = open(cfg, encoding="utf-8").read()
    assert 'url = "file:///S:/tools/wheels"' in content
    assert 'format = "flat"' in content
    assert "default = true" in content
    # legacy env-var mechanism must NOT be used (ignored by some uv versions)
    assert "UV_FIND_LINKS" not in env and "UV_NO_INDEX" not in env


def test_uv_toml_refreshes_when_setting_changes(home):
    config.set_value("package_index", r"S:\old")
    uv_tool._build_env(None)  # writes the initial uv.toml with the old value
    config.set_value("package_index", r"S:\new")
    assert 'file:///S:/new' in open(uv_tool._build_env(None)["UV_CONFIG_FILE"], encoding="utf-8").read()


def test_tag_line_prefixes_content_lines():
    assert "[uv]" in uv_tool.tag_line("Resolved 1 package")
    assert uv_tool.tag_line("\n") == "\n"


@needs_uv
class TestOfflineWheelDirectory:
    """The core closed-network guarantee, proven against the real uv."""

    @pytest.fixture
    def wheel_dir(self, home, tmp_path):
        # Hand-craft a minimal wheel (a wheel is just a zip + dist-info):
        # no build backend, no network -- the test itself is offline.
        import base64
        import hashlib
        import zipfile

        wheels = tmp_path / "wheels"
        wheels.mkdir()
        files = {
            "offlinepkg/__init__.py": b"VALUE = 42\n",
            "offlinepkg-1.0.dist-info/METADATA":
                b"Metadata-Version: 2.1\nName: offlinepkg\nVersion: 1.0\n",
            "offlinepkg-1.0.dist-info/WHEEL":
                b"Wheel-Version: 1.0\nGenerator: seedling-tests\n"
                b"Root-Is-Purelib: true\nTag: py3-none-any\n",
        }
        record_lines = []
        for name, data in files.items():
            digest = base64.urlsafe_b64encode(
                hashlib.sha256(data).digest()).rstrip(b"=").decode()
            record_lines.append(f"{name},sha256={digest},{len(data)}")
        record_lines.append("offlinepkg-1.0.dist-info/RECORD,,")
        with zipfile.ZipFile(wheels / "offlinepkg-1.0-py3-none-any.whl", "w") as z:
            for name, data in files.items():
                z.writestr(name, data)
            z.writestr("offlinepkg-1.0.dist-info/RECORD",
                       "\n".join(record_lines) + "\n")

        venv = tmp_path / "venv"
        subprocess.run([UV, "venv", str(venv)], check=True, capture_output=True)
        pyexe = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        return wheels, pyexe

    def test_present_package_installs_from_directory(self, home, wheel_dir):
        wheels, pyexe = wheel_dir
        config.set_value("package_index", str(wheels))
        result = uv_tool.run_captured(
            ["pip", "install", "--python", str(pyexe), "offlinepkg"], check=False)
        assert result.returncode == 0, result.stderr
        assert "offlinepkg" in result.stderr + result.stdout

    def test_absent_package_fails_fast_without_network(self, home, wheel_dir):
        wheels, pyexe = wheel_dir
        config.set_value("package_index", str(wheels))
        start = time.time()
        result = uv_tool.run_captured(
            ["pip", "install", "--python", str(pyexe), "requests"], check=False)
        elapsed = time.time() - start
        assert result.returncode != 0
        assert "unsatisfiable" in result.stderr or "not found" in result.stderr
        assert elapsed < 10, f"took {elapsed:.1f}s -- smells like network timeouts"
