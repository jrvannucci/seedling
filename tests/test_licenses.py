"""Licence scanning: resolving a licence from wheel/venv/channel metadata,
sorting packages into families, and the three commands that report it.

The point of the feature is that an admin copying a bundle onto a share can
see which packages carry an obligation -- so the cases that matter are the
ones where the answer is NOT permissive, and where nobody declared one."""

from __future__ import annotations

import json
import zipfile

import pytest

from seedling import licenses


def _wheel(directory, name, version, headers, licence_file=True):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{name}-{version}.dist-info/METADATA",
                   f"Metadata-Version: 2.4\nName: {name}\n"
                   f"Version: {version}\n{headers}\n\nlong description\n")
        if licence_file:
            z.writestr(f"{name}-{version}.dist-info/licenses/LICENSE", "text")
    return path


# --- resolving one package -------------------------------------------------

@pytest.mark.parametrize("headers,expected_licence,expected_source", [
    ("License-Expression: MIT", "MIT", "License-Expression"),
    ("Classifier: License :: OSI Approved :: BSD License",
     "BSD License", "classifier"),
    ("License: Apache 2.0", "Apache 2.0", "License field"),
    ("Summary: nothing at all", None, "none"),
])
def test_the_licence_is_resolved_from_the_best_source_available(
        tmp_path, headers, expected_licence, expected_source):
    _wheel(tmp_path, "pkg", "1.0", headers)
    (pkg,) = licenses.scan_wheelhouse(tmp_path)
    assert pkg.licence == expected_licence
    assert pkg.source == expected_source


def test_a_declared_expression_beats_a_classifier(tmp_path):
    """PEP 639 is SPDX and unambiguous; the classifier is a coarser claim.
    When a package carries both, the precise one wins."""
    _wheel(tmp_path, "pkg", "1.0",
           "License-Expression: BSD-3-Clause\n"
           "Classifier: License :: OSI Approved :: MIT License")
    (pkg,) = licenses.scan_wheelhouse(tmp_path)
    assert (pkg.licence, pkg.source) == ("BSD-3-Clause", "License-Expression")


def test_a_licence_pasted_in_full_reports_that_it_was(tmp_path):
    """Some projects put the whole licence in the License field. The first
    line still identifies it, but the source says not to trust it as a
    token."""
    body = "MIT License\n" + ("Permission is hereby granted, " * 20)
    _wheel(tmp_path, "pkg", "1.0", "License: " + body.replace("\n", "\n        "))
    (pkg,) = licenses.scan_wheelhouse(tmp_path)
    assert pkg.family == "permissive"
    assert "full text" in pkg.source


# --- families --------------------------------------------------------------

@pytest.mark.parametrize("text,family", [
    ("MIT", "permissive"),
    ("BSD-3-Clause", "permissive"),
    ("Apache-2.0", "permissive"),
    ("GPL-3.0-only", "copyleft"),
    ("GNU General Public License v2 (GPLv2)", "copyleft"),
    ("LGPL-3.0-or-later", "copyleft-weak"),
    ("Mozilla Public License 2.0 (MPL 2.0)", "copyleft-weak"),
    ("AGPL-3.0", "copyleft-network"),
    ("Other/Proprietary License", "proprietary"),
    ("Public Domain", "public-domain"),
    ("", "unknown"),
    (None, "unknown"),
    ("Some Bespoke Corporate Terms v4", "unclassified"),
])
def test_family_classification(text, family):
    assert licenses.family_of(text) == family


def test_lgpl_and_agpl_are_not_swallowed_by_the_gpl_pattern():
    """The whole reason FAMILIES is ordered: both contain "GPL", and calling
    an LGPL package strong copyleft would overstate the obligation."""
    assert licenses.family_of("LGPL-3.0-or-later") == "copyleft-weak"
    assert licenses.family_of("AGPL-3.0-or-later") == "copyleft-network"
    assert licenses.family_of("GPL-3.0-only") == "copyleft"


def test_severity_order_is_not_the_matching_order():
    """Matching has to test LGPL before GPL; a report ordered that way would
    rank weak copyleft above GPL, which is backwards."""
    severity = licenses.SEVERITY
    assert severity.index("copyleft") < severity.index("copyleft-weak")
    assert severity.index("proprietary") < severity.index("copyleft")
    assert severity.index("unknown") < severity.index("permissive")


# --- scanning a set --------------------------------------------------------

def _mixed_wheelhouse(tmp_path):
    d = tmp_path / "wheels"
    _wheel(d, "pandas", "2.2.1", "License-Expression: BSD-3-Clause")
    _wheel(d, "PyQt6", "6.7.1", "License-Expression: GPL-3.0-only")
    _wheel(d, "certifi", "2024.7.4",
           "Classifier: License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)")
    _wheel(d, "mystery", "0.1", "Summary: none declared", licence_file=False)
    return d


def test_summary_counts_and_orders_by_severity(tmp_path):
    found = licenses.scan_wheelhouse(_mixed_wheelhouse(tmp_path))
    assert len(found) == 4
    assert list(licenses.summarize(found)) == [
        "copyleft", "copyleft-weak", "unknown", "permissive"]


def test_attention_is_everything_that_isnt_routine(tmp_path):
    found = licenses.scan_wheelhouse(_mixed_wheelhouse(tmp_path))
    names = [p.name for p in licenses.needs_attention(found)]
    assert names == ["PyQt6", "certifi", "mystery"], \
        "permissive packages are not a review; the other three are"


def test_licence_files_are_recorded_for_the_evidence_case(tmp_path):
    found = {p.name: p for p in licenses.scan_wheelhouse(_mixed_wheelhouse(tmp_path))}
    assert found["PyQt6"].files == ["PyQt6-6.7.1.dist-info/licenses/LICENSE"]
    assert found["mystery"].files == []


def test_an_unreadable_wheel_is_reported_not_skipped(tmp_path):
    """Silently dropping it would understate the set -- the one thing a
    licence report must not do."""
    d = tmp_path / "wheels"
    d.mkdir()
    (d / "broken-1.0-py3-none-any.whl").write_text("not a zip")
    (pkg,) = licenses.scan_wheelhouse(d)
    assert pkg.family == "unknown" and "unreadable" in pkg.source


def test_scan_venv_reads_installed_distributions(tmp_path):
    site = tmp_path / "site-packages"
    info = site / "pkg-1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        "Name: pkg\nVersion: 1.0\nLicense-Expression: GPL-2.0-only\n",
        encoding="utf-8")
    (info / "LICENSE").write_text("text", encoding="utf-8")
    (pkg,) = licenses.scan_venv(site)
    assert (pkg.name, pkg.family) == ("pkg", "copyleft")
    assert pkg.files == ["pkg-1.0.dist-info/LICENSE"]


def test_scan_conda_channel_reads_repodata(tmp_path):
    """The archives are zstd-compressed, which the stdlib can't open -- the
    licence is in the index anyway."""
    sub = tmp_path / "win-64"
    sub.mkdir(parents=True)
    (sub / "repodata.json").write_text(json.dumps({
        "packages": {"ripgrep-14.1-0.tar.bz2":
                     {"name": "ripgrep", "version": "14.1", "license": "MIT"}},
        "packages.conda": {"pandoc-3.2-0.conda":
                           {"name": "pandoc", "version": "3.2", "license": "GPL-2.0-or-later"}},
    }), encoding="utf-8")
    found = {p.name: p for p in licenses.scan_conda_channel(tmp_path)}
    assert found["ripgrep"].family == "permissive"
    assert found["pandoc"].family == "copyleft"


# --- the commands ----------------------------------------------------------

class TestCommands:
    def test_whl_licenses_reports_the_exceptions(self, run_cli, home, tmp_path):
        d = _mixed_wheelhouse(tmp_path)
        code, out = run_cli("whl-licenses", str(d))
        assert code == 0
        assert "Needs a decision (3)" in out
        assert "PyQt6" in out and "GPL-3.0-only" in out
        assert "pandas" not in out, "permissive packages stay out of the way"

    def test_all_lists_everything(self, run_cli, home, tmp_path):
        code, out = run_cli("whl-licenses", str(_mixed_wheelhouse(tmp_path)), "--all")
        assert code == 0 and "pandas" in out

    def test_json_is_machine_readable_and_complete(self, run_cli, home, tmp_path):
        code, out = run_cli("whl-licenses", str(_mixed_wheelhouse(tmp_path)), "--json")
        assert code == 0
        doc = json.loads(out)
        assert doc["total"] == 4 and doc["summary"]["copyleft"] == 1
        assert {p["name"] for p in doc["packages"]} == {
            "pandas", "PyQt6", "certifi", "mystery"}

    def test_fail_on_turns_a_policy_into_an_exit_code(self, run_cli, home, tmp_path):
        d = _mixed_wheelhouse(tmp_path)
        code, out = run_cli("whl-licenses", str(d), "--fail-on", "copyleft,unknown")
        assert code == 1
        assert "PyQt6" in out and "mystery" in out
        code, _ = run_cli("whl-licenses", str(d), "--fail-on", "proprietary")
        assert code == 0, "a family nothing is in must not fail the run"

    def test_a_bundle_root_resolves_to_its_wheels(self, run_cli, home, tmp_path):
        """Pointing it at the bundle is the obvious thing to try."""
        _mixed_wheelhouse(tmp_path)
        code, out = run_cli("whl-licenses", str(tmp_path))
        assert code == 0 and "PyQt6" in out

    def test_an_empty_directory_says_so(self, run_cli, home, tmp_path):
        (tmp_path / "empty").mkdir()
        code, out = run_cli("whl-licenses", str(tmp_path / "empty"))
        assert code == 1 and "No .whl files" in out

    def test_venv_licenses_needs_a_venv(self, run_cli, home, monkeypatch):
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        code, out = run_cli("venv-licenses")
        assert code == 1 and "No venv is active" in out

    def test_venv_licenses_scans_the_active_venv(self, run_cli, home, monkeypatch,
                                                 tmp_path):
        venv = tmp_path / "dev"
        info = venv / "Lib" / "site-packages" / "pkg-1.0.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text(
            "Name: pkg\nVersion: 1.0\nLicense-Expression: AGPL-3.0\n",
            encoding="utf-8")
        monkeypatch.setenv("VIRTUAL_ENV", str(venv))
        code, out = run_cli("venv-licenses")
        assert code == 0
        assert "copyleft-network" in out and "pkg" in out

    def test_forge_licenses_reads_a_channel(self, run_cli, home, tmp_path):
        sub = tmp_path / "noarch"
        sub.mkdir(parents=True)
        (sub / "repodata.json").write_text(json.dumps({
            "packages": {"pandoc-3.2-0.tar.bz2": {
                "name": "pandoc", "version": "3.2",
                "license": "GPL-2.0-or-later"}}}), encoding="utf-8")
        code, out = run_cli("forge-licenses", str(tmp_path))
        assert code == 0 and "pandoc" in out and "copyleft" in out


# --- the documented examples ----------------------------------------------

def test_every_documented_json_block_parses():
    """The manifest excerpts in the offline examples are presented as real
    output. A block that isn't valid JSON is a block nobody can check against
    their own bundle -- and the first draft of one of these was a comma-
    separated fragment that looked fine and parsed as nothing."""
    import json
    import re
    from conftest import REPO_ROOT

    checked = 0
    for page in (REPO_ROOT / "docs").rglob("*.md"):
        if "_build" in str(page):
            continue
        for block in re.findall(r"```json\n(.*?)```",
                                page.read_text(encoding="utf-8"), re.S):
            try:
                json.loads(block)
            except json.JSONDecodeError as e:
                raise AssertionError(f"{page.name}: {e}") from e
            checked += 1
    assert checked >= 4, "the offline examples lost their manifest excerpts?"


def test_the_documented_families_are_the_real_ones():
    """The docs name the families in severity order. If a family is renamed
    in code and not in prose, an admin greps for a category that never
    appears in output."""
    from conftest import REPO_ROOT
    text = (REPO_ROOT / "docs" / "LICENSING.md").read_text(encoding="utf-8")
    for family in licenses.SEVERITY:
        if family == "unclassified":
            continue          # an internal fallback, not something to promise
        assert f"`{family}`" in text, f"{family} is not documented"
