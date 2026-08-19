#!/usr/bin/env python3
"""Generate _static/command-explorer.html -- the command reference you can
actually navigate.

command-map.svg puts all 59 commands on one page, which is the only way a
static diagram can show the whole surface, and is exactly why it's hard to
read: everything is at the same size and nothing collapses. This is the same
content as an interactive page -- families as sections, one row per command,
click a row to expand its full documentation.

The content comes from the two places that already own it, so this page can't
drift from them:

  * FAMILIES in diagrams/generate_family_commands.py -- the family/section
    structure and each command's one-line summary
  * docs/commands/<slug>.md -- the full per-command section, matched on the
    command NAME (the signatures differ in detail between the two, and the
    docs' fuller one is the one worth showing)

Deliberately single-column: the point is scanning a list and opening one
thing, not comparing two columns.

Run:  python docs/generate_command_explorer.py
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "diagrams"))

from generate_family_commands import FAMILIES  # noqa: E402

OUT = HERE / "_static" / "command-explorer.html"

# seedling's own diagram palette (diagrams/generate_profile_flows.py), so the
# explorer and the SVGs it stands in for read as one set rather than two
# unrelated designs.
NAVY = "#1B4332"
ICE = "#E9F5EC"
SLATE = "#52796F"
DANGER = "#9C4A3C"


# ---------------------------------------------------------------------------
# pulling the long-form docs
# ---------------------------------------------------------------------------

def _command_name(signature: str) -> str:
    """'seed venv <name> [--python tag]' -> 'venv'. The stable key between
    FAMILIES and the docs, whose signatures spell out more flags."""
    parts = signature.split()
    return parts[1] if len(parts) > 1 else signature


def _doc_sections(slug: str) -> dict[str, tuple[str, str]]:
    """{command name: (full signature, markdown body)} for one family page."""
    md = HERE / "commands" / f"{slug}.md"
    if not md.is_file():
        return {}
    text = md.read_text(encoding="utf-8")
    out: dict[str, tuple[str, str]] = {}
    parts = re.split(r"^## `([^`]+)`\s*$", text, flags=re.M)
    # parts = [preamble, heading1, body1, heading2, body2, ...]
    for heading, body in zip(parts[1::2], parts[2::2]):
        out[_command_name(heading)] = (heading, body.strip())
    return out


# ---------------------------------------------------------------------------
# the smallest markdown subset the command pages actually use
# ---------------------------------------------------------------------------

def _inline(text: str) -> str:
    """Escape, then re-introduce the inline marks the pages use. Escaping
    first is what keeps `<name>` in a signature from becoming a tag."""
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    # [label](target) -> label; the targets are relative doc paths that mean
    # nothing from a standalone page, and a dead link is worse than plain text.
    out = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", out)
    return out


def _render(body: str) -> str:
    """Markdown -> HTML for the fragment shapes these pages use: paragraphs,
    bullet lists, fenced code, block quotes and tables."""
    lines = body.split("\n")
    out: list[str] = []
    para: list[str] = []
    bullets: list[str] = []
    code: list[str] | None = None
    table: list[str] = []

    def flush_para():
        if para:
            out.append("<p>" + _inline(" ".join(para).strip()) + "</p>")
            para.clear()

    def flush_bullets():
        if bullets:
            out.append("<ul>" + "".join(f"<li>{_inline(b)}</li>"
                                        for b in bullets) + "</ul>")
            bullets.clear()

    def flush_table():
        if not table:
            return
        rows = [r for r in table if not re.match(r"^\s*\|[\s|:-]+\|\s*$", r)]
        cells = [[c.strip() for c in r.strip().strip("|").split("|")]
                 for r in rows]
        head, *rest = cells
        html_rows = ["<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head)
                     + "</tr>"]
        html_rows += ["<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r)
                      + "</tr>" for r in rest]
        out.append('<div class="scroll"><table>' + "".join(html_rows)
                   + "</table></div>")
        table.clear()

    for line in lines:
        if line.startswith("```"):
            if code is None:
                flush_para()
                flush_bullets()
                flush_table()
                code = []
            else:
                out.append("<pre><code>"
                           + html.escape("\n".join(code)) + "</code></pre>")
                code = None
            continue
        if code is not None:
            code.append(line)
            continue

        stripped = line.strip()
        if stripped.startswith("|"):
            flush_para()
            flush_bullets()
            table.append(line)
            continue
        flush_table()

        if not stripped:
            flush_para()
            flush_bullets()
            continue
        if stripped.startswith("> "):
            flush_para()
            flush_bullets()
            out.append('<blockquote>' + _inline(stripped[2:]) + "</blockquote>")
            continue
        m = re.match(r"^[-*]\s+(.*)$", stripped)
        if m:
            flush_para()
            bullets.append(m.group(1))
            continue
        if bullets and line.startswith(("  ", "\t")):
            bullets[-1] += " " + stripped
            continue
        para.append(stripped)

    flush_para()
    flush_bullets()
    flush_table()
    if code:
        out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
    return "".join(out)


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------

CSS = f"""
:root {{
  --ground: #FFFFFF;
  --surface: #FBFDFB;
  --raised: {ICE};
  --ink: #14261C;
  --ink-soft: {SLATE};
  --line: #D4E6DA;
  --accent: {NAVY};
  --danger: {DANGER};
  --danger-tint: #F7ECE9;
  --focus: #2D6A4F;
  --shadow: 0 1px 2px rgba(20, 38, 28, .06);
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --ground: #0E1A13;
    --surface: #12211A;
    --raised: #162A20;
    --ink: #E6F2EA;
    --ink-soft: #9DBCAA;
    --line: #243B2E;
    --accent: #95D5B2;
    --danger: #E0846F;
    --danger-tint: #2A1A16;
    --focus: #95D5B2;
    --shadow: none;
  }}
}}
:root[data-theme="dark"] {{
  --ground: #0E1A13;
  --surface: #12211A;
  --raised: #162A20;
  --ink: #E6F2EA;
  --ink-soft: #9DBCAA;
  --line: #243B2E;
  --accent: #95D5B2;
  --danger: #E0846F;
  --danger-tint: #2A1A16;
  --focus: #95D5B2;
  --shadow: none;
}}

* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--ground);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.6;
}}
.wrap {{ max-width: 860px; margin: 0 auto; padding: 40px 20px 96px; }}

header h1 {{
  font-family: Georgia, "Times New Roman", serif;
  font-size: 30px; font-weight: 700; margin: 0 0 6px;
  text-wrap: balance; color: var(--ink);
}}
header p {{ margin: 0; color: var(--ink-soft); font-style: italic; }}

.tools {{
  position: sticky; top: 0; z-index: 5;
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  margin: 26px 0 8px; padding: 12px 0;
  background: var(--ground); border-bottom: 1px solid var(--line);
}}
input[type="search"] {{
  flex: 1 1 260px; min-width: 0;
  padding: 9px 12px; font: inherit; color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--line); border-radius: 7px;
}}
input[type="search"]::placeholder {{ color: var(--ink-soft); }}
button {{
  font: inherit; color: var(--ink); cursor: pointer;
  background: var(--surface); border: 1px solid var(--line);
  border-radius: 7px; padding: 9px 13px;
}}
button:hover {{ background: var(--raised); }}
:is(a, button, summary, input):focus-visible {{
  outline: 2px solid var(--focus); outline-offset: 2px; border-radius: 4px;
}}
.count {{ color: var(--ink-soft); font-size: 13px; margin: 0 0 22px; }}

.family {{ margin: 0 0 34px; }}
.family > h2 {{
  font-family: Georgia, "Times New Roman", serif;
  font-size: 19px; margin: 0 0 2px; color: var(--ink);
}}
.family > .sub {{ margin: 0 0 14px; color: var(--ink-soft); font-size: 13.5px; }}
.section-label {{
  font-size: 11px; letter-spacing: .09em; text-transform: uppercase;
  color: var(--ink-soft); margin: 18px 0 8px;
}}
.section-label.danger {{ color: var(--danger); }}

.cmds {{ display: flex; flex-direction: column; gap: 6px; }}
details {{
  background: var(--surface);
  border: 1px solid var(--line);
  border-left: 3px solid transparent;
  border-radius: 8px; box-shadow: var(--shadow);
}}
details.danger {{ border-left-color: var(--danger); background: var(--danger-tint); }}
details[open] {{ background: var(--raised); }}
details[open].danger {{ background: var(--danger-tint); }}
summary {{
  cursor: pointer; list-style: none; padding: 11px 14px;
  display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px;
}}
summary::-webkit-details-marker {{ display: none; }}
summary::before {{
  content: "+"; font-family: Consolas, "SF Mono", Monaco, monospace;
  color: var(--ink-soft); width: 12px; flex: none;
}}
details[open] summary::before {{ content: "\\2212"; }}
.sig {{
  font-family: Consolas, "SF Mono", Monaco, "Courier New", monospace;
  font-size: 13.5px; font-weight: 700; color: var(--ink);
}}
details.danger .sig {{ color: var(--danger); }}
.gist {{ color: var(--ink-soft); font-size: 13.5px; }}
.body {{ padding: 2px 16px 16px 40px; border-top: 1px solid var(--line); }}
.body > :first-child {{ margin-top: 12px; }}
.body p {{ margin: 0 0 10px; }}
.body ul {{ margin: 0 0 12px; padding-left: 20px; }}
.body li {{ margin: 0 0 5px; }}
.body blockquote {{
  margin: 0 0 12px; padding: 8px 12px;
  border-left: 3px solid var(--line); color: var(--ink-soft);
}}
code {{
  font-family: Consolas, "SF Mono", Monaco, "Courier New", monospace;
  font-size: .9em; background: var(--raised);
  padding: 1px 5px; border-radius: 4px;
}}
pre {{
  margin: 0 0 12px; padding: 11px 13px; overflow-x: auto;
  background: var(--raised); border: 1px solid var(--line); border-radius: 7px;
}}
pre code {{ background: none; padding: 0; }}
.scroll {{ overflow-x: auto; margin: 0 0 12px; }}
table {{ border-collapse: collapse; font-size: 13.5px; width: 100%; }}
th, td {{
  text-align: left; padding: 6px 10px;
  border-bottom: 1px solid var(--line); vertical-align: top;
}}
th {{ color: var(--ink-soft); font-weight: 600; }}
.empty {{ color: var(--ink-soft); font-style: italic; padding: 30px 0; }}
footer {{
  margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--line);
  color: var(--ink-soft); font-size: 13px;
}}
@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
}}
"""

JS = """
const q = document.getElementById('q');
const rows = [...document.querySelectorAll('details[data-hay]')];
const count = document.getElementById('count');
const empty = document.getElementById('empty');

function apply() {
  const term = q.value.trim().toLowerCase();
  let shown = 0;
  for (const row of rows) {
    const hit = !term || row.dataset.hay.includes(term);
    row.hidden = !hit;
    if (hit) shown++;
    if (term && hit && term.length > 2) row.open = true;
    if (!term) row.open = false;
  }
  for (const fam of document.querySelectorAll('.family')) {
    const any = [...fam.querySelectorAll('details')].some(d => !d.hidden);
    fam.hidden = !any;
  }
  for (const label of document.querySelectorAll('.section-label')) {
    const group = label.nextElementSibling;
    label.hidden = group ? ![...group.querySelectorAll('details')]
      .some(d => !d.hidden) : false;
  }
  count.textContent = term
    ? shown + (shown === 1 ? ' command matches' : ' commands match')
    : rows.length + ' commands across ' +
      document.querySelectorAll('.family').length + ' families';
  empty.hidden = shown !== 0;
}

q.addEventListener('input', apply);
document.getElementById('expand').addEventListener('click', () => {
  const anyClosed = rows.some(r => !r.hidden && !r.open);
  rows.filter(r => !r.hidden).forEach(r => { r.open = anyClosed; });
});
document.addEventListener('keydown', e => {
  if (e.key === '/' && document.activeElement !== q) { e.preventDefault(); q.focus(); }
  if (e.key === 'Escape' && document.activeElement === q) { q.value = ''; apply(); }
});
apply();
"""


def build() -> str:
    families_html: list[str] = []
    total = 0

    for slug, title, subtitle, *rest in FAMILIES:
        sections = rest[-1]
        docs = _doc_sections(slug)
        blocks: list[str] = []
        for label, items in sections:
            if label:
                cls = "section-label danger" if "danger" in label.lower() else "section-label"
                blocks.append(f'<p class="{cls}">{html.escape(label)}</p>')
            rows: list[str] = []
            for signature, desc_lines, danger, *_ in items:
                name = _command_name(signature)
                full_sig, body = docs.get(name, (signature, ""))
                gist = " ".join(desc_lines)
                detail = _render(body) if body else (
                    "<p>" + _inline(gist) + "</p>")
                hay = html.escape(
                    f"{full_sig} {gist} {re.sub(r'<[^>]+>', ' ', detail)}"
                    .lower().replace('"', ""))
                rows.append(
                    f'<details data-hay="{hay}"'
                    f'{" class=\"danger\"" if danger else ""}>'
                    f'<summary><span class="sig">{html.escape(full_sig)}</span>'
                    f'<span class="gist">{_inline(gist)}</span></summary>'
                    f'<div class="body">{detail}</div></details>')
                total += 1
            blocks.append('<div class="cmds">' + "".join(rows) + "</div>")

        families_html.append(
            f'<section class="family" id="{html.escape(slug)}">'
            f'<h2>{html.escape(title)}</h2>'
            f'<p class="sub">{html.escape(subtitle)}</p>'
            + "".join(blocks) + "</section>")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>seedling commands</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>seedling commands</h1>
  <p>Every command, grouped the way you'd look for one. Click to open.</p>
</header>

<div class="tools">
  <input type="search" id="q" placeholder="Filter commands &mdash; press / to focus"
         aria-label="Filter commands" autocomplete="off">
  <button id="expand" type="button">Expand / collapse shown</button>
</div>
<p class="count" id="count"></p>

{"".join(families_html)}

<p class="empty" id="empty" hidden>Nothing matches that.</p>

<footer>Generated from the command reference &mdash; {total} commands.
Run <code>seed help</code> for the same list in your terminal.</footer>
</div>
<script>{JS}</script>
</body>
</html>
"""


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
