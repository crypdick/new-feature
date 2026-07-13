from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


def atomic_text_write(path: Path, content: str, *, default_mode: int) -> None:
    """Write text durably without exposing a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else default_mode
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        _write_temporary_file(descriptor, content)
        temporary_path.chmod(mode)
        temporary_path.replace(path)
        _sync_directory(path.parent)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _write_temporary_file(descriptor: int, content: str) -> None:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
