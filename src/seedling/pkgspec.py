"""Parsing for the `thing[extra,extra]` spelling.

One implementation, two callers: `seed repo-install plotpress[gui]` on the
command line, and `[[repo]] install = ["dev[gui]"]` in a profile. The two
have to agree exactly -- a profile is meant to say what a user could have
typed -- so neither owns the parser.
"""

from __future__ import annotations


class BadExtras(ValueError):
    pass


def split_extras(spec: str) -> tuple[str, list[str]]:
    """Split `name[extra,extra]` into the name and its extras, the same shape
    pip and uv accept for a package spec. A plain `name` yields no extras."""
    head, bracket, rest = spec.partition("[")
    if not bracket:
        return spec, []
    if not rest.endswith("]"):
        raise BadExtras(f"unbalanced brackets in {spec!r} -- expected name[extra,...]")
    extras: list[str] = []
    for extra in rest[:-1].split(","):
        extra = extra.strip()
        if not extra:
            raise BadExtras(f"empty extra in {spec!r} -- expected name[extra,...]")
        if extra not in extras:
            extras.append(extra)
    return head.strip(), extras


def join_extras(name: str, extras: list[str]) -> str:
    """The inverse: `("proj", ["gui"])` -> `"proj[gui]"`. Used to build the
    spec `seed apply` hands to `seed repo-install`, so what runs is spelled
    exactly like what a user would type."""
    return f"{name}[{','.join(extras)}]" if extras else name
