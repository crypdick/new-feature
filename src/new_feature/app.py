"""Provide the installed command-line entry point."""

from __future__ import annotations

import signal
import sys

from new_feature.cli import main as cli_main


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface with optional explicit arguments."""

    def terminate(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    previous_handlers = {
        signum: signal.signal(signum, terminate) for signum in (signal.SIGHUP, signal.SIGTERM)
    }
    try:
        return cli_main(sys.argv[1:] if argv is None else argv)
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
