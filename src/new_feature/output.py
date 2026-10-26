"""Keep command diagnostics separate from machine-readable results."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager, redirect_stdout
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def command_output(*, json_output: bool) -> Iterator[None]:
    """Route Python and inherited subprocess stdout to stderr in JSON mode."""
    if not json_output:
        yield
        return
    # NOTE: README.md documents one JSON document on stdout, including during setup and agent launch.
    sys.stdout.flush()
    saved_stdout = os.dup(1)
    try:
        os.dup2(2, 1)
        with redirect_stdout(sys.stderr):
            yield
    finally:
        sys.stdout.flush()
        os.dup2(saved_stdout, 1)
        os.close(saved_stdout)
