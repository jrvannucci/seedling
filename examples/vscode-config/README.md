# VS Code settings/keybindings — worked example

A runnable companion to [docs/DEPLOYMENT.md#seeding-your-own-settings-and-keybindings](../../docs/DEPLOYMENT.md#seeding-your-own-settings-and-keybindings).

```
seed config set vscode_config_dir ./examples/vscode-config
seed vscode --reinstall
```

`--reinstall` is only needed here because you likely already have an editor
installed from earlier in this walkthrough — both files apply the first
time *any* fresh editor is set up, so on a genuinely new install just
`seed vscode` is enough once `vscode_config_dir` is configured.

What lands where:

- **`settings.json`** is *merged* over seedling's own built-in defaults
  (`vscode_cmd.DEFAULT_SETTINGS`) — this example adds a ruler at 88
  columns, a slightly larger font, a specific theme, and trailing-whitespace
  trimming, while every default seedling already sets (format-on-save,
  telemetry off, ...) survives alongside them.
- **`keybindings.json`** is copied in as-is — there's no built-in default to
  merge with. This example rebinds <kbd>Ctrl+Shift+R</kbd> to "run the
  current Python file in the terminal" while a Python file has focus.

Neither file is ever overwritten once written — reinstalling, updating, or
re-running `seed vscode` leaves a user's own edits to either file alone.

Unset it with `seed config unset vscode_config_dir` when you're done trying
it out (this only stops it from applying to a *future* fresh install; it
doesn't undo what's already been written).
