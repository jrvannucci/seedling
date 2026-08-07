# Custom commands — worked examples

A runnable companion to [docs/CUSTOM-COMMANDS.md](../../docs/CUSTOM-COMMANDS.md).
One file, `custom-commands.toml`, declares every command below (`run` for
the simple ones, `script` for `quote`/`bootstrap`, which need real logic):

```
seed config set custom_commands ./examples/custom-commands/custom-commands.toml
```

Then:

```
seed custom              # lists everything in the file
seed custom data-stack   # run: seed install into the active venv
seed hello Jon           # run, toplevel = true -- runs as bare `seed hello`
seed custom quote        # script: random line from a companion quotes.txt
seed bootstrap           # script, toplevel = true -- runs as bare `seed bootstrap`
```

`bootstrap.py` is illustrative — it shells out to `seed venv` and
`seed run` (the pattern for "build a venv, then run something in it"), but
the `myorg_tools.setup` module it references is a stand-in for whatever your
own package actually is; it won't complete successfully as-is.

**Running one at shell startup.** `motd` in `custom-commands.toml` is meant
to demonstrate [`startup_commands`](../../docs/CUSTOM-COMMANDS.md#running-commands-at-startup)
rather than be typed by hand:

```
seed config set startup_commands motd
```

Open a **new** terminal (the existing one already ran its startup block) and
the message prints automatically, before your prompt — no `seed custom`, no
`seed motd`, nothing to remember. `seed config unset startup_commands` turns
it back off.

**Chaining two commands** so the second only runs if the first succeeds:

```
seed config set startup_commands "data-stack&&motd"
```

Open a new terminal and `data-stack` (the `seed install` example above)
runs first; `motd` only follows it if that install actually succeeded. `,`
still separates independent entries — `"data-stack&&motd, quote"` runs
`quote` regardless of how the chain went.

Unset the rest with `seed config unset custom_commands` /
`seed config unset startup_commands` when you're done trying it out.
