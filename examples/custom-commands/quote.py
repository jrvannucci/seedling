# Registered in custom-commands.toml as `script = "quote.py"`.
# Try it: seed config set custom_commands ./examples/custom-commands/custom-commands.toml
#         seed custom quote
#
# The case a flat TOML `run` list can't express: real logic (random.choice)
# and a companion data file resolved relative to the script itself via
# Path(__file__).parent -- see docs/CUSTOM-COMMANDS.md.
import random
import sys
from pathlib import Path


def main(argv):
    lines = [ln for ln in (Path(__file__).parent / "quotes.txt")
             .read_text(encoding="utf-8").splitlines() if ln.strip()]
    print(random.choice(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
