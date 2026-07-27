"""
The editor / IDE family.

seedling bundles one editor today (VS Code, in its Microsoft or VSCodium
build) and is designed to gain others -- Spyder next. This module holds the
parts that are the same whatever the editor is:

  - the first-run download gate (every bundled editor is a large download
    whose cost is invisible until it happens),
  - the detached launch (an editor must never block the terminal or leak its
    own log spam into it),
  - the registry `seed help` renders the family from.

Anything that knows a specific editor's archive layout, CLI flags, settings
file, or extension mechanism belongs in that editor's own module, not here.
The test of whether something belongs in this file is simple: could a second,
unrelated editor use it unchanged?

Editors register themselves at import time (see the bottom of vscode_cmd),
so adding one to the family is a `register(...)` call rather than an edit
scattered across cli.py's help tables.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Callable

from .. import confirm

# Passed to every editor subprocess we launch, so Electron/GPU/Chromium log
# spam never lands in the user's terminal.
QUIET = {
    "stdout": subprocess.DEVNULL,
    "stderr": subprocess.DEVNULL,
    "stdin": subprocess.DEVNULL,
}


@dataclass(frozen=True)
class Editor:
    """One bundled editor, as the CLI presents it.

    Deliberately presentation + a liveness check only -- NOT install/launch
    hooks. Those differ so much between editors (an archive extract with a
    product.json rewrite, versus a uv tool install with a kernels package in
    another venv) that a shared signature would be a fiction, and the family
    would end up passing options nobody else understands.

    `label` is a plain string rather than a callable because `seed help`
    renders it: resolving a configured value here (VS Code's flavor, say)
    would let a misconfigured setting crash the help screen, which must
    always work. Commands that need the precise build name resolve it
    themselves when they run.
    """

    key: str                      # registry key, e.g. "vscode"
    label: str                    # human name for help, e.g. "VS Code"
    command: str                  # `seed <command>`
    summary: str                  # one-line help description
    download_note: str            # e.g. "~300 MB download"
    is_installed: Callable[[], bool]
    # The editor's own `run(args) -> int` -- the CLI dispatch contract it
    # already satisfies, not a new abstraction invented for the registry.
    # That distinction matters: this type deliberately has no install()/
    # launch() hooks, because those genuinely differ (VS Code extracts an
    # archive and patches product.json; Spyder installs a uv tool and a
    # kernels package into a DIFFERENT venv), and a shared signature for
    # them would be a fiction. `run` is safe to share precisely because
    # cli.py already calls both through it.
    run: Callable[[object], int]
    args_hint: str = ""           # e.g. "[path] [--reinstall]"
    repo_command: str | None = None      # `seed <repo_command> <name>`
    repo_summary: str = ""


REGISTRY: dict[str, Editor] = {}


def register(editor: Editor) -> None:
    REGISTRY[editor.key] = editor


def ensure_registered() -> dict[str, Editor]:
    """The registry, with the built-in editors guaranteed to be in it.

    Editors register themselves at import time, which is fine for the CLI --
    cli.py imports every command module. It is NOT fine for anything that
    reaches the registry without going through the CLI: `seedling.profile`
    validates a profile's `editor` key against it, and the offline bundler
    loads a profile long before it imports any editor module. That saw an
    EMPTY registry and rejected every valid editor with "Valid values: ."

    Imported inside the function, not at module scope: the editor modules
    import this one, so a top-level import would be circular."""
    from . import spyder_cmd, vscode_cmd  # noqa: F401  (registers on import)
    return REGISTRY


def confirm_first_install(args, *, label: str, note: str,
                          installed: bool) -> bool:
    """Ask before an editor's first-run download. Returns False (having said
    what to do instead) if the user declined.

    Only the DOWNLOAD is gated -- opening an editor that is already installed
    is the common case and stays instant. Everything else in seedling that
    costs this much asks first (every remove-*, the offline builder's licence
    gate), and on a metered or locked-down connection the surprise is
    expensive.

    Takes label/note explicitly rather than an Editor, so a caller can pass
    the precise build name it just resolved (VS Code vs VSCodium) without
    this function reaching for configuration.
    """
    if installed:
        return True
    print(f"{label} isn't installed yet ({note}).")
    if confirm.ask(args, f"Install {label} now?"):
        return True
    print(f"Skipped. To install it later:  seed {_install_hint(label)} -y")
    return False


def _install_hint(label: str) -> str:
    """The command that installs `label`, for the decline message."""
    for editor in REGISTRY.values():
        if editor.label == label or label.lower().startswith(editor.key):
            return editor.command
    return "vscode"


def open_detached(argv: list[str], path: str) -> None:
    """Launch an editor at `path`, fully detached from seedling's own process
    so it never blocks the caller or leaks output into their terminal.

    Generic on purpose: every GUI editor needs exactly this, and the only
    per-editor part is the argv prefix the caller resolved."""
    popen_kwargs = dict(QUIET)
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        popen_kwargs["start_new_session"] = True
    subprocess.Popen([*argv, path], **popen_kwargs)


def help_rows() -> list[tuple[str, str, str]]:
    """The family's rows for `seed help`, as (name, args-hint, description).

    Every registered editor is listed whether or not it is installed --
    hiding a command the user could run destroys discovery, and an
    uninstalled one still dispatches (it offers to install). Installed ones
    are marked so the screen answers "what do I already have?" at a glance.
    """
    rows: list[tuple[str, str, str]] = []
    for editor in REGISTRY.values():
        try:
            present = editor.is_installed()
        except OSError:
            # Help must never fail on a filesystem hiccup.
            present = False
        suffix = "  (installed)" if present else f"  ({editor.download_note})"
        rows.append((editor.command, editor.args_hint,
                     editor.summary + suffix))
        if editor.repo_command:
            rows.append((editor.repo_command, "<name>", editor.repo_summary))
    return rows
