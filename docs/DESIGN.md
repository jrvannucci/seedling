# Design and safety

Why seedling behaves the way it does. None of this is required reading to use
it — but if you are evaluating seedling for other people, or wondering why a
removal did something unexpected, the reasoning is here.

---

## Contents

- [Why deletion is so defensive](#why-deletion-is-so-defensive)
- [Non-interactive mode & previews](#non-interactive-mode--previews)
- [Command logging](#command-logging)
- [Download verification](#download-verification)

---

## Why deletion is so defensive

Every command that deletes a directory (`remove-venv(-all)`, `remove-python`,
`remove-repo`, `remove-user`, `purge`) routes through a shared helper
(`robust_rmtree`) that works around four real causes of "file in use" /
permission-denied failures, rather than just calling
`shutil.rmtree(path, ignore_errors=True)` and hoping:

1. **The calling process's own working directory being inside the folder
   being deleted.** Windows refuses to delete a directory that is any
   running process's cwd — including `seed-cli` itself. This is easy to hit
   in practice: activate a venv, `cd` into its project directory (or the
   venv folder itself), then run a remove/purge command from right there.
   The fix moves the process out to the user's home directory first, if
   its cwd is inside (or is) the target.
2. **A process that was just force-closed** (a blocked delete closes
   whatever is holding the files, see `seed kill-processes`) not having
   released its file handles instantly. The fix retries deletion a few
   times with a short delay instead of failing on the first pass.
3. **Read-only files.** Windows refuses to delete them outright, and git
   marks every file under `.git/objects` read-only — so any tree holding a
   git checkout (every cloned repo) would otherwise fail on hundreds of
   files at once. The error handler clears the read-only bit and retries
   each failed file individually.
4. **A program can't delete its own running executable.** `seed purge` and
   `seed remove-user` run *as* `seed-cli.exe` (plus the tool venv's
   `python.exe` underneath it), which live inside the very tree being
   deleted. When those are the only survivors, the command hands them to a
   small invisible helper that finishes the deletion a moment after
   `seed-cli` exits — and says so, instead of reporting an error. The
   `seed` shell function (still loaded in your session) then waits for the
   helper and prints an explicit confirmation — "Confirmed: ~/seedling has
   been fully removed" — or a warning with the leftover path if something
   is still holding files open, so the outcome is never silent.

If a file is genuinely still stuck after all retries — something *outside*
seedling holding it open — you get its exact path printed, instead of a
vague "something might be in use" message.

---

### How a removal frees locked files

Deleting a file that another process holds open **fails on Windows** and
**succeeds on POSIX** — unlinking there just removes the directory entry. So
everything below is a Windows concern; on macOS and Linux a removal simply
works and none of it runs.

Every remove command (`remove-venv`, `remove-venv-all`, `remove-python`,
`remove-repo`, `remove-user`, `purge`) escalates only as far as it has to:

1. **Delete.** Usually nothing is holding anything, and **nothing is closed.**
2. **Find out what's blocking, and close only that.** seedling asks the
   Windows **Restart Manager** — the API installers use for *"the following
   applications are using files that need to be updated"* — which names the
   processes holding the surviving files. It reports them and closes just
   those:
   ```
   Something is holding files (dev): VS Code (pid 4821)
   Closing just those...
   ```
   A directory that is another process's *working directory* also blocks
   removal without holding any file handle, and the Restart Manager can't see
   that; a scoped search covers it, matching processes by where they live
   rather than by name.
3. **Last resort.** Only if the targeted close didn't free the tree does
   seedling force-close every Python and VS Code process, which is what it
   used to do unconditionally.

Earlier versions ran step 3 up front, every time — so removing a throwaway venv
would close an unrelated editor window before establishing anything was wrong.

Matching by **location rather than process name** matters in both directions.
An unrelated system Python or an editor window on another project is left
alone; and a process named nothing like Python — a PyQt/PySide app's
`QtWebEngineProcess.exe`, or a `node`/`ffmpeg` binary bundled in a venv — is
still caught, because it lives inside the tree being deleted.

`seed kill-processes` is the manual equivalent, and follows the same
principle: it closes **only seedling's processes by default**, and needs an
explicit `--system` for the machine-wide sweep.

```
seed kill-processes             # only seedling's own processes (default)
seed kill-processes --system    # every python + VS Code on the machine
seed kill-processes <name>      # every process with that name
```

`seed kill-processes all` was the old spelling of `--system` and still works
that way — it is deliberately *not* re-pointed at the narrow mode, since that
would silently change what an existing script does.

### Unsaved work in cloned repos

The commands that can delete cloned repos — `seed purge`, `seed remove-repo`
and `seed remove-user` — check each repo first for work that exists nowhere
else, and name what's at risk:

```
2 repo(s) contain work that deleting them would destroy:
  - analysis: 1 uncommitted change, 1 untracked file
  - etl: 1 untracked file
```

That covers uncommitted changes, untracked files, and commits never pushed to
a remote. It runs **before** the confirmation prompt and before the process
kill that closes VS Code, so you see it while you can still act on it.

It reports rather than blocks. `-y` still proceeds — scripted teardowns keep
working — but the warning is printed either way, so it lands in the terminal
and in seedling's run log. `--preview` shows it too.

`seed purge --keep-repos` and `seed purge-and-reinstall` don't warn: they move
repos to safety and restore them, so nothing is at risk.

Two things it cannot see, and does not claim to: **unsaved editor buffers**
(nothing has written them to disk yet, and the process kill closes VS Code),
and **unpushed commits on a branch with no upstream** (there's no remote to
compare against). Treat a clean result as "git found nothing", not as
"verified safe".

---

## Non-interactive mode & previews

Every destructive command (`remove-python`, `remove-venv`, `remove-venv-all`,
`remove-repo`, `remove-user`, `purge`, `kill-processes`) supports three
shared flags:

- `-y` / `--yes` — skip the confirmation prompt and proceed.
  (`SEEDLING_YES=1` is the environment equivalent.)
- `--preview` — print exactly what would be deleted (full paths; for
  `kill-processes`, the actual matching processes running right now), then
  exit without changing anything.
- `--non-interactive` — never wait for keyboard input. Anything that would
  have prompted aborts safely instead, unless `-y` was also given.
  (`SEEDLING_NONINTERACTIVE=1` is the environment equivalent.) This is the
  mode for scripts and CI, where a forgotten prompt would otherwise hang
  the job forever.

## Command logging

Every `seed` invocation appends to a daily log file under
`~/seedling/system/logs/` (e.g. `seed-2026-07-05.log`):

- the exact command line and a timestamp,
- everything the command printed — stdout *and* stderr, including the
  tagged `[uv]`/`[git]` output — with ANSI color codes stripped, so the
  logs are plain text end to end (shippable to a server, greppable, and
  displayable anywhere with no escape-code handling),
- and the exit code.

Log files older than 30 days are pruned automatically. Logging never
interferes with the command itself: if the log file can't be written, the
command carries on unlogged. Set `SEEDLING_NO_LOG=1` to disable logging for
a given call (the shell integration uses this itself for its startup
`default_venv` query, so opening a terminal doesn't spam the log).

---

## Download verification

The two things seedling downloads itself as plain archives — portable
MinGit on Windows and VS Code — are verified against their publishers'
SHA-256 checksums before extraction (GitHub's release-asset digest for
MinGit; VS Code's update API hash for VS Code). A checksum mismatch deletes
the download and aborts with an explanation. If no checksum could be
obtained (e.g. the metadata endpoint is blocked on your network), the
download proceeds but says so explicitly. uv and Python interpreters are
installed by uv's own tooling, which does its own verification.

---
