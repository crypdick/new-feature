"""Timestamps and diagnostic paths for managed-feature lifecycle commands."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 - package-wide beartype resolves annotations at runtime


def now() -> str:
    """Return a UTC timestamp in the manifest's canonical format."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def merge_failure_log(root: Path, slug: str, *, phase: str) -> Path:
    """Return a unique retained-output path for one merge-check phase."""
    timestamp = now().replace(":", "-")
    return (
        root
        / ".new-feature"
        / "diagnostics"
        / "merge-failures"
        / slug
        / f"{timestamp}-{os.getpid()}-{phase}.log"
    )
