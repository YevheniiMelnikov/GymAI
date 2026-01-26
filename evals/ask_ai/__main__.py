from __future__ import annotations

import sys
from argparse import ArgumentParser

from evals.ask_ai import config

config.apply_env_defaults()

from evals.ask_ai.runner import main  # noqa: E402


def _parse_args() -> str:
    parser = ArgumentParser(description="Ask AI eval runner")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "cognify"],
        help="run evals or only sync profile dataset",
    )
    args = parser.parse_args()
    return str(args.command)


def _entry() -> int:
    command = _parse_args()
    return main(command)


if __name__ == "__main__":
    sys.exit(_entry())
