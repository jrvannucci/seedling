"""offline-bundle.toml: parsing/validation, the two ways an Inventory is
built (declared intent vs. what a bundle on disk actually holds), and the
profile check that both feed -- including `seed profile-check`, the
air-gapped side of the story."""

from __future__ import annotations

import json

import pytest

from seedling import bundle as bundle_mod, config, profile as profile_mod


def _bundle(tmp_path, text: str):
    p = tmp_path / "offline-bundle.toml"
    p.write_text(text, encoding="utf-8")
    return p


# --- parsing ---------------------------------------------------------------

def test_a_minimal_bundle_parses():
    b = bundle_mod.parse("")
    assert b.pythons == [] and b.packages == [] and b.vscode is True


def test_every_section_is_read():
    b = bundle_mod.parse('''
        schema = 1
        platform = "Windows/x86_64"
        deploy_root = "S:\\\\tools"
        pythons = ["3.12", "3.11"]
        packages = ["scipy", "polars"]
        tools = ["ripgrep"]

        [editor]
        flavor = "vscodium"
        extensions = ["ms-python.python"]

        [git]
        mingit = true

        [[repo]]
        url = "https://git.corp/team/plotpress.git"
        extras = ["gui"]
    ''')
    assert b.pythons == ["3.12", "3.11"]
    assert b.packages == ["scipy", "polars"]
    assert b.tools == ["ripgrep"]
    assert b.editor_flavor == "vscodium"
    assert b.mingit is True
    assert b.repos[0].name == "plotpress" and b.repos[0].extras == ["gui"]


def test_a_bare_string_is_a_one_element_list():
    assert bundle_mod.parse('tools = "ripgrep"').tools == ["ripgrep"]


def test_it_knows_nothing_about_profiles():
    """The dependency runs one way: profiles conform to the bundle, so the
    bundle has no key that names one."""
    with pytest.raises(bundle_mod.BundleError) as e:
        bundle_mod.parse('profiles = ["team.toml"]')
    assert "unknown key" in str(e.value)


@pytest.mark.parametrize("text,fragment", [
    ('nonsense = 1', "unknown key"),
    ('[editor]\nflavor = "emacs"', "flavor must be"),
    ('[editor]\nstage = "yes"', "stage must be true or false"),
    ('[git]\nmingit = "yes"', "mingit must be true or false"),
    ('[[repo]]\nurl = ""', "non-empty url"),
    ('[[repo]]\nurl = "x"\nnope = 1', "unknown key"),
    ('schema = 99', "newer than this seedling understands"),
    ('pythons = [""]', "non-empty strings"),
])
def test_invalid_declarations_are_rejected(text, fragment):
    with pytest.raises(bundle_mod.BundleError) as e:
        bundle_mod.parse(text)
    assert fragment in str(e.value)


def test_loading_from_disk_records_the_path(tmp_path):
    path = _bundle(tmp_path, 'pythons = ["3.12"]')
    assert bundle_mod.load(path).path == path


# --- inventory: declared intent --------------------------------------------

def test_the_declared_superset_stands_alone(home):
    """No profile enters the inventory. A superset assembled from the profile
    it judges could never refuse one."""
    b = bundle_mod.parse('packages = ["polars"]\ntools = ["ripgrep"]\n'
                         'pythons = ["3.12"]')
    inv = bundle_mod.Inventory.from_bundle(b)
    assert "polars" in inv.packages
    assert inv.tools == {"ripgrep"} and inv.pythons == {"3.12"}

    prof = profile_mod.parse('[[venv]]\nname = "dev"\npackages = ["pandas"]\n'
                             'default_packages = false\n')
    assert "pandas" not in inv.packages
    assert bundle_mod.check_profile(prof, inv), \
        "a package the bundle never declared must fail the check"


def test_what_every_bundle_always_carries_counts_as_declared(home):
    """seedling always downloads hatchling + the default venv packages, so a
    profile using them isn't unsatisfiable against a bundle that lists none."""
    inv = bundle_mod.Inventory.from_bundle(bundle_mod.parse(""))
    for name in bundle_mod.ALWAYS_PRESENT:
        assert name in inv.packages
    prof = profile_mod.parse('[[venv]]\nname = "dev"\n')   # default packages
    assert bundle_mod.check_profile(prof, inv) == []


# --- inventory: what a bundle really holds ---------------------------------

def _fake_bundle_dir(root, *, wheels=(), pythons=(), tools=(), vscode=False):
    (root / "wheels").mkdir(parents=True)
    for name in wheels:
        (root / "wheels" / name).write_text("", encoding="utf-8")
    if pythons:
        (root / "python-builds").mkdir()
        for v in pythons:
            (root / "python-builds" /
             f"cpython-{v}.9+20260101-x86_64-pc-windows-msvc.tar.gz"
             ).write_text("", encoding="utf-8")
    if tools:
        sub = root / "conda-channel" / "win-64"
        sub.mkdir(parents=True)
        (sub / "repodata.json").write_text(json.dumps({
            "packages": {f"{t}-1.0-0.tar.bz2": {"name": t} for t in tools},
        }), encoding="utf-8")
    if vscode:
        (root / "seedling" / "vendor" / "vscode").mkdir(parents=True)
    return root


def test_discover_reads_wheels_interpreters_tools_and_the_editor(tmp_path):
    root = _fake_bundle_dir(
        tmp_path / "bundle",
        wheels=["pandas-2.1.4-cp312-cp312-win_amd64.whl",
                "Ruff_LSP-0.0.5-py3-none-any.whl",
                "legacy-pkg-1.2.tar.gz"],
        pythons=["3.12"], tools=["ripgrep"], vscode=True)
    inv = bundle_mod.Inventory.discover(root)
    assert inv.packages["pandas"] == {"2.1.4"}
    assert "ruff-lsp" in inv.packages, "wheel names are canonicalized"
    assert inv.packages["legacy-pkg"] == {"1.2"}, "sdists count too"
    assert inv.pythons == {"3.12"} and inv.tools == {"ripgrep"}
    assert inv.vscode is True


def test_discover_on_an_empty_directory_is_empty_not_an_error(tmp_path):
    inv = bundle_mod.Inventory.discover(tmp_path)
    assert inv.packages == {} and not inv.vscode


def test_repo_extras_come_from_the_bundles_own_declaration(tmp_path):
    """Nothing on disk records which extras a wheelhouse was resolved for, so
    the bundle carries its declaration and discover() reads it back."""
    root = _fake_bundle_dir(tmp_path / "bundle")
    (root / "seedling").mkdir(exist_ok=True)
    (root / "seedling" / "offline-bundle.toml").write_text(
        '[[repo]]\nurl = "https://git.corp/team/plotpress.git"\n'
        'extras = ["gui"]\n', encoding="utf-8")
    inv = bundle_mod.Inventory.discover(root)
    assert inv.repos == {"plotpress": {"gui"}}


# --- the check ------------------------------------------------------------

class TestCheckProfile:
    def _inv(self, **kw):
        inv = bundle_mod.Inventory()
        inv.packages = {"pandas": {"2.1.4"}, "ipython": {"8.0"},
                        "ruff": {"0.5"}, "ipykernel": {"6.0"}}
        inv.pythons = {"3.12"}
        inv.tools = {"ripgrep"}
        for k, v in kw.items():
            setattr(inv, k, v)
        return inv

    def test_a_satisfied_profile_reports_nothing(self, home):
        prof = profile_mod.parse(
            'python = ["3.12"]\ntools = ["ripgrep"]\n'
            '[[venv]]\nname = "dev"\npackages = ["pandas"]\n')
        assert bundle_mod.check_profile(prof, self._inv()) == []

    def test_a_missing_package_is_named(self, home):
        prof = profile_mod.parse(
            '[[venv]]\nname = "dev"\npackages = ["polars"]\n'
            'default_packages = false\n')
        problems = bundle_mod.check_profile(prof, self._inv())
        assert len(problems) == 1 and "'polars'" in problems[0]

    def test_an_exact_pin_the_bundle_lacks_is_caught(self, home):
        """A range can be met by whatever the wheelhouse holds; `==` can't."""
        prof = profile_mod.parse(
            '[[venv]]\nname = "dev"\npackages = ["pandas==9.9.9"]\n'
            'default_packages = false\n')
        problems = bundle_mod.check_profile(prof, self._inv())
        assert "that exact version isn't in the bundle" in problems[0]

    def test_a_range_is_not_second_guessed(self, home):
        prof = profile_mod.parse(
            '[[venv]]\nname = "dev"\npackages = ["pandas>=2.0"]\n'
            'default_packages = false\n')
        assert bundle_mod.check_profile(prof, self._inv()) == []

    def test_an_unmirrored_interpreter_is_caught(self, home):
        prof = profile_mod.parse('python = ["3.9"]\n')
        problems = bundle_mod.check_profile(prof, self._inv())
        assert "Python 3.9" in problems[0]

    def test_a_missing_tool_is_caught(self, home):
        prof = profile_mod.parse('tools = ["pandoc"]\n')
        problems = bundle_mod.check_profile(prof, self._inv())
        assert "pandoc" in problems[0]

    def test_an_editor_the_bundle_doesnt_stage_is_caught(self, home):
        prof = profile_mod.parse('editor = "vscode"\n')
        problems = bundle_mod.check_profile(prof, self._inv(vscode=False))
        assert "vscode" in problems[0]

    def test_spyder_has_to_be_in_the_wheelhouse(self, home):
        """It's a PyPI application -- naming it as the editor doesn't put a
        distribution in the bundle."""
        prof = profile_mod.parse('editor = "spyder"\n')
        problems = bundle_mod.check_profile(prof, self._inv())
        assert "spyder" in problems[0]

    def test_an_undeclared_repo_is_caught(self, home):
        prof = profile_mod.parse(
            '[[venv]]\nname = "dev"\ndefault_packages = false\n'
            '[[repo]]\nurl = "https://git.corp/team/plotpress.git"\n'
            'install = ["dev"]\n')
        problems = bundle_mod.check_profile(prof, self._inv())
        assert "plotpress" in problems[0] and "dependencies" in problems[0]

    def test_an_extra_the_bundle_didnt_resolve_is_caught(self, home):
        """The per-venv extras case: the bundle resolved [gui], the profile
        asks for [gui,test], and the test extra's dependencies aren't there."""
        prof = profile_mod.parse(
            '[[venv]]\nname = "dev"\ndefault_packages = false\n'
            '[[repo]]\nurl = "https://git.corp/team/plotpress.git"\n'
            'install = ["dev[gui,test]"]\n')
        inv = self._inv(repos={"plotpress": {"gui"}})
        problems = bundle_mod.check_profile(prof, inv)
        assert len(problems) == 1 and "test" in problems[0]

    def test_every_problem_is_reported_not_just_the_first(self, home):
        prof = profile_mod.parse(
            'python = ["3.9"]\ntools = ["pandoc"]\n'
            '[[venv]]\nname = "dev"\npackages = ["polars"]\n'
            'default_packages = false\n')
        assert len(bundle_mod.check_profile(prof, self._inv())) == 3


def _doc_toml_blocks(*paths):
    """Every ```toml block in the docs, split by which schema it belongs to.

    Three schemas share the fence: bundles, profiles, and custom-command
    files. Classified by what the block actually is -- the filename its
    header comment names, else a key only one of them has -- and anything
    that matches none is skipped rather than guessed at."""
    import re
    bundles, profiles = [], []
    for path in paths:
        for block in re.findall(r"```toml\n(.*?)```", path.read_text(
                encoding="utf-8"), re.S):
            if "offline-bundle.toml" in block or re.search(r"^pythons\s*=",
                                                           block, re.M):
                bundles.append((path.name, block))
            elif "[[command]]" in block or "custom-commands.toml" in block:
                continue                      # a different schema entirely
            elif "profile.toml" in block or re.search(
                    r"^(\[\[venv\]\]|\[\[repo\]\]|python\s*=|editor\s*=)",
                    block, re.M):
                profiles.append((path.name, block))
    return bundles, profiles


def test_every_documented_bundle_example_is_valid():
    """The offline-bundle.toml blocks are presented as copy-and-ship files,
    so a stale one is worse than no example -- the same guarantee the profile
    examples already have."""
    from conftest import REPO_ROOT
    docs = REPO_ROOT / "docs"
    bundles, _ = _doc_toml_blocks(docs / "OFFLINE.md",
                                  *sorted((docs / "profile-examples").glob("*.md")))
    assert len(bundles) >= 4, "the docs lost their bundle examples?"
    for name, block in bundles:
        try:
            bundle_mod.parse(block)
        except bundle_mod.BundleError as e:
            raise AssertionError(f"{name}: {e}") from e


def test_every_profile_in_the_example_subpages_is_valid(home):
    """The examples page itself was already covered; its subpages -- where
    the whole copy-and-ship files actually live -- were not."""
    from conftest import REPO_ROOT
    _, profiles = _doc_toml_blocks(
        *sorted((REPO_ROOT / "docs" / "profile-examples").glob("*.md")))
    assert len(profiles) >= 8, "the subpages lost their profiles?"
    for name, block in profiles:
        try:
            profile_mod.parse(block)
        except profile_mod.ProfileError as e:
            raise AssertionError(f"{name}: {e}") from e


# --- seed profile-check ----------------------------------------------------

class TestProfileCheckCommand:
    def _bundle_on_disk(self, tmp_path):
        return _fake_bundle_dir(
            tmp_path / "share",
            wheels=["pandas-2.1.4-cp312-cp312-win_amd64.whl",
                    "ipython-8.0-py3-none-any.whl",
                    "ruff-0.5-py3-none-any.whl",
                    "ipykernel-6.0-py3-none-any.whl"],
            pythons=["3.12"])

    def test_a_satisfied_profile_exits_zero(self, run_cli, home, tmp_path):
        root = self._bundle_on_disk(tmp_path)
        prof = tmp_path / "profile.toml"
        prof.write_text('python = ["3.12"]\n[[venv]]\nname = "dev"\n'
                        'packages = ["pandas"]\n', encoding="utf-8")
        code, out = run_cli("profile-check", str(prof), "--bundle", str(root))
        assert code == 0
        assert "applies cleanly" in out

    def test_an_unsatisfiable_profile_exits_one_and_names_everything(
            self, run_cli, home, tmp_path):
        root = self._bundle_on_disk(tmp_path)
        prof = tmp_path / "profile.toml"
        prof.write_text('python = ["3.9"]\n[[venv]]\nname = "dev"\n'
                        'packages = ["polars"]\n', encoding="utf-8")
        code, out = run_cli("profile-check", str(prof), "--bundle", str(root))
        assert code == 1
        assert "polars" in out and "3.9" in out

    def test_the_bundle_is_found_from_package_index(
            self, run_cli, home, tmp_path):
        """The zero-argument case on a machine installed from a bundle: the
        install already recorded where the wheels are."""
        root = self._bundle_on_disk(tmp_path)
        config.set_value("package_index", str(root / "wheels"))
        prof = tmp_path / "profile.toml"
        prof.write_text('[[venv]]\nname = "dev"\npackages = ["pandas"]\n',
                        encoding="utf-8")
        code, out = run_cli("profile-check", str(prof))
        assert code == 0 and str(root) in out

    def test_an_index_url_is_not_mistaken_for_a_bundle(
            self, run_cli, home, tmp_path):
        config.set_value("package_index", "https://pypi.corp/simple")
        prof = tmp_path / "profile.toml"
        prof.write_text('[[venv]]\nname = "dev"\n', encoding="utf-8")
        code, out = run_cli("profile-check", str(prof))
        assert code == 1 and "Couldn't work out which bundle" in out

    def test_a_broken_profile_exits_two(self, run_cli, home, tmp_path):
        root = self._bundle_on_disk(tmp_path)
        prof = tmp_path / "profile.toml"
        prof.write_text('[[venv]]\nname = ""\n', encoding="utf-8")
        code, out = run_cli("profile-check", str(prof), "--bundle", str(root))
        assert code == 2
