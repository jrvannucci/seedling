#!/usr/bin/env python3
"""Generate _static/command-explorer.html -- the command reference you can
actually navigate.

It replaces command-map.svg, which put all 59 commands on one page -- the
only way a static diagram can show the whole surface, and exactly why it was
hard to read: everything at one size, nothing collapsible. Same content,
interactively -- families as sections, one row per command, click a row to
expand its full documentation.

The content comes from the two places that already own it, so this page can't
drift from them:

  * FAMILIES in diagrams/generate_family_commands.py -- the family/section
    structure and each command's one-line summary
  * docs/commands/<slug>.md -- the full per-command section, matched on the
    command NAME (the signatures differ in detail between the two, and the
    docs' fuller one is the one worth showing)

Deliberately single-column: the point is scanning a list and opening one
thing, not comparing two columns.

Emitted as a FRAGMENT (scoped styles + markup + script, no <html>), which
docs/COMMANDS.md pulls in with a `raw` directive. It used to be a standalone
page under _static/, which meant clicking through to it left the docs site
behind -- no sidebar, no search, no breadcrumbs. Embedded, it inherits all of
that, and the theme owns the page chrome while this owns only the widget.

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

OUT = HERE / "_include" / "command-explorer.html"

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
/* Scoped to .cmdx. This is embedded in a full docs page, so it styles the
   widget and nothing else -- no body, no :root, no dark-mode block (the
   theme is light-only, and a widget that went dark on its own would be the
   only dark thing on the page). */
.cmdx {{
  --cx-ink: #14261C;
  --cx-soft: {SLATE};
  --cx-line: #D4E6DA;
  --cx-accent: {NAVY};
  --cx-raised: {ICE};
  --cx-danger: {DANGER};
  --cx-danger-tint: #F7ECE9;
  margin: 1.5rem 0 0;
}}
.cmdx .tools {{
  display: flex;
  gap: .6rem;
  flex-wrap: wrap;
  position: sticky;
  top: 0;
  z-index: 2;
  padding: .6rem 0;
  background: #fff;
  border-bottom: 1px solid var(--cx-line);
}}
.cmdx #cmdx-q {{
  flex: 1 1 18rem;
  padding: .5rem .7rem;
  font: inherit;
  color: var(--cx-ink);
  background: #fff;
  border: 1px solid var(--cx-line);
  border-radius: 5px;
}}
.cmdx #cmdx-q:focus-visible,
.cmdx #cmdx-expand:focus-visible,
.cmdx summary:focus-visible {{
  outline: 3px solid #95D5B2;
  outline-offset: 1px;
}}
.cmdx #cmdx-expand {{
  padding: .5rem .8rem;
  font: inherit;
  color: var(--cx-accent);
  background: var(--cx-raised);
  border: 1px solid var(--cx-line);
  border-radius: 5px;
  cursor: pointer;
}}
.cmdx #cmdx-expand:hover {{ background: #DCEDE2; }}
.cmdx .count {{
  margin: .6rem 0 1.2rem;
  font-size: .85rem;
  color: var(--cx-soft);
}}
.cmdx .family {{ margin: 0 0 2rem; }}
.cmdx .family h2 {{
  margin: 0 0 .2rem;
  padding: 0;
  font-size: 1.15rem;
  font-family: Georgia, "Times New Roman", serif;
  color: var(--cx-accent);
  border: none;
}}
.cmdx .family .sub {{
  margin: 0 0 .8rem;
  font-size: .88rem;
  color: var(--cx-soft);
}}
.cmdx .section-label {{
  margin: 1rem 0 .4rem;
  font-size: .72rem;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--cx-soft);
}}
.cmdx .section-label.danger {{ color: var(--cx-danger); }}
.cmdx .cmds {{ display: flex; flex-direction: column; gap: .3rem; }}
.cmdx details {{
  border: 1px solid var(--cx-line);
  border-left: 3px solid var(--cx-accent);
  border-radius: 4px;
  background: #fff;
}}
.cmdx details.danger {{
  border-left-color: var(--cx-danger);
  background: var(--cx-danger-tint);
}}
.cmdx summary {{
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: .1rem 1rem;
  padding: .55rem .8rem;
  cursor: pointer;
  list-style: none;
}}
.cmdx summary::-webkit-details-marker {{ display: none; }}
.cmdx summary:hover {{ background: #F4FAF6; }}
.cmdx details.danger summary:hover {{ background: #F2E2DE; }}
.cmdx .sig {{
  font-family: Consolas, "SF Mono", Monaco, monospace;
  font-size: .88rem;
  font-weight: 700;
  color: var(--cx-accent);
}}
.cmdx details.danger .sig {{ color: var(--cx-danger); }}
.cmdx .gist {{ font-size: .86rem; color: var(--cx-soft); }}
.cmdx .body {{
  padding: .2rem .9rem .9rem;
  border-top: 1px solid var(--cx-line);
  font-size: .9rem;
}}
.cmdx .body > *:first-child {{ margin-top: .7rem; }}
.cmdx .body pre {{
  padding: .6rem .8rem;
  overflow-x: auto;
  background: #F4FAF6;
  border: 1px solid var(--cx-line);
  border-radius: 4px;
  font-size: .84rem;
}}
.cmdx .body code {{
  font-family: Consolas, "SF Mono", Monaco, monospace;
  font-size: .86em;
}}
.cmdx .body pre code {{ background: none; border: none; padding: 0; }}
.cmdx .body blockquote {{
  margin: .7rem 0;
  padding: .1rem 0 .1rem .9rem;
  border-left: 3px solid var(--cx-line);
  color: var(--cx-soft);
}}
.cmdx .scroll {{ overflow-x: auto; }}
.cmdx .body table {{ border-collapse: collapse; font-size: .86rem; }}
.cmdx .body th, .cmdx .body td {{
  padding: .35rem .6rem;
  border: 1px solid var(--cx-line);
  text-align: left;
  vertical-align: top;
}}
.cmdx .body th {{ background: var(--cx-raised); }}
.cmdx .empty, .cmdx .cmdx-foot {{
  font-size: .85rem;
  color: var(--cx-soft);
}}
.cmdx .cmdx-foot {{
  margin-top: 2rem;
  padding-top: .8rem;
  border-top: 1px solid var(--cx-line);
}}
"""

JS = """
(function () {
  // Scoped to .cmdx: this runs inside a full docs page now, so a bare
  // querySelectorAll would reach into the theme's own markup.
  const root = document.querySelector('.cmdx');
  if (!root) return;
  const q = root.querySelector('#cmdx-q');
  const rows = [...root.querySelectorAll('details[data-hay]')];
  const count = root.querySelector('#cmdx-count');
  const empty = root.querySelector('#cmdx-empty');

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
    for (const fam of root.querySelectorAll('.family')) {
      const any = [...fam.querySelectorAll('details')].some(d => !d.hidden);
      fam.hidden = !any;
    }
    for (const label of root.querySelectorAll('.section-label')) {
      const group = label.nextElementSibling;
      label.hidden = group ? ![...group.querySelectorAll('details')]
        .some(d => !d.hidden) : false;
    }
    count.textContent = term
      ? shown + (shown === 1 ? ' command matches' : ' commands match')
      : rows.length + ' commands across ' +
        root.querySelectorAll('.family').length + ' families';
    empty.hidden = shown !== 0;
  }

  q.addEventListener('input', apply);
  root.querySelector('#cmdx-expand').addEventListener('click', () => {
    const anyClosed = rows.some(r => !r.hidden && !r.open);
    rows.filter(r => !r.hidden).forEach(r => { r.open = anyClosed; });
  });
  document.addEventListener('keydown', e => {
    const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
    if (e.key === '/' && !typing) { e.preventDefault(); q.focus(); }
    if (e.key === 'Escape' && document.activeElement === q) {
      q.value = ''; apply();
    }
  });
  apply();
})();
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

    return f"""<style>{CSS}</style>
<div class="cmdx">
<div class="tools">
  <input type="search" id="cmdx-q"
         placeholder="Filter commands &mdash; press / to focus"
         aria-label="Filter commands" autocomplete="off">
  <button id="cmdx-expand" type="button">Expand / collapse shown</button>
</div>
<p class="count" id="cmdx-count"></p>

{"".join(families_html)}

<p class="empty" id="cmdx-empty" hidden>Nothing matches that.</p>

<p class="cmdx-foot">{total} commands. Run <code>seed help</code> for the same
list in your terminal.</p>
</div>
<script>{JS}</script>
"""


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
