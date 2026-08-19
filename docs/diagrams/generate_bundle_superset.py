#!/usr/bin/env python3
"""Generate bundle-superset.svg -- the containment argument, drawn.

Three claims the prose makes repeatedly, in one picture:

  1. The offline bundle is the SUPERSET. Everything that crosses onto the
     air-gapped network is inside it; nothing reaches that network any other
     way.
  2. A profile is a SUBSET of it. Drawn nested inside the superset, because
     that is exactly the constraint -- a profile naming something the bundle
     doesn't hold has nowhere to get it from. That is why `--check-profile`
     and `seed profile-check` exist, and why the profile that asks for more is
     drawn outside the boundary with the crossing struck through.
  3. global.conf is NOT part of that set. It configures each user's machine:
     it holds no packages, it points at where the packages already are. So it
     sits outside the superset with an arrow INTO it.

Style comes from generate_profile_flows (same palette, defs and header), so
this page looks like the rest of the diagram set. Run:

    python docs/diagrams/generate_bundle_superset.py
"""

from __future__ import annotations

from pathlib import Path

from generate_profile_flows import DEFS, ICE, NAVY, SLATE, WHITE, esc, header

OUT_DIR = Path(__file__).parent
FONT_MONO = "Consolas, 'SF Mono', Monaco, 'Courier New', monospace"

DANGER = "#9C4A3C"
DANGER_TINT = "#F7ECE9"
PROFILE_TINT = "#D8EEE0"

W, H = 1180, 1010

# What physically crosses the gap, in the order the bundle lays it out.
CONTENTS = [
    ("wheels/", "every distribution any profile may name"),
    ("python-builds/", "the interpreter archives"),
    ("conda-channel/", "conda-forge command-line tools"),
    ("vendor/vscode/", "the editor, with its extensions"),
    ("vendor/uv/, vendor/git/", "uv, and MinGit when asked for"),
    ("seedling/", "the source users install from"),
]

PROFILES = [
    ("dev.toml", ["python 3.12", "pandas, pytest", "VS Code"]),
    ("analysis.toml", ["python 3.12", "pandas, numpy", "jupyterlab"]),
    ("batch.toml", ["python 3.11", "pandas"]),
]

POINTERS = [
    ("SEEDLING_PACKAGE_INDEX", "wheels/"),
    ("SEEDLING_PYTHON_MIRROR", "python-builds/"),
    ("SEEDLING_CONDA_CHANNEL", "conda-channel/"),
    ("SEEDLING_REPO_URL", "seedling/"),
]


def _text(x, y, s, *, size=13, cls="body fg", weight=None, anchor=None,
          family=None, style=None, fill=None):
    attrs = [f'x="{x}"', f'y="{y}"', f'class="{cls}"', f'font-size="{size}"']
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    if family:
        attrs.append(f'font-family="{family}"')
    if style:
        attrs.append(f'font-style="{style}"')
    if fill:
        attrs.append(f'fill="{fill}"')
    return "  <text " + " ".join(attrs) + ">" + esc(s) + "</text>"


def build() -> str:
    o: list[str] = []
    o.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" aria-label="The offline bundle as '
        f'the superset of everything on the air-gapped network, with '
        f'deployment profiles drawn as subsets inside it, a profile that asks '
        f'for more drawn outside it, and global.conf outside pointing in.">')
    o.append(f'  <rect width="{W}" height="{H}" fill="{WHITE}"/>')
    o.append(DEFS)
    o.append(header("What crosses the air gap",
                    "The bundle is the superset. A profile is a subset of it. "
                    "global.conf points at it."))

    # ---- the superset -----------------------------------------------------
    bx, by, bw, bh = 40, 112, 700, 660
    o.append(f'  <rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="16" '
             f'fill="{ICE}" stroke="{NAVY}" stroke-width="2.4"/>')
    o.append(_text(bx + 24, by + 36, "The offline bundle", size=19,
                   cls="head fg", weight="700"))
    o.append(_text(bx + 24, by + 58,
                   "declared by offline-bundle.toml, built once, carried in once",
                   size=12.5, cls="body fmute", style="italic"))
    o.append(_text(bx + bw - 24, by + 36, "SUPERSET", size=12,
                   cls="body fmute", weight="700", anchor="end"))

    cy = by + 82
    for label, detail in CONTENTS:
        o.append(f'  <rect x="{bx + 24}" y="{cy}" width="{bw - 48}" height="34" '
                 f'rx="7" fill="{WHITE}" stroke="{SLATE}" stroke-width="1.1"/>')
        o.append(_text(bx + 38, cy + 22, label, size=13, weight="700",
                       family=FONT_MONO))
        o.append(_text(bx + 268, cy + 22, detail, size=12.5, cls="body fmute"))
        cy += 42

    # ---- profiles, nested inside ------------------------------------------
    py = cy + 22
    o.append(_text(bx + 24, py, "Deployment profiles, each a SUBSET of the above",
                   size=13.5, weight="700"))
    o.append(_text(bx + 24, py + 20,
                   "installation-profile/*.toml, checked against the bundle "
                   "before it is built",
                   size=12, cls="body fmute", style="italic"))
    py += 38
    pw = (bw - 48 - 2 * 16) / 3
    for i, (name, lines) in enumerate(PROFILES):
        px = bx + 24 + i * (pw + 16)
        o.append(f'  <rect x="{px}" y="{py}" width="{pw}" height="118" rx="10" '
                 f'fill="{PROFILE_TINT}" stroke="{NAVY}" stroke-width="1.6"/>')
        o.append(_text(px + 14, py + 26, name, size=13, weight="700",
                       family=FONT_MONO))
        ly = py + 50
        for line in lines:
            o.append(_text(px + 14, ly, "- " + line, size=11.8,
                           cls="body fmute"))
            ly += 19
    o.append(_text(bx + 24, py + 146,
                   "Every name resolves inside the box, so `seed apply` works "
                   "with no network at all.",
                   size=12, cls="body fmute"))

    # ---- the profile that doesn't fit -------------------------------------
    ox, oy, ow, oh = 800, 300, 340, 158
    o.append(f'  <rect x="{ox}" y="{oy}" width="{ow}" height="{oh}" rx="10" '
             f'fill="{DANGER_TINT}" stroke="{DANGER}" stroke-width="1.8" '
             f'stroke-dasharray="7 4"/>')
    o.append(_text(ox + 16, oy + 28, "reporting.toml", size=13, weight="700",
                   family=FONT_MONO, cls="body", fill=DANGER))
    o.append(_text(ox + 16, oy + 52, "- pandas", size=12.2, cls="body fmute"))
    o.append(_text(ox + 16, oy + 72, "- polars      not in the bundle",
                   size=12.2, cls="body", fill=DANGER))
    o.append(_text(ox + 16, oy + 100,
                   "Outside the superset, so there is nowhere",
                   size=12, cls="body fmute"))
    o.append(_text(ox + 16, oy + 118,
                   "for it to come from: no index, no share,",
                   size=12, cls="body fmute"))
    o.append(_text(ox + 16, oy + 136, "no internet.", size=12, cls="body fmute"))

    o.append(f'  <path d="M{ox - 8} {oy + 74} L{bx + bw + 46} {oy + 74}" '
             f'stroke="{DANGER}" stroke-width="2" stroke-dasharray="6 4" '
             f'fill="none"/>')
    o.append(f'  <path d="M{bx + bw + 34} {oy + 62} L{bx + bw + 10} {oy + 86} '
             f'M{bx + bw + 10} {oy + 62} L{bx + bw + 34} {oy + 86}" '
             f'stroke="{DANGER}" stroke-width="2.8" stroke-linecap="round"/>')
    o.append(_text(ox + ow, oy - 10,
                   "caught on the connected machine, not by a user",
                   size=11.5, cls="body", anchor="end", style="italic",
                   fill=DANGER))

    # ---- global.conf ------------------------------------------------------
    gx, gy, gw, gh = 800, 492, 340, 280
    o.append(f'  <rect x="{gx}" y="{gy}" width="{gw}" height="{gh}" rx="12" '
             f'fill="{WHITE}" stroke="{NAVY}" stroke-width="2"/>')
    o.append(_text(gx + 18, gy + 34, "global.conf", size=17, cls="head fg",
                   weight="700"))
    o.append(_text(gx + 18, gy + 56, "the user environment configuration",
                   size=12, cls="body fmute", style="italic"))
    o.append(_text(gx + 18, gy + 74, "carries nothing; it says where to look",
                   size=12, cls="body fmute", style="italic"))
    ky = gy + 106
    for key, target in POINTERS:
        o.append(_text(gx + 18, ky, key, size=11.2, family=FONT_MONO,
                       weight="700"))
        o.append(_text(gx + 30, ky + 17, "-> " + target, size=11.2,
                       family=FONT_MONO, cls="body fmute"))
        ky += 42
    o.append(f'  <path d="M{gx - 8} {gy + 140} C{gx - 70} {gy + 140} '
             f'{bx + bw + 70} {by + 430} {bx + bw + 8} {by + 430}" '
             f'stroke="{NAVY}" stroke-width="2" fill="none" '
             f'marker-end="url(#arrow)"/>')
    o.append(_text(gx - 24, gy + 122, "every user's machine", size=11.5,
                   cls="body fmute", anchor="end", style="italic"))
    o.append(_text(gx - 24, gy + 138, "resolves to the share", size=11.5,
                   cls="body fmute", anchor="end", style="italic"))

    o.append(_text(40, H - 30,
                   "Things enter the set only on the connected side. A profile "
                   "selects from the set; it can never add to it.",
                   size=12.5, cls="body fmute", style="italic"))
    o.append("</svg>")
    return "\n".join(o) + "\n"


def main() -> None:
    path = OUT_DIR / "bundle-superset.svg"
    path.write_text(build(), encoding="utf-8")
    print(f"wrote {path.name}  ({W}x{H})")


if __name__ == "__main__":
    main()
