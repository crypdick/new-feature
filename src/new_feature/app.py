"""Provide the installed command-line entry point."""

from __future__ import annotations

import sys

from new_feature.cli import main as cli_main


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface with optional explicit arguments."""
    return cli_main(sys.argv[1:] if argv is None else argv)
