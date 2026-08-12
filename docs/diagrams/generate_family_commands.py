#!/usr/bin/env python3
"""Generate one commands-<slug>.svg per docs/commands/<slug>.md page: every
command in that family as its own row -- a small subcard with the
signature on the left, its plain-language "what it actually does"
description running to the right of that subcard, grouped under a
section label ("Create & switch", "Packages", "Danger zone", ...) where
the family has more than one natural grouping.

This is the same row-per-command shape command-map.svg settled on, and for
the same reason: an earlier version of this file connected each command to
the part of ~/seedling it reads or writes with an arrow into a small,
family-scoped folder-tree column on the right (danger-zone commands got
their own separate target cluster, cards sharing an identical target were
bracketed into one arrow). It worked better here than it ever did in
command-map.svg's all-families version, since one family only ever reaches
a handful of folders -- but command-map.svg's redesign made the case for
dropping the folder side everywhere: showing what a command actually does
is the point of a per-command description, and giving it room to be read
in full, instead of splitting attention between prose and a target chip,
is worth more than the folder-mapping was.

FAMILIES keeps its target/danger_target/whole_tree fields even though this
file no longer renders them -- generate_command_map.py imports FAMILIES
directly to build its own row-per-command page across every family in one
place, and changing this tuple's shape would break that import. Unused
here, still the source of truth there.

The content below is transcribed BY HAND from each docs/commands/<slug>.md
page -- there is no automated link between the two. If a command's
behavior changes there, update its entry here too and re-run:

    python docs/diagrams/generate_family_commands.py
"""

from __future__ import annotations

from pathlib import Path

from generate_profile_flows import DEFS, ICE, NAVY, SLATE, WHITE, esc, header

DANGER = "#9C4A3C"
DANGER_TINT = "#F5E8E5"
FONT_MONO = "Consolas, 'SF Mono', Monaco, 'Courier New', monospace"
OUT_DIR = Path(__file__).parent

# -- one entry per docs/commands/<slug>.md page.
#   subtitle:        the page's own intro line.
#   targets:          unused here -- kept for generate_command_map.py's
#                     import. See that file for the shape.
#   danger_targets:   unused here -- see above.
#   whole_tree:       unused here -- see above.
#   sections:         list of (label_or_None, items); items is a list of
#                     (signature, desc_lines, danger, arrow_targets).
#                     arrow_targets is unused here too (kept for the same
#                     reason as targets/danger_targets/whole_tree above).
FAMILIES = [
    ("interpreters", "Python interpreters",
     "Structural commands: the base installs that venvs are built from.",
     [("python", "python/", "interpreters + venvs", [("base/", "base")])],
     [("python", "python/", "interpreters + venvs", [("base/", "base"), ("venvs/<name>/", "venvs")])],
     [],
     [
        (None, [
            ("seed python [version]",
             ["Installs a base CPython interpreter via uv. The first one",
              "installed becomes the default `seed venv` builds from."], False, [("python", "base")]),
            ("seed python-list [--json]",
             ["Lists installed base interpreters, the real versioned target",
              "each points to, which is default, and flags any broken alias."], False, [("python", "base")]),
        ]),
        ("Danger zone", [
            ("seed remove-python <tag>",
             ["Deletes a base Python -- and every venv built from it, since",
              "a venv can't outlive the interpreter it was created against."], True, [("python", "base"), ("python", "venvs")]),
        ]),
     ]),

    ("venvs-and-packages", "Venvs & packages",
     "The day-to-day family: creating and switching environments, and installing packages into them.",
     [
        ("python", "python/", "interpreters + venvs", [("venvs/<name>/", "venvs")]),
        ("system", "system/", "seedling's own internals", [("config/", "config")]),
     ],
     [("python", "python/", "interpreters + venvs", [("venvs/<name>/", "venvs")])],
     [],
     [
        ("Create & switch", [
            ("seed venv <name> [--python tag]",
             ["Creates a venv from a base interpreter and installs the",
              "default package set into it."], False, [("python", "venvs")]),
            ("seed venv-list [--json]",
             ["Lists every venv, its Python version, and which one is active."], False, [("python", "venvs")]),
            ("seed activate <name>",
             ["Activates a venv in the current shell."], False, [("python", "venvs")]),
            ("seed deactivate",
             ["Deactivates whatever venv is active in the current shell."], False, [("python", "venvs")]),
            ("seed run [-n venv] -- <cmd>",
             ["Runs one command inside a venv without activating anything --",
              "exit code and output pass through untouched."], False, [("python", "venvs")]),
            ("seed which [name] [--json]",
             ["Prints a venv's interpreter path, and nothing else."], False, [("python", "venvs")]),
            ("seed venv-default [name]",
             ["Shows or sets the venv every new shell auto-activates --",
              "writes default_venv to settings.json, not to the venv itself."], False, [("system", "config")]),
            ("seed auto-activate [True|False]",
             ["Turns auto-activation of the default venv on or off --",
              "also just a settings.json write."], False, [("system", "config")]),
        ]),
        ("Packages", [
            ("seed install <package...>",
             ["Passthrough to `uv pip install`, into the active venv."], False, [("python", "venvs")]),
            ("seed uninstall <package...>",
             ["Passthrough to `uv pip uninstall`."], False, [("python", "venvs")]),
            ("seed package-list [--json]",
             ["Passthrough to `uv pip list` for the active venv."], False, [("python", "venvs")]),
            ("seed show <package...>",
             ["Passthrough to `uv pip show` -- full detail on one installed package."], False, [("python", "venvs")]),
        ]),
        ("Danger zone", [
            ("seed remove-venv <name>",
             ["Deletes one venv, force-closing anything holding it open first."], True, [("python", "venvs")]),
            ("seed remove-venv-all",
             ["Deletes every venv under python/venvs."], True, [("python", "venvs")]),
        ]),
     ]),

    ("python-apps", "Python applications",
     "Run, not imported -- each installed into its own isolated environment.",
     [
        ("extensions", "extensions/", "editors + PyPI apps", [("apps/<name>/", "apps")]),
        ("system", "system/", "seedling's own internals", [("shims/", "shims")]),
     ],
     [
        ("extensions", "extensions/", "editors + PyPI apps", [("apps/<name>/", "apps")]),
        ("system", "system/", "seedling's own internals", [("shims/", "shims")]),
     ],
     [],
     [
        (None, [
            ("seed tool-install <name>[==ver]",
             ["Installs a PyPI application (Spyder, JupyterLab, httpie) into",
              "its own venv under extensions/apps/, launchers on PATH --",
              "not your project venv."], False, [("extensions", "apps"), ("system", "shims")]),
            ("seed tool-list",
             ["Lists installed applications and their versions."], False, [("extensions", "apps")]),
        ]),
        ("Danger zone", [
            ("seed tool-remove <name>",
             ["Removes an application's environment and launchers -- leaves",
              "whatever it installed into your project venvs alone."], True, [("extensions", "apps"), ("system", "shims")]),
        ]),
     ]),

    ("conda-forge-tools", "Command-line tools from conda-forge",
     "The non-Python tools -- ripgrep, pandoc, ffmpeg, gh, compilers.",
     [("system", "system/", "seedling's own internals", [("conda/", "conda"), ("shims/", "shims")])],
     [("system", "system/", "seedling's own internals", [("conda/", "conda"), ("shims/", "shims")])],
     [],
     [
        (None, [
            ("seed forge <command> [args...]",
             ["Runs an installed conda-forge tool by its exact path -- works",
              "immediately, no PATH or fresh terminal needed."], False, [("system", "conda")]),
            ("seed forge-install <name>[=ver]",
             ["Installs a command-line tool from conda-forge via micromamba,",
              "plus PATH launchers -- same shape as tool-install."], False, [("system", "conda"), ("system", "shims")]),
            ("seed forge-list",
             ["Lists installed conda-forge tools and the command(s) each provides."], False, [("system", "conda")]),
        ]),
        ("Danger zone", [
            ("seed forge-remove <name>",
             ["Removes a conda-forge tool: its environment, launchers, and record."], True, [("system", "conda"), ("system", "shims")]),
        ]),
     ]),

    ("offline-utilities", "Offline utilities",
     "Stage packages and tools on a connected machine, to install from later with no network at all.",
     [("outside", "(current directory)", "NOT inside ~/seedling", [
         ("./wheelhouse/", "wheelhouse"), ("./conda-channel/", "conda-channel"),
     ])],
     [], [],
     [
        (None, [
            ("seed download-whl <package...>",
             ["Downloads a package and its dependencies as .whl files into",
              "./wheelhouse, to carry to an air-gapped machine."], False, [("outside", "wheelhouse")]),
            ("seed download-requirements <req.txt>",
             ["Same as download-whl, reading specifiers from a requirements file."], False, [("outside", "wheelhouse")]),
            ("seed download-forge <name...>",
             ["Resolves a conda-forge tool and its dependencies into a local",
              "conda channel folder -- the download-whl of the conda-forge side."], False, [("outside", "conda-channel")]),
        ]),
     ]),

    ("repos", "Repos",
     "Cloning, opening, and installing dependencies from git repositories.",
     [
        ("repo", "repo/", "one folder per clone", [("<name>/", "name")]),
        ("python", "python/", "interpreters + venvs", [("venvs/<name>/", "venvs")]),
     ],
     [("repo", "repo/", "one folder per clone", [("<name>/", "name")])],
     [],
     [
        (None, [
            ("seed repo-clone <git-url>",
             ["Clones a git repo into repo/<name> -- bootstraps a portable",
              "git on Windows automatically if none is found."], False, [("repo", "name")]),
            ("seed repo-list",
             ["Lists cloned repos and each one's origin remote."], False, [("repo", "name")]),
            ("seed repo-cd [name]",
             ["Changes the current shell's directory into a cloned repo."], False, [("repo", "name")]),
            ("seed repo-open [name]",
             ["Opens a cloned repo in the OS file manager."], False, [("repo", "name")]),
            ("seed repo-install <name>[extras]",
             ["Installs a cloned repo's dependencies (editable) into a venv --",
              "the active one by default. Writes into the venv, not the repo."], False, [("python", "venvs")]),
        ]),
        ("Danger zone", [
            ("seed remove-repo <name>",
             ["Deletes a cloned repo."], True, [("repo", "name")]),
        ]),
     ]),

    ("editors", "Editors & IDEs",
     "Installed on demand, portable, and self-contained inside ~/seedling.",
     [
        ("extensions", "extensions/", "editors + PyPI apps", [
            ("vscode/", "vscode"), ("spyder-config/", "spyder-config"), ("apps/<name>/", "apps"),
        ]),
        ("system", "system/", "seedling's own internals", [("shims/", "shims")]),
     ],
     [], [],
     [
        (None, [
            ("seed vscode [path]",
             ["Installs a portable VS Code (once) and opens it at a path --",
              "settings, extensions, and workspace state stay inside ~/seedling."], False, [("extensions", "vscode")]),
            ("seed vscode-repo <name>",
             ["Opens a cloned repo in VS Code, installing VS Code first if needed."], False, [("extensions", "vscode")]),
            ("seed spyder [path] [--venv name]",
             ["Underneath it's `tool-install spyder` -- installs into",
              "extensions/apps/ with a PATH launcher, then points it at a",
              "venv and seeds extensions/spyder-config/."], False, [("extensions", "apps"), ("system", "shims"), ("extensions", "spyder-config")]),
            ("seed spyder-repo <name> [--venv name]",
             ["Opens a cloned repo as a Spyder project -- same install-if-needed", "shape as seed spyder."], False, [("extensions", "apps"), ("system", "shims"), ("extensions", "spyder-config")]),
        ]),
     ]),

    ("custom", "Custom commands",
     "An organization's own verbs, added to seed.",
     [("system", "system/", "seedling's own internals", [("config/", "config")])],
     [], [],
     [
        (None, [
            ("seed custom [name] [args...]",
             ["Runs one [[command]] entry from custom-commands.toml: a fixed",
              "argv (run = [...]), or a script that chains seed subcommands",
              "together. No name lists what's configured."], False, [("system", "config")]),
        ]),
     ]),

    ("lifecycle", "Fleet & lifecycle",
     "Cleanup, updates, and full-machine teardown.",
     [("system", "system/", "seedling's own internals", [("src/", "src"), ("shell/", "shell")])],
     [
        ("system", "system/", "seedling's own internals", []),
        ("python", "python/", "interpreters + venvs", []),
        ("extensions", "extensions/", "editors + PyPI apps", []),
        ("repo", "repo/", "one folder per clone", []),
     ],
     ["system", "python", "extensions", "repo"],
     [
        (None, [
            ("seed kill-processes [name] [--system]",
             ["Force-closes stuck processes -- scoped to seedling by default;",
              "--system or a name widens it to the whole machine."], False, []),
            ("seed update-commands",
             ["Updates seed itself from its recorded source, and reports any",
              "seedling.conf drift since install -- never touches venvs, packages, or repos."], False, [("system", "src"), ("system", "shell")]),
        ]),
        ("Danger zone", [
            ("seed remove-user",
             ["Deletes ~/seedling entirely -- keeps the shell hook."], True, ["ALL"]),
            ("seed purge",
             ["Everything remove-user does, plus removes the shell hook itself --",
              "seed stops existing as a command."], True, ["ALL"]),
            ("seed purge-and-reinstall",
             ["Purge, then reinstalls from the recorded source -- cloned repos",
              "are always preserved and restored."], True, ["ALL"]),
        ]),
     ]),

    ("status", "Status & profiles",
     "Read-only status, plus applying a fleet-wide deployment profile.",
     [("system", "system/", "seedling's own internals", [("config/", "config"), ("logs/", "logs")])],
     [], [],
     [
        (None, [
            ("seed where",
             ["Prints the seedling home directory."], False, []),
            ("seed --version",
             ["Prints the version of seed that's actually running."], False, []),
            ("seed summary [--sizes] [--json]",
             ["One read-only screen of everything installed: interpreters,",
              "venvs, repos, tooling, and settings."], False, [("system", "logs")]),
            ("seed health-check [--json]",
             ["Verifies every moving part, one line per check -- exits 1 if",
              "anything actually fails."], False, [("system", "logs")]),
            ("seed logs-viewer [--days N]",
             ["Renders every logged command into a self-contained, searchable HTML page."], False, [("system", "logs")]),
            ("seed apply [profile] [--preview] [--force]",
             ["Brings this machine in line with a deployment profile, idempotently --",
              "never destroys an existing venv or repo."], False, [("system", "config")]),
            ("seed config [get|set|unset]",
             ["Views and changes seedling's own settings (default_venv,",
              "package_index, vscode_flavor, ...)."], False, [("system", "config")]),
        ]),
     ]),

    ("scripting-and-automation", "Scripting & automation",
     "The machine-facing surface -- Makefiles, CI steps, and AI agents -- as capabilities, not new commands.",
     [], [], [],
     [
        (None, [
            ("seed-cli on PATH",
             ["Reachable without the shell hook -- works in a fresh,",
              "non-interactive process that never loads a shell profile."], False, []),
            ("seed which  /  seed run",
             ["Get an interpreter path, or run one command inside a venv,",
              "without activating anything."], False, []),
            ("--json on every read command",
             ["summary, venv-list, python-list, which, health-check,",
              "package-list -- all agree on shape, all schema-versioned."], False, []),
            ("--non-interactive  /  -y",
             ["Never blocks on a prompt -- aborts instead, or pre-answers it.",
              "SEEDLING_NONINTERACTIVE=1 / SEEDLING_YES=1 set both for a session."], False, []),
            ("Per-venv locking",
             ["install/uninstall/venv/remove-venv take an exclusive lock, so",
              "parallel CI jobs or agents queue instead of corrupting site-packages."], False, []),
            ("seed apply",
             ["Declarative setup: a deployment profile reaches its target state",
              "idempotently -- first provisioning and drift repair, same primitive."], False, []),
            ("Exit codes",
             ["0 success, 1 failure, 127 command not in the venv, 130 interrupt."], False, []),
        ]),
     ]),
]

G_X = 40
SUB_W = 300
DESC_GAP = 24
DESC_W = 760
CANVAS_W = G_X + SUB_W + DESC_GAP + DESC_W + 40

SUB_H = 30
ROW_GAP = 10
DESC_SIZE = 12.5
DESC_LINE_H = 17
SECTION_LABEL_H = 26
SECTION_GAP = 20
TABLE_TOP = 128


def _wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        candidate = f"{cur} {w}".strip()
        if len(candidate) > max_chars and cur:
            lines.append(cur)
            cur = w
        else:
            cur = candidate
    if cur:
        lines.append(cur)
    return lines


def _desc_wrap_chars() -> int:
    # ~6.3px/char at DESC_SIZE Arial regular -- same estimate command-map.svg
    # uses for the same font/size combination.
    return int(DESC_W / 6.3)


def _row_height(desc_lines: list[str]) -> float:
    return max(SUB_H, len(desc_lines) * DESC_LINE_H)


def _render_row(svg: list, y: float, signature: str, desc_lines: list[str], danger: bool) -> None:
    fill = DANGER_TINT if danger else ICE
    stroke = DANGER if danger else NAVY
    text_fill = DANGER if danger else NAVY
    row_h = _row_height(desc_lines)
    sub_y = y + (row_h - SUB_H) / 2
    svg.append(f'<rect x="{G_X:.0f}" y="{sub_y:.0f}" width="{SUB_W:.0f}" height="{SUB_H:.0f}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1" opacity="0.95"/>')
    svg.append(f'<text x="{G_X+12:.0f}" y="{sub_y+SUB_H/2+4.5:.0f}" font-family="{FONT_MONO}" font-size="12.5" font-weight="700" fill="{text_fill}">{esc(signature)}</text>')
    desc_x = G_X + SUB_W + DESC_GAP
    desc_y0 = y + (row_h - len(desc_lines) * DESC_LINE_H) / 2 + DESC_LINE_H - 5
    for i, line in enumerate(desc_lines):
        svg.append(f'<text x="{desc_x:.0f}" y="{desc_y0 + i*DESC_LINE_H:.0f}" class="body" font-size="{DESC_SIZE}" fill="{SLATE}">{esc(line)}</text>')


def _sections_height(sections: list, max_chars: int) -> float:
    total = 0.0
    for label, items in sections:
        if label:
            total += SECTION_LABEL_H
        for _, desc_lines, _, _ in items:
            wrapped = _wrap(" ".join(desc_lines), max_chars)
            total += _row_height(wrapped) + ROW_GAP
        total += SECTION_GAP
    return total


def build_one(slug: str, title: str, subtitle: str, sections: list) -> None:
    max_chars = _desc_wrap_chars()
    canvas_h = TABLE_TOP + _sections_height(sections, max_chars) + 30

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS_W} {canvas_h:.0f}" font-family="Arial, Helvetica, sans-serif">']
    svg.append(f"<defs>{DEFS}</defs>")
    svg.append(f'<rect x="0" y="0" width="{CANVAS_W}" height="{canvas_h:.0f}" fill="{WHITE}"/>')
    svg.append(header(title, subtitle))

    y = TABLE_TOP
    for label, items in sections:
        if label:
            danger_label = any(d for _, _, d, _ in items)
            label_color = DANGER if danger_label else SLATE
            svg.append(f'<text x="{G_X:.0f}" y="{y+14:.0f}" class="body" font-size="12.5" font-weight="700" fill="{label_color}" letter-spacing="0.4">{esc(label.upper())}</text>')
            y += SECTION_LABEL_H
        for signature, desc_lines, danger, _arrow_targets in items:
            wrapped = _wrap(" ".join(desc_lines), max_chars)
            _render_row(svg, y, signature, wrapped, danger)
            y += _row_height(wrapped) + ROW_GAP
        y += SECTION_GAP

    svg.append("</svg>")
    out_path = OUT_DIR / f"commands-{slug}.svg"
    out_path.write_text("\n".join(svg), encoding="utf-8")
    print(f"wrote commands-{slug}.svg  ({CANVAS_W}x{canvas_h:.0f})")


def build() -> None:
    for slug, title, subtitle, _targets, _danger_targets, _whole_tree, sections in FAMILIES:
        build_one(slug, title, subtitle, sections)


if __name__ == "__main__":
    build()
