"""
`seed run [-n NAME] -- <cmd...>` -- run one command inside a venv, without
activating anything.

`seed activate` deliberately mutates the calling shell, which is right for a
person at a terminal and useless to everything else: a Makefile recipe, a CI
step, and an AI agent each get a fresh process per command and have no shell
to mutate. Their only options today are to hardcode
`~/seedling/python/venvs/<name>/bin/python` or to re-derive it every time.
This is the non-interactive sibling of `activate` that closes that gap, and
the venv-shaped counterpart of `seed tool <cmd>`.

Three contracts matter more than the feature itself:

  1. **The child's exit code is passed through verbatim.** Anything else
     makes `seed run -- pytest` worthless in CI.
  2. **stdout and stderr are the child's, untouched.** The child inherits
     the real file descriptors, so its output does NOT pass through
     seedling's logging tee -- which means `seed run -- python -c 'print
     json'` stays byte-exact and pipeable. The invocation is logged; the
     child's output is not, and that is on purpose. (`_Tee.fileno()`
     returning the real descriptor is what makes this work; see runlog.)
  3. **argv, not a shell.** No pipes, no redirection, no glob expansion, no
     shell=True. `seed run -- sh -c '...'` is available to anyone who wants
     shell semantics and knows they're asking for them.

What it does to the environment is exactly what an activate script does, and
no more: set VIRTUAL_ENV, prepend the venv's bin/Scripts to PATH, and clear
PYTHONHOME. It is a launcher, not a sandbox -- the child has every bit of
reach the caller has.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from .. import paths, venv_target

USAGE = ("Usage: seed run [-n <venv>] -- <command> [args...]\n"
         "   e.g. seed run -- python -V\n"
         "        seed run -n myproject -- pytest -q")


def child_env(target: venv_target.Target, base: dict | None = None) -> dict:
    """The environment a command sees inside `target` -- the same three
    changes a venv's activate script makes, and nothing else."""
    env = dict(os.environ if base is None else base)
    env["VIRTUAL_ENV"] = str(target.path)
    bin_dir = str(paths.venv_bin_dir(target.path))
    existing = env.get("PATH", "")
    env["PATH"] = bin_dir + os.pathsep + existing if existing else bin_dir
    # A stale PYTHONHOME overrides the venv's own prefix and produces a
    # baffling "Could not find platform independent libraries" -- activate
    # scripts unset it for exactly this reason.
    env.pop("PYTHONHOME", None)
    return env


def resolve_command(program: str, env: dict) -> str | None:
    """Find `program` on the CHILD's PATH, not the parent's.

    This is load-bearing, and the reason `seed run` doesn't just hand a bare
    name to subprocess. On Windows, CreateProcess resolves argv[0] against
    the PATH of the CALLING process -- the `env` you pass is handed to the
    child but is NOT used to find it. So `seed run -- python` would prepend
    the venv's Scripts to the child's PATH and then cheerfully launch the
    system python anyway: the venv is set up correctly, and the wrong
    interpreter runs inside it. Silent, and precisely backwards from the
    command's entire purpose.

    POSIX gets this right on its own (the PATH search uses the passed env),
    so resolving here also makes the two platforms behave identically
    instead of only one of them being correct.

    A program given as a path (`./script.py`, an absolute path) is left
    alone -- there's nothing to search for.
    """
    if os.path.dirname(program):
        return program
    return shutil.which(program, path=env.get("PATH"))


def strip_separator(cmd: list[str]) -> list[str]:
    """Drop the single leading `--` argparse leaves in REMAINDER.

    Only the first one: `seed run -- pytest -- -k foo` must hand the second
    `--` to pytest, because it means something to pytest.
    """
    return cmd[1:] if cmd and cmd[0] == "--" else cmd


def run(args) -> int:
    cmd = strip_separator(list(getattr(args, "cmd", None) or []))
    if not cmd:
        print(USAGE, file=sys.stderr)
        return 1

    target, error = venv_target.resolve(getattr(args, "venv", None))
    if target is None:
        print(f"error: {error}", file=sys.stderr)
        return 1

    env = child_env(target)
    program = resolve_command(cmd[0], env)
    if program is None:
        # 127 is the shell's "command not found", and worth being specific
        # about: the usual cause is a tool that isn't installed in THAT
        # venv, which a bare "No such file or directory" doesn't convey.
        print(f"error: command not found in venv '{target.name}': {cmd[0]}\n"
              f"       add it with:  seed activate {target.name} "
              f"&& seed install {cmd[0]}",
              file=sys.stderr)
        return 127

    try:
        # No capture and no check: the child owns the terminal, and a
        # non-zero exit is a result to pass on, not a seedling failure.
        completed = subprocess.run([program, *cmd[1:]], env=env, check=False)
    except OSError as e:
        print(f"error: couldn't run {cmd[0]}: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # On POSIX the SIGINT already reached the child (same foreground
        # process group) and subprocess.run reaped it; on Windows the
        # console sent CTRL_C_EVENT to the group. Either way the child is
        # gone and 130 is the honest answer -- don't let cli._invoke print
        # its own "Cancelled." over whatever the child said on its way out.
        return 130
    return completed.returncode
