"""
`seed logs-viewer` -- render the daily command logs as a single, self-contained
HTML page and open it in the browser.

The logs are the plain-text daily files runlog.py writes under
~/seedling/system/logs/ (seed-YYYY-MM-DD.log), each a sequence of blocks:

    === [2026-07-05 14:30:22] seed venv dev
    <everything the command printed, ANSI stripped>
    === [14:30:23] exit code 0

This parses those blocks into structured entries, embeds them as JSON in a
standalone HTML file (no CDN, no network -- it works on a closed network like
the rest of seedling), and opens it. The page has search, a failures-only
filter, and collapsible per-command output; failed commands auto-expand.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

from .. import colors, paths

# A block starts with a full date+time stamp; the matching exit line carries a
# time-only stamp. The two stamp shapes are what tell start lines apart from
# exit lines (and from any stray "=== " a command might print).
_START_RE = re.compile(r"^=== \[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (.*)$")
_EXIT_RE = re.compile(r"^=== \[(\d{2}:\d{2}:\d{2})\] exit code (-?\d+)$")
# install-YYYYMMDD-HHMMSS.log -- one file per bootstrap run (install.sh /
# install.ps1). install.sh writes the same block format as the daily logs;
# install.ps1 (Start-Transcript) writes a raw transcript, handled as one entry.
_INSTALL_RE = re.compile(r"^install-(\d{8})-(\d{6})\.log$")

# The logs are written plain (runlog and install.sh both strip ANSI at the
# source, so they can be shipped to a server as-is), but strip again at parse
# time as defense-in-depth -- e.g. a log written by an older/newer seedling
# or a tool that colored despite the pipe still displays clean.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

VIEWER_FILENAME = "logs-viewer.html"


def _log_files(days: int | None) -> list[Path]:
    """Daily log files, newest first, optionally limited to the last `days`."""
    if not paths.LOGS_DIR.exists():
        return []
    files = []
    cutoff = None
    if days is not None:
        cutoff = _dt.date.today() - _dt.timedelta(days=days - 1)
    for f in paths.LOGS_DIR.glob("seed-*.log"):
        stamp = f.name[len("seed-"): -len(".log")]
        try:
            day = _dt.date.fromisoformat(stamp)
        except ValueError:
            continue
        if cutoff is None or day >= cutoff:
            files.append(f)
    return sorted(files, reverse=True)


def _read_log_text(path: Path) -> str:
    """Read a log file honoring a BOM. The daily logs and install.sh write
    UTF-8; install.ps1 captures via Tee-Object, which on Windows PowerShell
    5.1 writes UTF-16LE with a BOM -- detect it so both decode correctly."""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig", errors="replace")
    return raw.decode("utf-8", errors="replace")


def _parse_file(path: Path, kind: str = "command") -> list[dict]:
    """Parse one block-format log (daily seed log, or an install.sh log) into
    a list of entries, each tagged with `kind` ('command' or 'install')."""
    text = _read_log_text(path)

    entries: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        start = _START_RE.match(line)
        if start:
            # A previous entry with no exit line (e.g. a hard-killed process)
            # is flushed as-is before the new one begins.
            if current is not None:
                entries.append(_finalize(current, kind))
            current = {"ts": start.group(1), "cmd": start.group(2),
                       "out": [], "exit": None, "exit_time": None}
            continue
        exit_match = _EXIT_RE.match(line)
        if exit_match and current is not None and current["exit"] is None:
            current["exit"] = int(exit_match.group(2))
            current["exit_time"] = exit_match.group(1)
            entries.append(_finalize(current, kind))
            current = None
            continue
        if current is not None:
            current["out"].append(line)
    if current is not None:
        entries.append(_finalize(current, kind))
    return entries


def _duration(start_ts: str, exit_time: str | None) -> int | None:
    """Seconds between a command's start stamp ('YYYY-MM-DD HH:MM:SS') and its
    exit stamp ('HH:MM:SS'). None when there's no exit line, or the clock
    appears to have gone backwards (e.g. the run crossed midnight)."""
    if not exit_time:
        return None
    try:
        start = _dt.datetime.strptime(start_ts, "%Y-%m-%d %H:%M:%S")
        h, m, s = (int(x) for x in exit_time.split(":"))
        end = start.replace(hour=h, minute=m, second=s)
    except (ValueError, TypeError):
        return None
    secs = (end - start).total_seconds()
    return int(secs) if secs >= 0 else None


def _finalize(entry: dict, kind: str = "command") -> dict:
    out = _ANSI_RE.sub("", "\n".join(entry["out"])).strip("\n")
    return {"ts": entry["ts"], "cmd": entry["cmd"], "output": out,
            "exit": entry["exit"], "kind": kind,
            "dur": _duration(entry["ts"], entry.get("exit_time"))}


def _install_files(days: int | None) -> list[Path]:
    """install-*.log files, newest first, optionally limited to the last
    `days` (dated from the filename)."""
    if not paths.LOGS_DIR.exists():
        return []
    cutoff = None
    if days is not None:
        cutoff = _dt.date.today() - _dt.timedelta(days=days - 1)
    files = []
    for f in paths.LOGS_DIR.glob("install-*.log"):
        m = _INSTALL_RE.match(f.name)
        if not m:
            continue
        try:
            day = _dt.datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if cutoff is None or day >= cutoff:
            files.append(f)
    return sorted(files, reverse=True)


# install.ps1 prints this marker right before stopping its transcript; it's
# how a raw-transcript install log communicates its outcome to the viewer.
_PS_INSTALL_EXIT_RE = re.compile(
    r"seedling install (?:completed|FAILED) \(exit code (-?\d+)\)")


def _parse_install_file(path: Path) -> list[dict]:
    """A bootstrap log. install.sh writes the same block format as the daily
    logs (so it parses identically); install.ps1 writes a raw transcript,
    which becomes a single entry timestamped from the filename. The
    transcript's exit code comes from the explicit completion marker; logs
    from before that marker existed fall back to the human-facing
    'seedling is installed.' success line, else remain unknown."""
    text = _read_log_text(path)
    if text.lstrip().startswith("=== ["):
        return _parse_file(path, kind="install")
    m = _INSTALL_RE.match(path.name)
    if m:
        d, t = m.group(1), m.group(2)
        ts = f"{d[0:4]}-{d[4:6]}-{d[6:8]} {t[0:2]}:{t[2:4]}:{t[4:6]}"
    else:
        ts = "0000-00-00 00:00:00"
    exit_code: int | None = None
    markers = _PS_INSTALL_EXIT_RE.findall(text)
    if markers:
        exit_code = int(markers[-1])
    elif "seedling is installed." in text:
        exit_code = 0
    return [{"ts": ts, "cmd": "installer (bootstrap)",
             "output": _ANSI_RE.sub("", text).strip("\n"),
             "exit": exit_code, "kind": "install", "dur": None}]


def collect_entries(days: int | None = None) -> list[dict]:
    """Every logged command AND every bootstrap install, newest first. The
    start timestamp is 'YYYY-MM-DD HH:MM:SS', which sorts chronologically as
    plain text."""
    entries: list[dict] = []
    for f in _log_files(days):
        entries.extend(_parse_file(f, kind="command"))
    for f in _install_files(days):
        entries.extend(_parse_install_file(f))
    entries.sort(key=lambda e: e["ts"], reverse=True)
    return entries


def render_html(entries: list[dict]) -> str:
    """A standalone HTML page. Entries are embedded as JSON and rendered with
    textContent in the browser, so arbitrary log output can never inject
    markup. The `</` escape keeps a literal </script> in the data from
    closing the embedding <script> tag early."""
    payload = {
        "generated": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "home": str(paths.HOME),
        "entries": entries,
    }
    data = json.dumps(payload).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", data)


def _open_in_browser(path: Path) -> bool:
    """Open the generated page with the OS default handler for .html (the
    browser), same approach as `seed repo-open`. Never fatal -- a headless
    box has no browser, and the caller prints the path either way."""
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]  # Windows-only
        elif system == "Darwin":
            subprocess.Popen(["open", str(path)], start_new_session=True)
        else:
            subprocess.Popen(["xdg-open", str(path)], start_new_session=True)
        return True
    except OSError:
        return False


def run(args) -> int:
    days = getattr(args, "days", None)
    no_open = getattr(args, "no_open", False)

    entries = collect_entries(days)

    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = paths.LOGS_DIR / VIEWER_FILENAME
    try:
        out_path.write_text(render_html(entries), encoding="utf-8")
    except OSError as e:
        print(f"error: couldn't write the log viewer ({e})", file=sys.stderr)
        return 1

    if not entries:
        print("No commands logged yet -- the viewer will be empty until you "
              "run some `seed` commands (or logging is off via SEEDLING_NO_LOG=1).")

    n = len(entries)
    fails = sum(1 for e in entries if e["exit"] not in (0, None))
    summary = f"{n} command{'s' if n != 1 else ''}"
    if fails:
        summary += f", {colors.danger(str(fails) + ' failed')}"
    print(f"Log viewer: {summary}")
    print(f"  {out_path}")

    if no_open:
        return 0
    if _open_in_browser(out_path):
        print("Opening in your browser ...")
    else:
        print("Couldn't launch a browser automatically; open the file above by hand.")
    return 0


# The page: a dense master-detail table (Date | Time | Status | Command |
# Duration) on the left; clicking a row shows that command's full output in
# the pane on the right. Filters (search, failures-only, date range) live in
# the header. Dark/light via prefers-color-scheme. __DATA__ is replaced with
# the JSON payload before writing.
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>seedling logs</title>
<style>
  :root {
    color-scheme: light dark;  /* native date pickers follow the theme */
    --bg: #ffffff; --fg: #1f2328; --muted: #656d76; --border: #d0d7de;
    --card: #f6f8fa; --accent: #0969da; --ok: #1a7f37; --fail: #cf222e;
    --code-bg: #f6f8fa; --sel: #ddf4ff; --hover: rgba(127,127,127,.07);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0d1117; --fg: #e6edf3; --muted: #8b949e; --border: #30363d;
      --card: #161b22; --accent: #4493f8; --ok: #3fb950; --fail: #f85149;
      --code-bg: #010409; --sel: #182f4d; --hover: rgba(127,127,127,.1);
    }
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0; background: var(--bg); color: var(--fg); overflow: hidden;
    display: flex; flex-direction: column;
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  }
  header { flex: none; border-bottom: 1px solid var(--border); padding: 12px 16px; }
  h1 { margin: 0; font-size: 16px; display: inline; }
  h1 .seed { color: var(--accent); }
  .meta { color: var(--muted); font-size: 12px; margin-left: 8px; }
  .controls { margin-top: 10px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  #search {
    flex: 1; min-width: 180px; padding: 6px 9px; border: 1px solid var(--border);
    border-radius: 6px; background: var(--card); color: var(--fg); font-size: 13px;
  }
  label.toggle { color: var(--muted); font-size: 13px; user-select: none; cursor: pointer; }
  .rangelabel { color: var(--muted); font-size: 13px; }
  input[type=date] {
    padding: 5px 7px; border: 1px solid var(--border); border-radius: 6px;
    background: var(--card); color: var(--fg); font-size: 12px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  input[type=date]:disabled { opacity: .5; }
  .dash { color: var(--muted); }
  .preset {
    padding: 5px 9px; border: 1px solid var(--border); border-radius: 6px;
    background: var(--card); color: var(--fg); font-size: 12px; cursor: pointer;
  }
  .preset:hover { border-color: var(--accent); }
  .preset.active { border-color: var(--accent); color: var(--accent); }

  .split { flex: 1; display: flex; min-height: 0; }
  .tablewrap { flex: 1.25; overflow: auto; border-right: 1px solid var(--border); position: relative; }
  table { width: 100%; border-collapse: collapse; table-layout: fixed; }
  thead th {
    position: sticky; top: 0; z-index: 1; background: var(--bg); text-align: left;
    font-size: 11px; text-transform: uppercase; letter-spacing: .04em; font-weight: 600;
    color: var(--muted); padding: 7px 8px; border-bottom: 1px solid var(--border);
  }
  th.r, td.dur { text-align: right; }
  tbody td {
    padding: 4px 8px; font-size: 12.5px; border-bottom: 1px solid var(--border);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: var(--hover); }
  tbody tr.selected { background: var(--sel); }
  td.date, td.time, td.dur { color: var(--muted);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
  td.cmd { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .badge { display: inline-block; min-width: 22px; text-align: center; padding: 2px 6px;
    border-radius: 10px; font: 600 11px/1.3 ui-monospace, SFMono-Regular, Menlo, monospace; }
  .badge.ok { color: #fff; background: var(--ok); }
  .badge.fail { color: #fff; background: var(--fail); }
  .badge.unknown { color: var(--muted); border: 1px solid var(--border); }
  .kindtag { font: 600 9px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
    text-transform: uppercase; letter-spacing: .03em; color: var(--accent);
    border: 1px solid var(--accent); border-radius: 3px; padding: 2px 4px; margin-right: 6px; }

  .detail { flex: 1; overflow: auto; padding: 16px 18px; }
  .dcmd { font: 600 14px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }
  .dmeta { color: var(--muted); font-size: 12px; margin: 8px 0 14px;
    display: flex; gap: 8px 16px; flex-wrap: wrap; align-items: center; }
  .detail pre {
    background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 14px; margin: 0; white-space: pre-wrap; word-break: break-word;
    font: 12.5px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .placeholder { color: var(--muted); text-align: center; margin-top: 15vh; font-size: 13px; }
  .empty-state { position: absolute; inset: 0; display: flex; align-items: center;
    justify-content: center; color: var(--muted); font-size: 13px; }
  .empty-state[hidden] { display: none; }
</style>
</head>
<body>
<header>
  <h1><span class="seed">seed</span> command logs</h1><span class="meta" id="meta"></span>
  <div class="controls">
    <input id="search" type="search" placeholder="Filter by command or output ...">
    <label class="toggle"><input type="checkbox" id="failonly"> failures only</label>
  </div>
  <div class="controls">
    <span class="rangelabel">Range</span>
    <button class="preset" data-days="0">All</button>
    <button class="preset" data-days="1">Today</button>
    <button class="preset" data-days="7">7 days</button>
    <button class="preset" data-days="30">30 days</button>
    <input type="date" id="from" aria-label="From date">
    <span class="dash">–</span>
    <input type="date" id="to" aria-label="To date">
  </div>
</header>
<div class="split">
  <div class="tablewrap">
    <table>
      <colgroup>
        <col style="width:96px"><col style="width:74px"><col style="width:60px">
        <col><col style="width:76px">
      </colgroup>
      <thead><tr>
        <th>Date</th><th>Time</th><th>Status</th><th>Command</th><th class="r">Duration</th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
    <div class="empty-state" id="empty" hidden></div>
  </div>
  <div class="detail" id="detail"></div>
</div>
<script>
const PAYLOAD = __DATA__;
const entries = PAYLOAD.entries;
document.getElementById("meta").textContent =
  entries.length + " command" + (entries.length === 1 ? "" : "s") +
  " · " + PAYLOAD.home + " · generated " + PAYLOAD.generated;

const rows = document.getElementById("rows");
const detail = document.getElementById("detail");
const empty = document.getElementById("empty");
const search = document.getElementById("search");
const failonly = document.getElementById("failonly");

function badgeFor(exit) {
  const b = document.createElement("span");
  b.className = "badge " + (exit === 0 ? "ok" : exit === null ? "unknown" : "fail");
  b.textContent = exit === null ? "?" : String(exit);
  return b;
}
function fmtDur(s) {
  if (s == null) return "";
  if (s === 0) return "<1s";
  if (s < 60) return s + "s";
  const m = Math.floor(s / 60), sec = Math.round(s % 60);
  return sec ? m + "m " + sec + "s" : m + "m";
}
function cell(cls, text) {
  const td = document.createElement("td");
  td.className = cls; if (text != null) td.textContent = text;
  return td;
}

// Build every row once; filtering just toggles each row's display.
const nodes = entries.map((e, i) => {
  const tr = document.createElement("tr");
  tr.appendChild(cell("date", e.ts.slice(0, 10)));
  tr.appendChild(cell("time", e.ts.slice(11)));
  const status = cell("status"); status.appendChild(badgeFor(e.exit));
  tr.appendChild(status);
  const cmd = cell("cmd");
  if (e.kind === "install") {
    const tag = document.createElement("span");
    tag.className = "kindtag"; tag.textContent = "setup";
    cmd.appendChild(tag);
  }
  cmd.appendChild(document.createTextNode(e.cmd));
  cmd.title = e.cmd;
  tr.appendChild(cmd);
  tr.appendChild(cell("dur", fmtDur(e.dur)));
  tr.addEventListener("click", () => select(i));
  rows.appendChild(tr);
  return { tr, e, text: (e.cmd + "\n" + e.output).toLowerCase(),
           fail: e.exit !== 0 && e.exit !== null, day: e.ts.slice(0, 10) };
});

let selected = -1;
function select(i) {
  if (selected >= 0 && nodes[selected]) nodes[selected].tr.classList.remove("selected");
  selected = i;
  if (i < 0) { renderDetail(null); return; }
  nodes[i].tr.classList.add("selected");
  nodes[i].tr.scrollIntoView({ block: "nearest" });
  renderDetail(entries[i]);
}
function metaSpan(text) {
  const s = document.createElement("span"); s.textContent = text; return s;
}
function renderDetail(e) {
  detail.textContent = "";  // clear; content rebuilt with textContent (injection-safe)
  if (!e) {
    const p = document.createElement("div");
    p.className = "placeholder";
    p.textContent = entries.length ? "Select a command to see its output"
                                   : "No commands have been logged yet.";
    detail.appendChild(p);
    return;
  }
  const cmd = document.createElement("div");
  cmd.className = "dcmd"; cmd.textContent = e.cmd;
  const meta = document.createElement("div");
  meta.className = "dmeta";
  const badge = badgeFor(e.exit);
  meta.appendChild(badge);
  meta.appendChild(metaSpan(e.ts));
  meta.appendChild(metaSpan(e.exit === null ? "no exit code" : "exit code " + e.exit));
  if (e.dur != null) meta.appendChild(metaSpan("took " + fmtDur(e.dur)));
  if (e.kind === "install") meta.appendChild(metaSpan("bootstrap installer"));
  const pre = document.createElement("pre");
  pre.textContent = e.output || "(no output)";
  detail.append(cmd, meta, pre);
}

// --- date range (all entries embedded; filtering is pure client-side) ---
const fromEl = document.getElementById("from");
const toEl = document.getElementById("to");
const presets = [...document.querySelectorAll(".preset")];
let minDay = null, maxDay = null;
if (entries.length) {
  const days = entries.map(e => e.ts.slice(0, 10)).sort();
  minDay = days[0]; maxDay = days[days.length - 1];
  for (const el of [fromEl, toEl]) { el.min = minDay; el.max = maxDay; }
  fromEl.value = minDay; toEl.value = maxDay;
} else {
  fromEl.disabled = toEl.disabled = true;
}
function addDays(iso, n) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}
function markPreset(active) {
  for (const b of presets) b.classList.toggle("active", b === active);
}
for (const btn of presets) {
  btn.addEventListener("click", () => {
    if (!maxDay) return;
    const n = parseInt(btn.dataset.days, 10);
    let from = (n === 0) ? minDay : addDays(maxDay, -(n - 1));
    if (from < minDay) from = minDay;   // don't run before the oldest log
    fromEl.value = from; toEl.value = maxDay;
    markPreset(btn); apply();
  });
}
for (const el of [fromEl, toEl]) el.addEventListener("change", () => { markPreset(null); apply(); });

function apply() {
  const q = search.value.trim().toLowerCase();
  const onlyFail = failonly.checked;
  const from = fromEl.value, to = toEl.value;
  let shown = 0, firstVisible = -1;
  nodes.forEach((n, i) => {
    const inRange = (!from || n.day >= from) && (!to || n.day <= to);
    const ok = inRange && (!q || n.text.includes(q)) && (!onlyFail || n.fail);
    n.tr.style.display = ok ? "" : "none";
    if (ok) { shown++; if (firstVisible < 0) firstVisible = i; }
  });
  empty.hidden = shown !== 0;
  if (shown === 0) { empty.textContent = "No commands match your filter."; }
  // Keep a valid selection: if the selected row got filtered out (or none was
  // selected), jump to the newest visible one so the detail pane stays useful.
  if (selected < 0 || nodes[selected].tr.style.display === "none") {
    select(firstVisible);
  }
}
search.addEventListener("input", apply);
failonly.addEventListener("change", apply);
markPreset(presets.find(b => b.dataset.days === "0"));  // "All" selected on load
apply();
</script>
</body>
</html>
"""
