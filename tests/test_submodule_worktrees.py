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


def test_teardown_protects_ignored_submodule_files(tmp_path: Path, monkeypatch, capsys) -> None:
    from new_feature.cli import main
    from tests.conftest import init_git_repo

    dependency = tmp_path / "dependency"
    dependency.mkdir()
    init_git_repo(dependency)
    (dependency / ".gitignore").write_text("drafts/\n__pycache__/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=dependency, check=True)
    subprocess.run(["git", "commit", "-m", "Ignore local files"], cwd=dependency, check=True)
    project = tmp_path / "project"
    project.mkdir()
    init_git_repo(project)
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "add", str(dependency), "vendor/dependency"],
        cwd=project,
        check=True,
    )
    subprocess.run(["git", "commit", "-am", "Add dependency"], cwd=project, check=True)
    monkeypatch.chdir(project)
    assert main(["create", "demo", "--no-agent"]) == 0
    assert main(["teardown", "demo", "--dry-run"]) == 0
    worktree = project / ".worktrees/demo"
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "update", "--init"], cwd=worktree, check=True
    )
    module = worktree / "vendor/dependency"
    (module / "drafts").mkdir()
    (module / "drafts/note").write_text("valuable", encoding="utf-8")
    (module / "__pycache__").mkdir()
    (module / "__pycache__/cache.pyc").write_bytes(b"cache")
    assert main(["teardown", "demo"]) == 1
    assert "ignored files" in capsys.readouterr().err
    assert main(["merge", "demo", "--include-untracked"]) == 1
    assert "tracked path" in capsys.readouterr().err
    (project / "vendor/dependency/drafts").mkdir()
    (project / "vendor/dependency/drafts/note").write_text("valuable", encoding="utf-8")
    assert main(["teardown", "demo"]) == 0
    assert not worktree.exists()
    assert (project / "vendor/dependency/drafts/note").read_text() == "valuable"
