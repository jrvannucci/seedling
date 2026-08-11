#!/usr/bin/env python3
"""Generate two SVGs per example profile in ../PROFILE-EXAMPLES.md:

  profile-build-<slug>.svg   only for profiles that build a bundle --
                              sources on the left, the offline-bundle/
                              folder each one is staged into on the right.

  profile-pull-<slug>.svg    every profile -- one box per ORIGIN the user's
                              machine actually talks to (a host, or the
                              seedling bundle/share itself), each with the
                              handful of things it provides, and a labeled
                              arrow per thing showing the command that pulls
                              it in.

The two answer different questions on purpose. "Where did the bundle come
from" (profile-build) and "where does a deployed machine reach out to"
(profile-pull) are different diagrams even for a profile that has a bundle
in between -- the build side cares about astral.sh and python-build-
standalone, the pull side only cares about the share, because that's all
the deployed machine ever sees.

The key move on the pull side is grouping by ORIGIN, not by capability: if
one host serves several things (Internal mirrors' artifactory.corp.example
proxies packages, Spyder, conda-forge tools AND interpreters all at once;
the offline bundle itself is one folder tree that hands out uv, wheels,
python-builds, a conda channel, the editor, git, and a CA cert), that's ONE
box with several small chips inside it and one labeled arrow per chip --
not N separate boxes that happen to all point at the same place.

The data below is transcribed BY HAND from PROFILE-EXAMPLES.md's "Assumes"
table, TOML, and conf blocks -- there is no automated link between the two.
If a profile's sources, hosts, or offline shape change there, update its
entry here too and re-run:

    python docs/diagrams/generate_profile_flows.py

Unlike the *.mmd -> *.svg diagrams build.py in this same directory, these
are hand-authored SVG rather than Mermaid: grouped origin boxes with nested
chips and per-chip labeled arrows don't map onto Mermaid's flowchart
syntax."""

from __future__ import annotations
from pathlib import Path

NAVY = "#1B4332"
ICE = "#E9F5EC"
WHITE = "#FFFFFF"
SLATE = "#52796F"
TARGET_TINT = "#EAF3EE"

FONT_HEAD = "Georgia, 'Times New Roman', serif"
FONT_BODY = "Arial, Helvetica, sans-serif"

OUT_DIR = Path(__file__).parent


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


DEFS = f"""
  <defs>
    <style>
      .head  {{ font-family: {FONT_HEAD}; }}
      .body  {{ font-family: {FONT_BODY}; }}
      .fg    {{ fill: {NAVY}; }}
      .fw    {{ fill: {WHITE}; }}
      .fmute {{ fill: {SLATE}; }}
    </style>
    <marker id="arrow" markerWidth="7" markerHeight="7" refX="5.5" refY="3.5" orient="auto">
      <path d="M0,0 L7,3.5 L0,7 Z" fill="{NAVY}"/>
    </marker>
    <symbol id="ic-cloud" viewBox="0 0 24 24">
      <path d="M6.5 18 C3.5 18 2 15.8 2 13.8 C2 11.6 3.8 10 5.8 10.1 C6.4 7.6 8.7 6 11.2 6.3 C13.6 6.6 15.4 8.6 15.5 11 C17.9 11.1 20 13 20 15.3 C20 17.4 18.2 18 17 18 Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
    </symbol>
    <symbol id="ic-box" viewBox="0 0 24 24">
      <path d="M3 8 L12 4 L21 8 L12 12 Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M3 8 V17 L12 21 V12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M21 8 V17 L12 21" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
    </symbol>
    <symbol id="ic-server" viewBox="0 0 24 24">
      <rect x="3" y="4" width="18" height="6" rx="1.3" fill="none" stroke="currentColor" stroke-width="1.6"/>
      <rect x="3" y="14" width="18" height="6" rx="1.3" fill="none" stroke="currentColor" stroke-width="1.6"/>
      <circle cx="7" cy="7" r="1" fill="currentColor"/>
      <circle cx="7" cy="17" r="1" fill="currentColor"/>
    </symbol>
    <symbol id="ic-monitor" viewBox="0 0 24 24">
      <rect x="2.5" y="4" width="19" height="13" rx="1.4" fill="none" stroke="currentColor" stroke-width="1.6"/>
      <line x1="8" y1="21" x2="16" y2="21" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
      <line x1="12" y1="17" x2="12" y2="21" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
    </symbol>
    <symbol id="ic-folder" viewBox="0 0 24 24">
      <path d="M3 6.5 C3 5.7 3.7 5 4.5 5 H9.5 L11.5 7.5 H19.5 C20.3 7.5 21 8.2 21 9 V17.5 C21 18.3 20.3 19 19.5 19 H4.5 C3.7 19 3 18.3 3 17.5 Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
    </symbol>
    <symbol id="ic-doc" viewBox="0 0 24 24">
      <path d="M6 3 H14 L19 8 V20 C19 20.6 18.6 21 18 21 H6 C5.4 21 5 20.6 5 20 V4 C5 3.4 5.4 3 6 3 Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M14 3 V8 H19" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
      <line x1="8" y1="12" x2="16" y2="12" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
      <line x1="8" y1="15.5" x2="16" y2="15.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
      <line x1="8" y1="19" x2="12.5" y2="19" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
    </symbol>
  </defs>
"""


def header(title: str, subtitle: str) -> str:
    return f"""
  <g transform="translate(40,20)">
    <path d="M12 42 V16" stroke="{NAVY}" stroke-width="2.6" stroke-linecap="round" fill="none"/>
    <path d="M12 23 C12 14 5 12 0 14 C0 21 5 25 12 23 Z" fill="#74C69D" stroke="{NAVY}" stroke-width="1.4" stroke-linejoin="round"/>
    <path d="M12 19 C12 11 20 9 25 11 C25 18 20 22 12 19 Z" fill="#95D5B2" stroke="{NAVY}" stroke-width="1.4" stroke-linejoin="round"/>
  </g>
  <text x="94" y="54" class="head fg" font-size="25" font-weight="700">{esc(title)}</text>
  <text x="40" y="79" class="body fmute" font-size="13.5" font-style="italic">{esc(subtitle)}</text>
"""


def _fit(text: str, avail_px: float, base_size: float, px_per_char: float = 6.6) -> float:
    budget = avail_px / px_per_char
    if len(text) <= budget:
        return base_size
    return max(9.5, base_size * budget / len(text))


def cell(x: float, y: float, w: float, h: float, label: str, sub: str, *,
        dark: bool) -> str:
    fill = NAVY if dark else ICE
    label_cls = "fw" if dark else "fg"
    sub_color = "#CFE3D6" if dark else SLATE
    border = "" if dark else f'stroke="{NAVY}" stroke-width="1" opacity="0.8"'
    label_size = _fit(label, w - 24, 13)
    sub_size = _fit(sub, w - 24, 10.8, px_per_char=5.6) if sub else 10.8
    parts = [f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="9" fill="{fill}" {border}/>']
    if sub:
        parts.append(f'<text x="{x+12:.0f}" y="{y+h/2-4:.0f}" class="body {label_cls}" font-size="{label_size:.1f}" font-weight="700">{esc(label)}</text>')
        parts.append(f'<text x="{x+12:.0f}" y="{y+h/2+13:.0f}" class="body" fill="{sub_color}" font-size="{sub_size:.1f}">{esc(sub)}</text>')
    else:
        parts.append(f'<text x="{x+12:.0f}" y="{y+h/2+5:.0f}" class="body {label_cls}" font-size="{label_size:.1f}" font-weight="700">{esc(label)}</text>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# Part 1: profile-build-<slug>.svg -- sources -> what's staged into the
# bundle. Only generated for profiles that have a `build` list (i.e. build
# a bundle at all).
# ---------------------------------------------------------------------------

B_CAP_X, B_CAP_W = 40, 150
B_SRC_X, B_SRC_W = 200, 320
B_MID_X, B_MID_W = 560, 340
B_CANVAS_W = 940


B_HEAD_H = 40   # height of the "offline-bundle/" header drawn inside the box
B_BOX_PAD = 16  # gap between the box's outer edge and the header/chips it contains


def build_part1(slug: str, title: str, subtitle: str, rows: list[dict]) -> None:
    row_h = 54
    gap = 10
    pitch = row_h + gap
    table_top = 150
    table_h = len(rows) * pitch - gap
    box_top = table_top - B_HEAD_H - B_BOX_PAD
    box_bottom = table_top + table_h + B_BOX_PAD
    canvas_h = box_bottom + 40

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {B_CANVAS_W} {canvas_h:.0f}" font-family="Arial, Helvetica, sans-serif">']
    svg.append(f"<defs>{DEFS}</defs>")
    svg.append(f'<rect x="0" y="0" width="{B_CANVAS_W}" height="{canvas_h:.0f}" fill="{WHITE}"/>')
    svg.append(header(title, subtitle))

    svg.append(f'<text x="{B_SRC_X}" y="{table_top-14:.0f}" class="body fg" font-size="12.5" font-weight="700" letter-spacing="0.8">PULLED FROM</text>')

    # one box for the whole offline-bundle/ -- everything below is staged
    # into this single folder tree, not N independent destinations
    box_x = B_MID_X - B_BOX_PAD
    box_w = B_MID_W + 2 * B_BOX_PAD
    svg.append(f'<rect x="{box_x:.0f}" y="{box_top:.0f}" width="{box_w:.0f}" height="{box_bottom-box_top:.0f}" rx="14" fill="{TARGET_TINT}" stroke="{NAVY}" stroke-width="1.4"/>')
    svg.append(f'<use href="#ic-box" x="{box_x+16:.0f}" y="{box_top+12:.0f}" width="20" height="20" color="{NAVY}"/>')
    svg.append(f'<text x="{box_x+46:.0f}" y="{box_top+27:.0f}" class="body fg" font-size="15" font-weight="700">offline-bundle/</text>')
    svg.append(f'<text x="{box_x+46:.0f}" y="{box_top+41:.0f}" class="body fmute" font-size="11" font-style="italic">everything below is staged into this one folder tree</text>')

    for i, r in enumerate(rows):
        y = table_top + i * pitch
        cy = y + row_h / 2
        svg.append(f'<text x="{B_CAP_X}" y="{cy+4:.0f}" class="body fg" font-size="12.5" font-weight="700">{esc(r["cap"])}</text>')
        svg.append(cell(B_SRC_X, y, B_SRC_W, row_h, r["src"], r["src_sub"], dark=False))
        svg.append(cell(B_MID_X, y, B_MID_W, row_h, r["mid"], r["mid_sub"], dark=True))
        svg.append(f'<line x1="{B_SRC_X+B_SRC_W}" y1="{cy:.0f}" x2="{B_MID_X-4}" y2="{cy:.0f}" stroke="{NAVY}" stroke-width="1.4" marker-end="url(#arrow)"/>')

    svg.append("</svg>")
    (OUT_DIR / f"profile-build-{slug}.svg").write_text("\n".join(svg), encoding="utf-8")
    print(f"wrote profile-build-{slug}.svg  ({B_CANVAS_W}x{canvas_h:.0f}, {len(rows)} rows)")


def brow(cap, src, src_sub, mid, mid_sub):
    return dict(cap=cap, src=src, src_sub=src_sub, mid=mid, mid_sub=mid_sub)


# ---------------------------------------------------------------------------
# Part 2: profile-pull-<slug>.svg -- one box per ORIGIN (a host, or the
# bundle/share), each with a chip per thing it provides and one labeled
# arrow per chip into a single "YOUR MACHINE" box. Generated for every
# profile.
# ---------------------------------------------------------------------------

P_GROUP_X, P_GROUP_W = 40, 470
P_CHIP_H, P_CHIP_GAP = 32, 8
P_HEAD_H = 46
P_PAD = 14
P_GROUP_GAP = 26
P_ARROW_GAP = 130
P_MACHINE_W = 320
P_CANVAS_W = P_GROUP_X + P_GROUP_W + P_ARROW_GAP + P_MACHINE_W + 40

_ICONS = {"internet": "ic-cloud", "internal": "ic-server", "bundle": "ic-box"}
_KIND_FILL = {"internet": ICE, "internal": ICE, "bundle": TARGET_TINT}


def item(label: str, via: str) -> dict:
    return dict(label=label, via=via)


def stored(path: str, note: str, items: list[str]) -> dict:
    """One storage location under ~/seedling (per the on-disk layout in
    GUIDE.md) inside the YOUR MACHINE box -- a folder, and the specific
    things kept in it. Mirrors `group()` on the pull side: the folder is
    the outer box, `items` are the sub-chips inside it, same nesting
    language as an origin hosting several capabilities."""
    return dict(path=path, note=note, items=items)


def group(host: str, note: str, items: list[dict], *, kind: str = "internet") -> dict:
    return dict(host=host, note=note, items=items, kind=kind)


def _group_height(g: dict) -> float:
    return P_HEAD_H + len(g["items"]) * (P_CHIP_H + P_CHIP_GAP) - P_CHIP_GAP + P_PAD


M_BULLET_GAP = 16  # gap between the location note and the storage stack
M_LABEL_H = 24     # the "WHAT THE USER HAS" divider + caption line

SH_PAD = 14        # inset of a storage box from the machine box's edge
SH_HEAD_H = 32     # folder icon + path + note, inside a storage box
SH_ITEM_H = 21
SH_ITEM_GAP = 6
SH_INNER_PAD = 10  # inset of item chips within their storage box
SH_GROUP_GAP = 12  # gap between storage boxes


def _storage_height(s: dict) -> float:
    n = len(s["items"])
    items_h = n * (SH_ITEM_H + SH_ITEM_GAP) - SH_ITEM_GAP if n else 0
    return SH_HEAD_H + items_h + SH_INNER_PAD


def subchip(x: float, y: float, w: float, h: float, label: str) -> str:
    fs = _fit(label, w - 16, 11.5, px_per_char=6.2)
    return (f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="6" fill="{WHITE}" stroke="{NAVY}" stroke-width="0.9"/>'
            f'<text x="{x+9:.0f}" y="{y+h/2+4:.0f}" class="body fg" font-size="{fs:.1f}" font-weight="600">{esc(label)}</text>')


CONFIG_GAP = 42      # space for the connector arrow + its label
CONFIG_NOTE = "one file, read at install and every later `seed apply`"

# which TOML section in seedling-profile.toml is responsible for each
# on-disk storage location -- derived from `storage`, so the config box
# lists exactly the sections THIS profile actually uses, never a generic
# list. Order matters: more specific prefixes first.
_CONFIG_KEY_FOR = [
    ("python/venvs/", "[[venv]]"),
    ("python/base/", "python = [...]"),
    ("extensions/", "editor = ..."),
    ("system/conda/", "tools = [...]"),
    ("repo/", "[[repo]]"),
]


def _config_key_lines(storage: list[dict]) -> list[str]:
    seen: dict[str, str] = {}
    for s in storage:
        for prefix, key in _CONFIG_KEY_FOR:
            if s["path"].startswith(prefix) and key not in seen:
                seen[key] = prefix
                break
    return [f"{key}  →  {path}" for key, path in seen.items()]


CFG_ITEM_H = 22
CFG_ITEM_GAP = 6


def build_part2(slug: str, title: str, subtitle: str, groups: list[dict],
                machine_note: str, storage: list[dict] | None = None,
                footnote: str | None = None, config_label: str = "seedling-profile.toml",
                config_via: str = "install + seed apply") -> None:
    storage = storage or []
    config_lines = _config_key_lines(storage)
    note_wrap = _wrap(CONFIG_NOTE, 40)
    config_items_h = len(config_lines) * (CFG_ITEM_H + CFG_ITEM_GAP) - CFG_ITEM_GAP if config_lines else 0
    config_h = 44 + len(note_wrap) * 12 + (6 + config_items_h if config_lines else 0) + 10
    base_top = 150
    table_top = base_top + config_h + CONFIG_GAP
    heights = [_group_height(g) for g in groups]
    groups_h = sum(heights) + P_GROUP_GAP * (len(groups) - 1)

    note_lines = _wrap(machine_note, 34)
    storage_heights = [_storage_height(s) for s in storage]
    storage_h = sum(storage_heights) + SH_GROUP_GAP * (len(storage) - 1) if storage else 0
    # icon+title row, the note lines, a gap, a caption, then one box per
    # storage location (each with its own nested item chips)
    machine_h = 30 + len(note_lines) * 15 + (M_BULLET_GAP + M_LABEL_H + storage_h if storage else 0) + 14

    total_h = max(groups_h, machine_h)
    canvas_h = table_top + total_h + 50 + (26 if footnote else 0)

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {P_CANVAS_W} {canvas_h:.0f}" font-family="Arial, Helvetica, sans-serif">']
    svg.append(f"<defs>{DEFS}</defs>")
    svg.append(f'<rect x="0" y="0" width="{P_CANVAS_W}" height="{canvas_h:.0f}" fill="{WHITE}"/>')
    svg.append(header(title, subtitle))

    machine_x = P_GROUP_X + P_GROUP_W + P_ARROW_GAP

    # the config box -- deliberately the same dark treatment as a "bundle"
    # box elsewhere in this set, so it reads as the one authoritative
    # source, with a connector arrow showing it's what builds YOUR MACHINE
    svg.append(f'<rect x="{machine_x:.0f}" y="{base_top:.0f}" width="{P_MACHINE_W:.0f}" height="{config_h:.0f}" rx="12" fill="{NAVY}"/>')
    svg.append(f'<use href="#ic-doc" x="{machine_x+18:.0f}" y="{base_top+13:.0f}" width="22" height="22" color="{WHITE}"/>')
    cfg_label_size = _fit(config_label, P_MACHINE_W - 96, 14, px_per_char=6.4)
    svg.append(f'<text x="{machine_x+52:.0f}" y="{base_top+28:.0f}" class="body fw" font-size="{cfg_label_size:.1f}" font-weight="700">{esc(config_label)}</text>')
    for j, line in enumerate(note_wrap):
        svg.append(f'<text x="{machine_x+18:.0f}" y="{base_top+44+j*12:.0f}" class="body" fill="#CFE3D6" font-size="10" font-style="italic">{esc(line)}</text>')

    if config_lines:
        keys_top = base_top + 44 + len(note_wrap) * 12 + 6
        svg.append(f'<line x1="{machine_x+18:.0f}" y1="{keys_top-8:.0f}" x2="{machine_x+P_MACHINE_W-18:.0f}" y2="{keys_top-8:.0f}" stroke="{WHITE}" stroke-width="1" opacity="0.2"/>')
        cfg_chip_w = P_MACHINE_W - 36
        for j, line in enumerate(config_lines):
            cy = keys_top + j * (CFG_ITEM_H + CFG_ITEM_GAP)
            svg.append(subchip(machine_x + 18, cy, cfg_chip_w, CFG_ITEM_H, line))

    conn_x = machine_x + P_MACHINE_W / 2
    conn_y1 = base_top + config_h
    conn_y2 = table_top
    svg.append(f'<line x1="{conn_x:.0f}" y1="{conn_y1:.0f}" x2="{conn_x:.0f}" y2="{conn_y2-4:.0f}" stroke="{NAVY}" stroke-width="1.6" marker-end="url(#arrow)"/>')
    via_size = _fit(config_via, P_MACHINE_W - 20, 10.5, px_per_char=5.6)
    svg.append(f'<text x="{conn_x+10:.0f}" y="{(conn_y1+conn_y2)/2+4:.0f}" class="body fmute" font-size="{via_size:.1f}" font-style="italic">{esc(config_via)}</text>')

    svg.append(f'<rect x="{machine_x:.0f}" y="{table_top:.0f}" width="{P_MACHINE_W:.0f}" height="{total_h:.0f}" rx="12" fill="{TARGET_TINT}" stroke="{NAVY}" stroke-width="1.2"/>')

    content_top = table_top + max(0, (total_h - machine_h) / 2)
    svg.append(f'<use href="#ic-monitor" x="{machine_x+22:.0f}" y="{content_top+4:.0f}" width="24" height="24" color="{NAVY}"/>')
    svg.append(f'<text x="{machine_x+56:.0f}" y="{content_top+21:.0f}" class="body fg" font-size="15" font-weight="700">YOUR MACHINE</text>')
    m_note_size = _fit(machine_note, P_MACHINE_W - 44, 11.5, px_per_char=5.6)
    note_y = content_top + 38
    for j, line in enumerate(note_lines):
        svg.append(f'<text x="{machine_x+22:.0f}" y="{note_y+j*15:.0f}" class="body fmute" font-size="{m_note_size:.1f}" font-style="italic">{esc(line)}</text>')

    if storage:
        label_top = note_y + (len(note_lines) - 1) * 15 + M_BULLET_GAP
        svg.append(f'<line x1="{machine_x+22:.0f}" y1="{label_top-11:.0f}" x2="{machine_x+P_MACHINE_W-22:.0f}" y2="{label_top-11:.0f}" stroke="{NAVY}" stroke-width="1" opacity="0.25"/>')
        svg.append(f'<text x="{machine_x+22:.0f}" y="{label_top:.0f}" class="body fg" font-size="10.5" font-weight="700" letter-spacing="0.6">WHAT THE USER HAS</text>')
        sub_x = machine_x + SH_PAD
        sub_w = P_MACHINE_W - 2 * SH_PAD
        sub_y = label_top + 14
        for s, sh in zip(storage, storage_heights):
            svg.append(f'<rect x="{sub_x:.0f}" y="{sub_y:.0f}" width="{sub_w:.0f}" height="{sh:.0f}" rx="8" fill="{ICE}" stroke="{NAVY}" stroke-width="1"/>')
            svg.append(f'<use href="#ic-folder" x="{sub_x+8:.0f}" y="{sub_y+6:.0f}" width="15" height="15" color="{NAVY}"/>')
            path_size = _fit(s["path"], sub_w - 30, 12, px_per_char=6)
            svg.append(f'<text x="{sub_x+27:.0f}" y="{sub_y+17:.0f}" class="body fg" font-size="{path_size:.1f}" font-weight="700">{esc(s["path"])}</text>')
            note_size = _fit(s["note"], sub_w - 30, 9.5, px_per_char=5)
            svg.append(f'<text x="{sub_x+27:.0f}" y="{sub_y+28:.0f}" class="body fmute" font-size="{note_size:.1f}" font-style="italic">{esc(s["note"])}</text>')
            item_x = sub_x + SH_INNER_PAD
            item_w = sub_w - 2 * SH_INNER_PAD
            item_y0 = sub_y + SH_HEAD_H
            for k, it_label in enumerate(s["items"]):
                iy = item_y0 + k * (SH_ITEM_H + SH_ITEM_GAP)
                svg.append(subchip(item_x, iy, item_w, SH_ITEM_H, it_label))
            sub_y += sh + SH_GROUP_GAP

    y = table_top + max(0, (total_h - groups_h) / 2)
    for g, gh in zip(groups, heights):
        icon = _ICONS[g["kind"]]
        fill = _KIND_FILL[g["kind"]]
        svg.append(f'<rect x="{P_GROUP_X:.0f}" y="{y:.0f}" width="{P_GROUP_W:.0f}" height="{gh:.0f}" rx="12" fill="{fill}" stroke="{NAVY}" stroke-width="1.3"/>')
        svg.append(f'<use href="#{icon}" x="{P_GROUP_X+16:.0f}" y="{y+12:.0f}" width="20" height="20" color="{NAVY}"/>')
        host_size = _fit(g["host"], P_GROUP_W - 100, 15)
        svg.append(f'<text x="{P_GROUP_X+44:.0f}" y="{y+27:.0f}" class="body fg" font-size="{host_size:.1f}" font-weight="700">{esc(g["host"])}</text>')
        note_size = _fit(g["note"], P_GROUP_W - 100, 11, px_per_char=5.6)
        svg.append(f'<text x="{P_GROUP_X+44:.0f}" y="{y+41:.0f}" class="body fmute" font-size="{note_size:.1f}" font-style="italic">{esc(g["note"])}</text>')

        cy0 = y + P_HEAD_H
        chip_w = P_GROUP_W - 2 * P_PAD
        for k, it in enumerate(g["items"]):
            cy = cy0 + k * (P_CHIP_H + P_CHIP_GAP)
            svg.append(cell(P_GROUP_X + P_PAD, cy, chip_w, P_CHIP_H, it["label"], "", dark=(g["kind"] == "bundle")))
            chip_cy = cy + P_CHIP_H / 2
            ax1 = P_GROUP_X + P_GROUP_W
            ax2 = machine_x
            svg.append(f'<line x1="{ax1:.0f}" y1="{chip_cy:.0f}" x2="{ax2-4:.0f}" y2="{chip_cy:.0f}" stroke="{NAVY}" stroke-width="1.3" marker-end="url(#arrow)"/>')
            via_size = _fit(it["via"], P_ARROW_GAP - 10, 10.5, px_per_char=5.4)
            svg.append(f'<text x="{(ax1+ax2)/2:.0f}" y="{chip_cy-6:.0f}" text-anchor="middle" class="body fmute" font-size="{via_size:.1f}" font-style="italic">{esc(it["via"])}</text>')
        y += gh + P_GROUP_GAP

    if footnote:
        svg.append(f'<text x="{P_GROUP_X}" y="{table_top+total_h+34:.0f}" class="body fmute" font-size="12" font-style="italic">{esc(footnote)}</text>')

    svg.append("</svg>")
    (OUT_DIR / f"profile-pull-{slug}.svg").write_text("\n".join(svg), encoding="utf-8")
    print(f"wrote profile-pull-{slug}.svg  ({P_CANVAS_W}x{canvas_h:.0f}, {len(groups)} groups)")


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if len(cand) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines[:2]


# ---------------------------------------------------------------------------
# Data: one entry per profile. `build` (optional) is the list of rows
# staged into the bundle -- omit it (or leave empty) for profiles that
# build nothing. `pull` is always present.
# ---------------------------------------------------------------------------

PROFILES = [
    dict(
        slug="research-group",
        title="Research group",
        subtitle="Spyder, two venvs -- installs straight from the internet",
        pull=dict(
            groups=[
                group("pypi.org", "the public package index", kind="internet", items=[
                    item("Packages", "seed venv / apply"),
                    item("Spyder", "seed spyder"),
                ]),
            ],
            machine_note="each researcher's own ~/seedling",
            storage=[
                stored("python/base/", "interpreters", ["3.12"]),
                stored("python/venvs/", "one folder per venv", ["collect", "analyse"]),
                stored("extensions/spyder-config/", "the editor's local settings", ["Spyder"]),
            ],
        ),
    ),
    dict(
        slug="software-team",
        title="Software team",
        subtitle="VS Code, repos cloned -- installs straight from the internet",
        pull=dict(
            groups=[
                group("pypi.org", "package index", kind="internet", items=[
                    item("Packages", "seed apply"),
                ]),
                group("conda-forge", "via the vendored micromamba", kind="internet", items=[
                    item("conda-forge tools", "seed forge-install"),
                ]),
                group("VS Code Marketplace", "official build + 4 extensions", kind="internet", items=[
                    item("Editor", "seed apply"),
                ]),
                group("github.com", "platform.git, shared-lib.git", kind="internet", items=[
                    item("Repos", "seed repo-clone"),
                ]),
            ],
            machine_note="each engineer's own ~/seedling",
            storage=[
                stored("python/base/", "interpreters", ["3.12", "3.11"]),
                stored("python/venvs/", "one folder per venv", ["dev", "legacy"]),
                stored("extensions/vscode/", "portable VS Code + extensions", ["VS Code"]),
                stored("system/conda/", "conda-forge tool envs", ["ripgrep", "gh", "just"]),
                stored("repo/", "one folder per clone", ["platform", "shared-lib"]),
            ],
        ),
    ),
    dict(
        slug="both-editors",
        title="Both editors",
        subtitle="One shared venv -- installs straight from the internet",
        pull=dict(
            groups=[
                group("pypi.org", "package index", kind="internet", items=[
                    item("Packages", "seed apply"),
                    item("Spyder", "seed apply"),
                ]),
                group("VS Code Marketplace", "official build", kind="internet", items=[
                    item("Editor", "seed apply"),
                ]),
            ],
            machine_note="one shared venv, both editors installed",
            storage=[
                stored("python/base/", "interpreters", ["3.12"]),
                stored("python/venvs/", "one folder per venv", ["work"]),
                stored("extensions/", "both editors, side by side", ["VS Code", "Spyder"]),
            ],
        ),
    ),
    dict(
        slug="classroom",
        title="Classroom",
        subtitle="Pinned, reproducible -- installs straight from the internet",
        pull=dict(
            groups=[
                group("pypi.org", "package index", kind="internet", items=[
                    item("Packages (pinned)", "seed apply"),
                    item("Spyder", "seed spyder"),
                ]),
            ],
            machine_note="every lab machine, identical pins",
            storage=[
                stored("python/base/", "interpreters", ["3.12"]),
                stored("python/venvs/", "one folder per venv", ["phys201"]),
                stored("extensions/spyder-config/", "the editor's local settings", ["Spyder"]),
            ],
            footnote="If the lab machines have no internet, build a bundle instead -- see Air-gapped (everything) and take only the pieces you need.",
        ),
    ),
    dict(
        slug="internal-mirrors",
        title="Internal mirrors",
        subtitle="No bundle needed -- the mirrors are reachable",
        pull=dict(
            groups=[
                group("artifactory.corp.example", "one Artifactory host, three proxies", kind="internal", items=[
                    item("Packages", "seed install"),
                    item("Spyder", "seed apply"),
                    item("conda-forge tools", "seed forge-install"),
                    item("Interpreters", "seed python"),
                ]),
                group("gitlab.corp.example", "your internal git host", kind="internal", items=[
                    item("seedling itself", "seed update-commands"),
                    item("Repos", "seed repo-clone"),
                ]),
            ],
            machine_note="every workstation, live over HTTPS each time",
            storage=[
                stored("python/base/", "interpreters", ["3.12"]),
                stored("python/venvs/", "one folder per venv", ["work"]),
                stored("extensions/spyder-config/", "the editor's local settings", ["Spyder"]),
                stored("system/conda/", "conda-forge tool envs", ["ripgrep", "pandoc"]),
                stored("repo/", "one folder per clone", ["toolkit"]),
            ],
        ),
    ),
    dict(
        slug="internal-pypi-only",
        title="Internal PyPI only",
        subtitle="Partial bundle -- everything except the wheels",
        build=[
            brow("uv", "astral.sh", "the binary itself",
                "vendor/uv/", "staged into the bundle"),
            brow("Interpreters", "python-build-standalone", "no internal PBS mirror",
                "python-builds/", "staged into the bundle"),
            brow("conda-forge tools", "conda-forge", "no internal conda mirror",
                "conda-channel/", "+ vendored micromamba"),
            brow("Editor", "VS Code Marketplace", "Marketplace is blocked here",
                "vendor/vscode/", "staged into the bundle"),
            brow("Git", "git-for-windows", "no git host to clone from either",
                "vendor/git/", "staged with --mingit"),
            brow("CA cert", "you supply it", "the proxy re-signs HTTPS",
                "vendor/certs/", "staged into the bundle"),
        ],
        pull=dict(
            groups=[
                group("artifactory.corp.example", "the one live service on this network", kind="internal", items=[
                    item("Packages", "seed install"),
                    item("Spyder", "seed apply"),
                ]),
                group("S:\\seedling (the bundle)", "everything else, copied once", kind="bundle", items=[
                    item("uv", "system/bin/"),
                    item("Interpreters", "seed python"),
                    item("conda-forge tools", "seed forge-install"),
                    item("Editor", "extensions/vscode/"),
                    item("Git", "extensions/git/"),
                    item("CA cert", "system/certs/"),
                ]),
            ],
            machine_note="each user's own ~/seedling, off the share",
            storage=[
                stored("python/base/", "interpreters", ["3.12"]),
                stored("python/venvs/", "one folder per venv", ["work"]),
                stored("extensions/", "both editors, side by side", ["VS Code", "Spyder"]),
                stored("system/conda/", "conda-forge tool envs", ["ripgrep", "pandoc"]),
            ],
        ),
    ),
    dict(
        slug="air-gapped-vscodium",
        title="Air-gapped (VSCodium)",
        subtitle="No redistribution rights -- built once, carried in",
        build=[
            brow("Packages", "pypi.org", "every venv package",
                "wheels/", "staged into the bundle"),
            brow("uv", "astral.sh", "the binary itself",
                "vendor/uv/", "staged into the bundle"),
            brow("Interpreters", "python-build-standalone", "the interpreter archive(s)",
                "python-builds/", "staged into the bundle"),
            brow("conda-forge tools", "conda-forge", "ripgrep, pandoc",
                "conda-channel/", "+ vendored micromamba"),
            brow("Editor", "VSCodium + Open VSX", "MIT-licensed, no rights needed",
                "vendor/vscode/", "staged into the bundle"),
            brow("Git", "git-for-windows", "optional, --mingit",
                "vendor/git/", "staged if requested"),
        ],
        pull=dict(
            groups=[
                group("the share (the bundle)", "offline-bundle/, copied once", kind="bundle", items=[
                    item("Packages", "seed install"),
                    item("uv", "system/bin/"),
                    item("Interpreters", "seed python"),
                    item("conda-forge tools", "seed forge-install"),
                    item("Editor (VSCodium)", "extensions/vscode/"),
                    item("Git (optional)", "extensions/git/"),
                ]),
            ],
            machine_note="zero internet, every machine on the target network",
            storage=[
                stored("python/base/", "interpreters", ["3.12"]),
                stored("python/venvs/", "one folder per venv", ["work"]),
                stored("extensions/vscode/", "portable VSCodium + extensions", ["VSCodium"]),
                stored("system/conda/", "conda-forge tool envs", ["ripgrep", "pandoc"]),
            ],
            footnote="An optional CA cert follows the same path as Git above -- staged if a TLS-inspecting proxy needs one.",
        ),
    ),
    dict(
        slug="air-gapped-vs-code",
        title="Air-gapped (VS Code)",
        subtitle="Keeps Pylance -- built once, carried in",
        build=[
            brow("Packages", "pypi.org", "every venv package",
                "wheels/", "staged into the bundle"),
            brow("uv", "astral.sh", "the binary itself",
                "vendor/uv/", "staged into the bundle"),
            brow("Interpreters", "python-build-standalone", "the interpreter archive(s)",
                "python-builds/", "staged into the bundle"),
            brow("conda-forge tools", "conda-forge", "ripgrep, pandoc",
                "conda-channel/", "+ vendored micromamba"),
            brow("Editor", "VS Code Marketplace", "official build -- rights held",
                "vendor/vscode/", "staged, marked RESTRICTED"),
            brow("Git", "git-for-windows", "optional, --mingit",
                "vendor/git/", "staged if requested"),
        ],
        pull=dict(
            groups=[
                group("the share (the bundle)", "offline-bundle/, copied once", kind="bundle", items=[
                    item("Packages", "seed install"),
                    item("uv", "system/bin/"),
                    item("Interpreters", "seed python"),
                    item("conda-forge tools", "seed forge-install"),
                    item("Editor (VS Code)", "extensions/vscode/ -- keeps Pylance"),
                    item("Git (optional)", "extensions/git/"),
                ]),
            ],
            machine_note="zero internet, every machine on the target network",
            storage=[
                stored("python/base/", "interpreters", ["3.12"]),
                stored("python/venvs/", "one folder per venv", ["work"]),
                stored("extensions/vscode/", "portable VS Code -- keeps Pylance", ["VS Code"]),
                stored("system/conda/", "conda-forge tool envs", ["ripgrep", "pandoc"]),
            ],
            footnote="An optional CA cert follows the same path as Git above -- staged if a TLS-inspecting proxy needs one.",
        ),
    ),
    dict(
        slug="air-gapped-everything",
        title="Air-gapped (everything)",
        subtitle="Every capability at once -- the maximal case",
        build=[
            brow("Packages + Spyder", "pypi.org", "every venv package, per interpreter",
                "wheels/", "staged into the bundle"),
            brow("uv", "astral.sh", "the binary itself",
                "vendor/uv/", "staged into the bundle"),
            brow("Interpreters", "python-build-standalone", "3.12 and 3.11",
                "python-builds/", "staged into the bundle"),
            brow("conda-forge tools", "conda-forge", "ripgrep, pandoc, gh",
                "conda-channel/", "+ vendored micromamba"),
            brow("Editor", "VS Code Marketplace", "official build, Pylance included",
                "vendor/vscode/", "staged, marked RESTRICTED"),
            brow("Git", "git-for-windows", "--mingit",
                "vendor/git/", "staged into the bundle"),
            brow("CA cert", "you supply it", "proxy re-signs HTTPS here",
                "vendor/certs/", "staged into the bundle"),
        ],
        pull=dict(
            groups=[
                group("S:\\seedling (the bundle)", "one shared bundle, staged once", kind="bundle", items=[
                    item("Packages + Spyder", "seed install / apply"),
                    item("uv", "system/bin/"),
                    item("Interpreters x2", "seed python 3.12 / 3.11"),
                    item("conda-forge tools", "seed forge-install"),
                    item("Editor", "extensions/vscode/"),
                    item("Git", "extensions/git/"),
                    item("CA cert", "system/certs/"),
                ]),
                group("git.corp.example", "reached only after install", kind="internal", items=[
                    item("Repos", "seed repo-clone"),
                ]),
            ],
            machine_note="S:\\users\\{user}\\seedling -- a private folder per person",
            storage=[
                stored("python/base/", "interpreters", ["3.12", "3.11"]),
                stored("python/venvs/", "one folder per venv", ["dev", "analysis", "legacy"]),
                stored("extensions/", "both editors, side by side", ["VS Code", "Spyder"]),
                stored("system/conda/", "conda-forge tool envs", ["ripgrep", "pandoc", "gh"]),
                stored("repo/", "one folder per clone", ["toolkit", "analysis-lib"]),
            ],
            footnote="Everything in the bundle box above lands under S:\\users\\{user}\\seedling -- one shared bundle, a private folder per person.",
        ),
    ),
    dict(
        slug="just-python",
        title="Just Python",
        subtitle="Interpreters and venvs only -- installs straight from the internet",
        pull=dict(
            groups=[
                group("pypi.org", "package index", kind="internet", items=[
                    item("Packages", "seed venv"),
                ]),
            ],
            machine_note="the one venv, straight from the internet",
            storage=[
                stored("python/base/", "interpreters", ["3.13"]),
                stored("python/venvs/", "one folder per venv", ["work"]),
            ],
        ),
    ),
]


def main() -> None:
    for p in PROFILES:
        if p.get("build"):
            build_part1(p["slug"], p["title"], p["subtitle"], p["build"])
        pull = p["pull"]
        build_part2(p["slug"], p["title"], p["subtitle"], pull["groups"],
                    pull["machine_note"], pull.get("storage"), pull.get("footnote"))


if __name__ == "__main__":
    main()
