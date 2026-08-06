"""The `thing[extra,extra]` spelling, shared by `seed repo-install` and
`[[repo]] install` so the two can't drift apart."""

from __future__ import annotations

import pytest

from seedling import pkgspec


@pytest.mark.parametrize("spec,expected", [
    ("proj", ("proj", [])),
    ("proj[gui]", ("proj", ["gui"])),
    ("proj[gui,dev]", ("proj", ["gui", "dev"])),
    ("proj[gui, dev]", ("proj", ["gui", "dev"])),   # tolerated, as in pip
    ("proj[gui,gui]", ("proj", ["gui"])),           # de-duplicated
    ("dev[gui]", ("dev", ["gui"])),                 # the profile's target form
])
def test_split_extras(spec, expected):
    assert pkgspec.split_extras(spec) == expected


@pytest.mark.parametrize("spec", ["proj[gui", "proj[gui]x", "proj[]",
                                  "proj[gui,]", "proj[,]", "proj[ ]"])
def test_a_malformed_spec_raises(spec):
    with pytest.raises(pkgspec.BadExtras):
        pkgspec.split_extras(spec)


@pytest.mark.parametrize("name,extras,expected", [
    ("proj", [], "proj"),
    ("proj", ["gui"], "proj[gui]"),
    ("proj", ["gui", "dev"], "proj[gui,dev]"),
])
def test_join_extras_round_trips(name, extras, expected):
    assert pkgspec.join_extras(name, extras) == expected
    assert pkgspec.split_extras(expected) == (name, extras)
