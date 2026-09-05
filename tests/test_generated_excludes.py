from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature.cli import main
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("existing_ignore", ["none", "tracked", "local"])
def test_create_and_merge_preserve_tracked_ignore_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_ignore: str
) -> None:
    init_git_repo(tmp_path)
    ignore_text = "# User rules\n.cache/\n"
    if existing_ignore == "tracked":
        (tmp_path / ".gitignore").write_text(ignore_text, encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-m", "Ignore cache"], cwd=tmp_path, check=True)
    if existing_ignore == "local":
        (tmp_path / ".git/info/exclude").write_text(
            ignore_text + ".new-feature/\n.worktrees/\n*.local.toml\n", encoding="utf-8"
        )
    monkeypatch.chdir(tmp_path)

    assert main(["create", "demo", "--no-agent"]) == 0
    assert not subprocess.check_output(["git", "status", "--porcelain"], text=True)
    if existing_ignore == "tracked":
        assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ignore_text
    else:
        assert not (tmp_path / ".gitignore").exists()
    worktree = tmp_path / ".worktrees/demo"
    (worktree / "prefs.local.toml").write_text("enabled = true\n", encoding="utf-8")
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=worktree, text=True)
    (worktree / "feature.txt").write_text("complete\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Add feature"], cwd=worktree, check=True)
    assert main(["merge", "demo"]) == 0
    assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == "complete\n"
