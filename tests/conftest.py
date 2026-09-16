from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def init_git_repo(path: Path, pyproject: str | None = None) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    if pyproject is not None:
        (path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
        subprocess.run(["git", "add", "pyproject.toml"], cwd=path, check=True)
    else:
        (path / "README.md").write_text("# demo\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True)


@pytest.fixture(autouse=True)
def clean_git_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in os.environ:
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
