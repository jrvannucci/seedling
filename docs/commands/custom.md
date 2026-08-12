# Custom commands

![What seed custom does: runs one command entry from custom-commands.toml, either a fixed argv or a script that chains seed subcommands together.](../diagrams/commands-custom.svg)

## `seed custom [name] [args...]`

Runs an organization's own **custom command** — full details, including how
to define one, are in **[CUSTOM-COMMANDS.md](../CUSTOM-COMMANDS.md)**.

Every command is one `[[command]]` entry in `custom-commands.toml`: either
`run = [...]` (a fixed argv, an optional venv) for the simple case, or
`script = "..."` (a `.py`/`.sh`/`.ps1` file next to the TOML file) for
anything that needs real logic or to chain several `seed` subcommands
together — a script orchestrates by shelling out to `seed` itself, the same
thing `seed apply` already does internally, so there's no special API to
learn.

Everything after the command's own name is passed straight through. Run
`seed custom` with no arguments to list what's configured. A command can
also opt into running as bare `seed <name>` — see
[Making a command top-level](../CUSTOM-COMMANDS.md#making-a-command-top-level);
a built-in `seed` command always wins any name collision.

```
seed custom lint
seed custom lint --fix
seed custom
```

A configured `startup_commands` list runs these same commands automatically
in every new shell — see [CUSTOM-COMMANDS.md#running-commands-at-
startup](../CUSTOM-COMMANDS.md#running-commands-at-startup).
