"""Timeless-comment CLI accepts domain words and inspects actual prose."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("source", "status"),
    [
        ("# Create a new connection using the compatible fallback.\n", 0),
        ('text = "# previously configured"\n', 0),
        ('text = """previously configured"""\n', 0),
        ('"""Service is now configured."""\n', 1),
        ('def f(): """Previously configured."""\n', 1),
        ('text = "previously configured"  # Current setting.\n', 0),
        ('text = "# temporal-ok"  # Previously configured.\n', 1),
        ('"""Previously configured."""  # allow: timeless-comments\n', 0),
        ("# TODO: previously configured.\n", 0),
    ],
)
def test_timeless_comment_cli(tmp_path: Path, source: str, status: int) -> None:
    source_path = tmp_path / "example.py"
    source_path.write_text(source)
    hook = Path(__file__).resolve().parents[1] / "scripts/prek_hooks/check_timeless_comments.py"
    result = subprocess.run(
        [sys.executable, str(hook), str(source_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == status, result.stdout + result.stderr
    if status:
        assert f"{source_path}:1:" in result.stdout
