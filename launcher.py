#!/usr/bin/env python3
"""Entry point for the pyplaydia graphical launcher."""

from main import main as run_cli
from playdia_player.launcher import choose_command


def main():
    command = choose_command()
    return 0 if command is None else run_cli(command)


if __name__ == "__main__":
    raise SystemExit(main())
