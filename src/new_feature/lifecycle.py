"""Timestamp helpers for managed-feature lifecycle commands."""

from __future__ import annotations

from datetime import UTC, datetime


def now() -> str:
    """Return a UTC timestamp in the manifest's canonical format."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
