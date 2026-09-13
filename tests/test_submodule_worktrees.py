from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from new_feature.git import create_worktree, remove_worktree_and_branch

if TYPE_CHECKING:
    from pathlib import Path


def test_remove_worktree_and_branch_handles_initialized_submodules(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    dependency = tmp_path / "dependency"
    dependency.mkdir()
    init_git_repo(dependency)
    project = tmp_path / "project"
    project.mkdir()
    init_git_repo(project)
    subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(dependency),
            "vendor/dependency",
        ],
        cwd=project,
        check=True,
    )
    subprocess.run(["git", "commit", "-am", "Add dependency"], cwd=project, check=True)
    worktree = project / ".worktrees" / "my-feature"
    create_worktree(project, branch="my-feature", worktree=worktree, target_branch="main")
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "update", "--init"],
        cwd=worktree,
        check=True,
    )

    remove_worktree_and_branch(project, branch="my-feature", worktree=worktree, force=False)

    assert not worktree.exists()
    branches = subprocess.check_output(["git", "branch", "--list", "my-feature"], cwd=project, text=True)
    assert not branches.strip()
