#!/usr/bin/env python3
"""Generate the three small flow diagrams embedded directly in README.md
(and, via docs/index.md, the docs homepage): why-vs-usual.svg,
install-flow.svg, lifecycle.svg.

These used to be mermaid diagrams (*.mmd rendered by mermaid-cli via
build.py) -- the only three in the repo. Hand-authoring them as plain SVG,
same as every other diagram under docs/diagrams/, removes the Node/mermaid-
cli dependency entirely: nothing under docs/diagrams/ needs anything but
Python to regenerate anymore, so docs/diagrams/build.py and its *.mmd inputs
are gone too (see CHANGELOG). Styled to match the rest of the diagram set
(NAVY/ICE/WHITE/DANGER, Georgia headings, Arial body) instead of mermaid's
default flowchart look, so a README scroll doesn't visibly change palette
between a hand-authored diagram and a mermaid one.

Hooked into the same docs/conf.py `_generate_diagrams` build-time pass as
generate_family_commands.py / generate_profile_
flows.py -- always fresh, never a stale committed SVG.

    python docs/diagrams/generate_marketing_flows.py
"""

from __future__ import annotations

from pathlib import Path

from generate_profile_flows import ICE, NAVY, WHITE, esc

DANGER = "#9C4A3C"
FONT_HEAD = "Georgia, 'Times New Roman', serif"
FONT_BODY = "Arial, Helvetica, sans-serif"
OUT_DIR = Path(__file__).parent

_DEFS = f"""
  <defs>
    <style>
      .head {{ font-family: {FONT_HEAD}; }}
      .body {{ font-family: {FONT_BODY}; }}
    </style>
    <marker id="mf-arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
      <path d="M0,0 L8,4 L0,8 Z" fill="#8A8A8A"/>
    </marker>
  </defs>
"""


def _wrap_box(x: float, y: float, w: float, h: float, lines: list[str], *,
             fill: str, text_fill: str, stroke: str, bold_first: bool = False) -> str:
    parts = [f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="10" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>']
    n = len(lines)
    line_h = 20
    start_y = y + h / 2 - (n - 1) * line_h / 2 + 5
    for i, line in enumerate(lines):
        weight = "700" if (bold_first and i == 0) or not bold_first else "400"
        parts.append(f'<text x="{x+w/2:.0f}" y="{start_y+i*line_h:.0f}" text-anchor="middle" '
                    f'class="body" font-size="13.5" font-weight="{weight}" fill="{text_fill}">{esc(line)}</text>')
    return "".join(parts)


def _harrow(x1: float, x2: float, y: float) -> str:
    return (f'<line x1="{x1:.0f}" y1="{y:.0f}" x2="{x2-6:.0f}" y2="{y:.0f}" '
           f'stroke="#8A8A8A" stroke-width="1.6" marker-end="url(#mf-arrow)"/>')


def _varrow(x: float, y1: float, y2: float) -> str:
    return (f'<line x1="{x:.0f}" y1="{y1:.0f}" x2="{x:.0f}" y2="{y2-6:.0f}" '
           f'stroke="#8A8A8A" stroke-width="1.6" marker-end="url(#mf-arrow)"/>')


def build_install_flow() -> None:
    """Run the one-liner -> seedling sets up everything -> open a terminal
    -> python just works (highlighted). A straight left-to-right chain."""
    w, h = 1040, 150
    box_h = 84
    y = (h - box_h) / 2
    boxes = [
        (190, ["Run the", "one-liner"], ICE, NAVY, NAVY, False),
        (260, ["seedling sets up everything", "Python needs, automatically"], ICE, NAVY, NAVY, False),
        (190, ["Open a new", "terminal"], ICE, NAVY, NAVY, False),
        (330, ["python just works",
               "seed install requests adds packages",
               "seed vscode opens the editor"], NAVY, WHITE, NAVY, True),
    ]
    gap = 34
    total_w = sum(b[0] for b in boxes) + gap * (len(boxes) - 1)
    x = (w - total_w) / 2

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="{FONT_BODY}">', _DEFS]
    prev_right = None
    for bw, lines, fill, tf, stroke, bold in boxes:
        if prev_right is not None:
            svg.append(_harrow(prev_right, x, y + box_h / 2))
        svg.append(_wrap_box(x, y, bw, box_h, lines, fill=fill, text_fill=tf, stroke=stroke, bold_first=bold))
        prev_right = x + bw
        x += bw + gap

    svg.append("</svg>")
    (OUT_DIR / "install-flow.svg").write_text("\n".join(svg), encoding="utf-8")
    print(f"wrote install-flow.svg  ({w}x{h})")


def build_lifecycle() -> None:
    """Install -> Use -> Uninstall, with Use <-> Update looping beneath Use."""
    w, h = 830, 260
    box_w, box_h = 220, 76
    row_y = 30
    gap = 60

    install_x = 40
    use_x = install_x + box_w + gap
    uninstall_x = use_x + box_w + gap
    update_y = row_y + box_h + 70
    update_x = use_x

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="{FONT_BODY}">', _DEFS]
    svg.append(_harrow(install_x + box_w, use_x, row_y + box_h / 2))
    svg.append(_harrow(use_x + box_w, uninstall_x, row_y + box_h / 2))
    down_x = update_x + box_w * 0.32
    up_x = update_x + box_w * 0.68
    svg.append(_varrow(down_x, row_y + box_h, update_y))
    svg.append(f'<line x1="{up_x:.0f}" y1="{update_y:.0f}" x2="{up_x:.0f}" y2="{row_y+box_h+6:.0f}" '
              f'stroke="#8A8A8A" stroke-width="1.6" marker-end="url(#mf-arrow)"/>')

    svg.append(_wrap_box(install_x, row_y, box_w, box_h, ["Install", "one-liner"],
                         fill=NAVY, text_fill=WHITE, stroke=NAVY, bold_first=True))
    svg.append(_wrap_box(use_x, row_y, box_w, box_h, ["Use", "seed venv / install / vscode"],
                         fill=ICE, text_fill=NAVY, stroke=NAVY, bold_first=True))
    svg.append(_wrap_box(uninstall_x, row_y, box_w, box_h, ["Uninstall", "seed purge → gone, cleanly"],
                         fill=DANGER, text_fill=WHITE, stroke=DANGER, bold_first=True))
    svg.append(_wrap_box(update_x, update_y, box_w, box_h, ["Update (optional)", "seed update-commands"],
                         fill=ICE, text_fill=NAVY, stroke=NAVY, bold_first=True))

    svg.append("</svg>")
    (OUT_DIR / "lifecycle.svg").write_text("\n".join(svg), encoding="utf-8")
    print(f"wrote lifecycle.svg  ({w}x{h})")


def build_why_vs_usual() -> None:
    """Getting started with Python -> branches into "the usual way" (red)
    and "with seedling" (green/navy)."""
    w, h = 760, 300
    top_w, top_h = 300, 56
    top_x, top_y = (w - top_w) / 2, 20

    col_w, col_h = 330, 96
    left_x = w * 0.27 - col_w / 2
    right_x = w * 0.73 - col_w / 2
    col_y = 190
    label_y = col_y - 34
    branch_y = top_y + top_h + 26

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="{FONT_BODY}">', _DEFS]

    mid_x = w / 2
    left_cx = left_x + col_w / 2
    right_cx = right_x + col_w / 2
    svg.append(f'<line x1="{mid_x:.0f}" y1="{top_y+top_h:.0f}" x2="{mid_x:.0f}" y2="{branch_y:.0f}" stroke="#8A8A8A" stroke-width="1.6"/>')
    svg.append(f'<line x1="{left_cx:.0f}" y1="{branch_y:.0f}" x2="{right_cx:.0f}" y2="{branch_y:.0f}" stroke="#8A8A8A" stroke-width="1.6"/>')
    svg.append(_varrow(left_cx, branch_y, label_y + 24))
    svg.append(_varrow(right_cx, branch_y, label_y + 24))

    svg.append(f'<text x="{left_cx:.0f}" y="{label_y:.0f}" text-anchor="middle" class="body" font-size="13.5" font-weight="700" fill="{NAVY}">The usual way</text>')
    svg.append(f'<text x="{right_cx:.0f}" y="{label_y:.0f}" text-anchor="middle" class="body" font-size="13.5" font-weight="700" fill="{NAVY}">With seedling</text>')

    svg.append(_wrap_box(top_x, top_y, top_w, top_h, ["Getting started with Python"],
                         fill=NAVY, text_fill=WHITE, stroke=NAVY, bold_first=True))
    svg.append(_wrap_box(left_x, col_y, col_w, col_h,
                         ["research, install, and connect several tools —",
                          "hours of setup and decisions",
                          "before your first line of code"],
                         fill=DANGER, text_fill=WHITE, stroke=DANGER))
    svg.append(_wrap_box(right_x, col_y, col_w, col_h,
                         ["run one command → open a terminal →",
                          "you're writing Python"],
                         fill=NAVY, text_fill=WHITE, stroke=NAVY))

    svg.append("</svg>")
    (OUT_DIR / "why-vs-usual.svg").write_text("\n".join(svg), encoding="utf-8")
    print(f"wrote why-vs-usual.svg  ({w}x{h})")


def build() -> None:
    build_install_flow()
    build_lifecycle()
    build_why_vs_usual()


if __name__ == "__main__":
    build()
