# Registered in custom-commands.toml as `script = "bootstrap.py"`,
# `toplevel = true`.
# Try it: seed config set custom_commands ./examples/custom-commands/custom-commands.toml
#         seed bootstrap          (bare -- toplevel = true)
#         seed custom bootstrap   (also works, namespaced)
#
# The "build a venv, then run a function in it" case. No SDK needed --
# orchestration scripts just shell out to `seed` itself, the same thing
# `seed apply` already does internally. See docs/CUSTOM-COMMANDS.md.
import subprocess
import sys


def main(argv):
    subprocess.run(["seed", "venv", "myproj", "--python", "312"], check=True)
    subprocess.run(["seed", "run", "-n", "myproj", "--",
                     "python", "-m", "myorg_tools.setup", *argv], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
