"""Deployment profiles: parsing/validation (seedling/profile.py) and the
idempotent applier (`seed apply`).

Validation is where most of the value is -- a profile is distributed to a
whole fleet, so a typo has to fail loudly for the admin rather than quietly
for each user.
"""

from __future__ import annotations

import pytest

from seedling import config, paths, profile as profile_mod
from seedling.commands import apply_cmd


def _write(tmp_path, text: str):
    p = tmp_path / "seedling-profile.toml"
    p.write_text(text, encoding="utf-8")
    return p


# --- parsing ---------------------------------------------------------------

def test_minimal_profile():
    prof = profile_mod.parse("")
    assert prof.pythons == [] and prof.venvs == [] and prof.repos == []


def test_full_profile_round_trips():
    prof = profile_mod.parse('''
        python = ["3.12", "3.13"]
        tools = ["ripgrep", "pandoc=3.2"]

        [[venv]]
        name = "dev"
        python = "312"
        packages = ["ipython", "ruff"]
        default = true

        [[venv]]
        name = "analysis"
        packages = ["pandas"]
        default_packages = false

        [[repo]]
        url = "https://git.corp/team/toolkit.git"
        install = true

        [config]
        vscode_flavor = "vscodium"
    ''')
    assert prof.pythons == ["3.12", "3.13"]
    assert [v.name for v in prof.venvs] == ["dev", "analysis"]
    dev, analysis = prof.venvs
    assert dev.python == "312" and dev.default is True
    assert analysis.default_packages is False
    assert prof.repos[0].install is True
    assert prof.tools == ["ripgrep", "pandoc=3.2"]
    assert prof.tool_set() == ["ripgrep", "pandoc=3.2"]
    assert prof.settings["vscode_flavor"] == "vscodium"


def test_whitespace_is_stripped():
    prof = profile_mod.parse('[[venv]]\nname = "  dev  "\npython = " 312 "')
    assert prof.venvs[0].name == "dev"
    assert prof.venvs[0].python == "312"


@pytest.mark.parametrize("text,fragment", [
    ("schema = 99", "understands up to 1"),
    ("python = 'notalist'", "python must be a list"),
    ("python = [3]", "non-empty strings"),
    ('[[venv]]\nname = ""', "non-empty name"),
    ('[[venv]]\nname = "a"\npackages = "x"', "packages must be a list"),
    ('[[venv]]\nname = "a"\ndefault = "yes"', "must be true or false"),
    ('[[venv]]\nname = "a"\ndefault_packages = 1', "must be true or false"),
    ('[[venv]]\nname="a"\n[[venv]]\nname="a"', "duplicate venv name"),
    ('[[venv]]\nname="a"\ndefault=true\n[[venv]]\nname="b"\ndefault=true',
     "only one venv may be default"),
    ('[[repo]]\ninstall = true', "needs a non-empty url"),
    ('[[repo]]\nurl = "x"\ninstall = "yes"', "must be true or false"),
    ("[config]\nupdate_source = 'x'", "cannot be set from a profile"),
    ("[config]\nnative_tls = true", "cannot be set from a profile"),
    ('[config]\ndefault_venv = "ghost"', "names no venv"),
    ("this is not toml {{{", "not valid TOML"),
])
def test_invalid_profiles_are_rejected(text, fragment):
    with pytest.raises(profile_mod.ProfileError) as e:
        profile_mod.parse(text)
    assert fragment in str(e.value)


def test_install_time_settings_are_not_settable_from_a_profile():
    """seedling.conf owns anything that must be right BEFORE seed-cli runs.
    Allowing a profile to rewrite it would create two sources of truth."""
    for key in ("update_source", "package_index", "python_mirror",
                "native_tls", "ca_cert", "shared_root", "profile"):
        with pytest.raises(profile_mod.ProfileError):
            profile_mod.parse(f"[config]\n{key} = 'x'")


def test_a_declared_default_venv_must_exist_but_may_be_declared_either_way():
    # via [config]
    prof = profile_mod.parse('[[venv]]\nname="dev"\n[config]\ndefault_venv="dev"')
    assert prof.settings["default_venv"] == "dev"
    # or via the venv's own flag
    prof = profile_mod.parse('[[venv]]\nname="dev"\ndefault=true')
    assert prof.venvs[0].default is True


# --- package_set (what the offline bundler needs) --------------------------

def test_package_set_unions_every_venv_and_the_inherited_defaults(home):
    prof = profile_mod.parse('''
        [[venv]]
        name = "a"
        packages = ["pandas"]
        [[venv]]
        name = "b"
        packages = ["pandas", "numpy"]
    ''')
    packages = prof.package_set()
    assert "pandas" in packages and "numpy" in packages
    # venv_default_packages land in every venv, so a bundle needs them too.
    assert "ruff" in packages and "ipython" in packages
    assert packages == sorted(set(packages)), "must be sorted and de-duplicated"


def test_package_set_honors_an_overridden_default_list(home):
    prof = profile_mod.parse('''
        [[venv]]
        name = "a"
        packages = ["pandas"]
        [config]
        venv_default_packages = ["black"]
    ''')
    packages = prof.package_set()
    assert "black" in packages and "pandas" in packages
    assert "ruff" not in packages, "the profile replaced the default list"


def test_package_set_skips_defaults_when_no_venv_takes_them(home):
    prof = profile_mod.parse('''
        [[venv]]
        name = "a"
        packages = ["pandas"]
        default_packages = false
    ''')
    assert prof.package_set() == ["pandas"]


# --- resolution ------------------------------------------------------------

def test_find_prefers_explicit_then_config_then_cwd(home, tmp_path, monkeypatch):
    explicit = _write(tmp_path, "")
    assert profile_mod.find(str(explicit)) == explicit

    recorded = tmp_path / "recorded.toml"
    recorded.write_text("", encoding="utf-8")
    config.set_value("profile", str(recorded))
    assert profile_mod.find(None) == recorded

    config.set_value("profile", None)
    monkeypatch.chdir(tmp_path)
    assert profile_mod.find(None) == tmp_path / "seedling-profile.toml"


def test_find_returns_none_when_there_is_nothing(home, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "seedling-profile.toml").unlink(missing_ok=True)
    assert profile_mod.find(None) is None


def test_a_recorded_profile_that_no_longer_exists_is_ignored(home, tmp_path, monkeypatch):
    """A share that moved shouldn't make every `seed apply` fail with a
    traceback -- it falls through to the local lookup."""
    config.set_value("profile", str(tmp_path / "gone.toml"))
    monkeypatch.chdir(tmp_path)
    assert profile_mod.find(None) is None


# --- apply -----------------------------------------------------------------

def test_apply_reports_a_missing_profile(run_cli, home, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out = run_cli("apply")
    assert code == 1
    assert "No profile to apply" in out


def test_invalid_profile_exits_2_not_1(run_cli, home, tmp_path):
    """Distinct exit codes: 2 = the profile is wrong (admin fixes the file),
    1 = a step failed at runtime (retry may help)."""
    bad = _write(tmp_path, "[[venv]]\nname = ''")
    code, out = run_cli("apply", str(bad))
    assert code == 2
    assert "non-empty name" in out


def test_preview_changes_nothing(run_cli, home, tmp_path):
    prof = _write(tmp_path, '[[venv]]\nname = "dev"\n[config]\nvscode_flavor = "vscodium"')
    code, out = run_cli("apply", str(prof), "--preview")
    assert code == 0
    assert "create venv 'dev'" in out
    assert not paths.venv_dir("dev").exists()
    assert config.get("vscode_flavor") == "microsoft", "settings must be untouched"


def test_apply_writes_settings_and_is_then_idempotent(run_cli, home, tmp_path):
    prof = _write(tmp_path, '[config]\nvscode_flavor = "vscodium"')
    code, out = run_cli("apply", str(prof))
    assert code == 0
    assert config.get("vscode_flavor") == "vscodium"

    code, out = run_cli("apply", str(prof))
    assert code == 0
    assert "Already up to date" in out


def test_apply_installs_profile_tools(run_cli, home, tmp_path, monkeypatch):
    """A profile's [tools] are installed by apply (from conda_channel, which on
    an offline bundle points at the bundled channel)."""
    from seedling.commands import apply_cmd
    installed = []
    monkeypatch.setattr(apply_cmd.tool_cmd, "install",
                        lambda args: (installed.append(args.spec), 0)[1])
    prof = _write(tmp_path, 'tools = ["ripgrep", "pandoc=3.2"]')

    code, out = run_cli("apply", str(prof), "--preview")
    assert code == 0
    assert "install conda-forge tool ripgrep" in out
    assert not installed, "preview must not install anything"

    code, out = run_cli("apply", str(prof))
    assert code == 0
    assert installed == ["ripgrep", "pandoc=3.2"]


def test_apply_skips_an_already_installed_tool(run_cli, home, tmp_path, monkeypatch):
    from seedling.commands import apply_cmd
    paths.TOOL_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    paths.tool_manifest_file("ripgrep").write_text('{"commands": ["rg"]}')
    called = []
    monkeypatch.setattr(apply_cmd.tool_cmd, "install",
                        lambda args: (called.append(args.spec), 0)[1])
    prof = _write(tmp_path, 'tools = ["ripgrep"]')
    code, out = run_cli("apply", str(prof))
    assert code == 0
    assert not called, "an installed tool must not be reinstalled"


def test_existing_venv_is_never_recreated(run_cli, home, tmp_path):
    """The core safety property: apply provisions what's missing and leaves
    a user's own environment alone."""
    target = paths.venv_dir("dev")
    target.mkdir(parents=True)
    (target / "user-file.txt").write_text("do not lose me", encoding="utf-8")

    prof = _write(tmp_path, '[[venv]]\nname = "dev"\npackages = ["ruff"]')
    code, out = run_cli("apply", str(prof), "--preview")
    assert code == 0
    assert "already exists" in out
    assert "create venv" not in out
    assert (target / "user-file.txt").read_text(encoding="utf-8") == "do not lose me"


def test_force_plans_missing_packages_for_an_existing_venv(home, tmp_path, monkeypatch):
    paths.venv_dir("dev").mkdir(parents=True)
    monkeypatch.setattr(apply_cmd, "_installed_packages", lambda name: {"ruff"})
    prof = profile_mod.parse('[[venv]]\nname="dev"\npackages=["ruff","pandas"]')

    plain = apply_cmd._plan(prof, force=False)
    assert any("already exists" in d for _, d in plain)

    forced = apply_cmd._plan(prof, force=True)
    detail = [d for action, d in forced if action == "packages"]
    assert detail and "pandas" in detail[0]
    assert "ruff" not in detail[0], "already-installed packages aren't reinstalled"


def test_requirement_name_strips_specifiers():
    for spec, expected in [
        ("ruff", "ruff"), ("ruff>=0.5", "ruff"), ("Django<6", "django"),
        ("pandas[all]", "pandas"), ("numpy==1.2.3", "numpy"),
        ("x != 2", "x"), ("torch~=2.0", "torch"),
    ]:
        assert apply_cmd._requirement_name(spec) == expected


def test_plan_is_empty_for_an_already_satisfied_profile(home, tmp_path):
    paths.venv_dir("dev").mkdir(parents=True)
    config.set_value("vscode_flavor", "vscodium")
    prof = profile_mod.parse('[[venv]]\nname="dev"\n[config]\nvscode_flavor="vscodium"')
    assert all(action == "skip" for action, _ in apply_cmd._plan(prof, force=False))


class TestProfileEditor:
    """`editor = "spyder"` lets a deployment standardize on a bundled editor,
    the way `tools = [...]` already does for conda-forge programs."""

    def _write(self, tmp_path, body):
        path = tmp_path / "seedling-profile.toml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_a_bare_string_still_works(self, tmp_path):
        """The single-value form predates the list one, so profiles already
        written against it must keep parsing -- normalized to a one-element
        list rather than kept as a separate shape."""
        prof = profile_mod.load(self._write(tmp_path, 'editor = "spyder"\n'))
        assert prof.editors == ["spyder"]

    def test_editor_is_optional(self, tmp_path):
        """Profiles written before this existed must behave exactly as they
        did: no editor declared means apply installs none."""
        prof = profile_mod.load(self._write(tmp_path, 'pythons = ["3.12"]\n'))
        assert prof.editors == []

    def test_editor_is_normalized(self, tmp_path):
        prof = profile_mod.load(self._write(tmp_path, 'editor = "  SPYDER "\n'))
        assert prof.editors == ["spyder"]

    def test_unknown_editor_is_fatal(self, tmp_path):
        """A typo must stop the profile, not quietly deploy a different
        editor than the fleet was promised -- same reasoning as an unknown
        vscode_flavor."""
        with pytest.raises(profile_mod.ProfileError) as excinfo:
            profile_mod.load(self._write(tmp_path, 'editor = "sypder"\n'))
        assert "not a bundled editor" in str(excinfo.value)

    def test_valid_values_come_from_the_registry(self, tmp_path):
        """The error lists what's actually registered, so registering an
        editor makes it profile-selectable with no second list to update."""
        from seedling.commands import editors
        with pytest.raises(profile_mod.ProfileError) as excinfo:
            profile_mod.load(self._write(tmp_path, 'editor = "nope"\n'))
        for key in editors.REGISTRY:
            assert key in str(excinfo.value)

    def test_non_string_editor_is_rejected(self, tmp_path):
        with pytest.raises(profile_mod.ProfileError):
            profile_mod.load(self._write(tmp_path, 'editor = 3\n'))


class TestProfileEditorQuery:
    """`seed apply --print-editor` is how the installers learn a profile's
    editor BEFORE deciding whether to start the VS Code background job. It
    has to stay machine-readable: one bare token, or nothing at all."""

    def _profile(self, tmp_path, body):
        path = tmp_path / "p.toml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_prints_the_declared_editor_and_nothing_else(
            self, run_cli, home, tmp_path):
        path = self._profile(tmp_path, 'editor = "spyder"\n')
        code, out = run_cli("apply", str(path), "--print-editor")
        assert code == 0
        assert out.strip() == "spyder"

    def test_prints_nothing_when_the_profile_is_silent(
            self, run_cli, home, tmp_path):
        """Empty means 'the profile doesn't say', which is the installer's
        signal to let SEEDLING_AUTO_VSCODE decide as it always has."""
        path = self._profile(tmp_path, 'pythons = ["3.12"]\n')
        code, out = run_cli("apply", str(path), "--print-editor")
        assert code == 0
        assert out.strip() == ""

    def test_query_installs_nothing(self, run_cli, home, tmp_path, monkeypatch):
        """It's a question, not an action -- the installers call it before
        they've decided anything."""
        # Editor is a frozen dataclass, so patch the module-level run() that
        # each registration closes over -- the lambda resolves it at call
        # time, so this still intercepts an install attempt.
        from seedling.commands import spyder_cmd, vscode_cmd

        def boom(*a, **k):
            raise AssertionError("--print-editor must not install anything")

        monkeypatch.setattr(spyder_cmd, "run", boom)
        monkeypatch.setattr(vscode_cmd, "run", boom)
        path = self._profile(tmp_path, 'editor = "spyder"\n')
        code, _ = run_cli("apply", str(path), "--print-editor")
        assert code == 0


class TestProfileEditorList:
    """`editor` accepts a list as well as a single string. The system already
    supports several editors installed at once -- separate trees, separate
    commands -- so restricting the profile to one was an artificial limit."""

    def _write(self, tmp_path, body):
        path = tmp_path / "seedling-profile.toml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_a_list_is_accepted(self, tmp_path):
        prof = profile_mod.load(
            self._write(tmp_path, 'editor = ["vscode", "spyder"]\n'))
        assert prof.editors == ["vscode", "spyder"]

    def test_order_is_preserved(self, tmp_path):
        """Apply installs in the order given, so it must not be sorted."""
        prof = profile_mod.load(
            self._write(tmp_path, 'editor = ["spyder", "vscode"]\n'))
        assert prof.editors == ["spyder", "vscode"]

    def test_duplicates_collapse(self, tmp_path):
        prof = profile_mod.load(
            self._write(tmp_path, 'editor = ["spyder", "spyder"]\n'))
        assert prof.editors == ["spyder"]

    def test_entries_are_normalized(self, tmp_path):
        prof = profile_mod.load(
            self._write(tmp_path, 'editor = [" VSCODE ", "Spyder"]\n'))
        assert prof.editors == ["vscode", "spyder"]

    def test_one_bad_entry_fails_the_whole_profile(self, tmp_path):
        """A partly-valid list must not deploy its good half -- the fleet
        would silently get an environment nobody specified."""
        with pytest.raises(profile_mod.ProfileError) as e:
            profile_mod.load(self._write(tmp_path, 'editor = ["vscode", "nope"]\n'))
        assert "not a bundled editor" in str(e.value)

    def test_empty_list_is_rejected(self, tmp_path):
        """`editor = []` is almost certainly a mistake; omitting the key is
        how you say 'no editor'."""
        with pytest.raises(profile_mod.ProfileError):
            profile_mod.load(self._write(tmp_path, 'editor = []\n'))

    def test_non_string_entry_is_rejected(self, tmp_path):
        with pytest.raises(profile_mod.ProfileError):
            profile_mod.load(self._write(tmp_path, 'editor = ["vscode", 3]\n'))

    def test_query_prints_all_of_them(self, run_cli, home, tmp_path):
        """The installers read this to decide whether to skip the VS Code
        job, so every declared editor has to appear."""
        path = tmp_path / "p.toml"
        path.write_text('editor = ["vscode", "spyder"]\n', encoding="utf-8")
        code, out = run_cli("apply", str(path), "--print-editor")
        assert code == 0
        assert set(out.split()) == {"vscode", "spyder"}
