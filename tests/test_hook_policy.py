from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature.gitignore import ensure_generated_paths_ignored
from new_feature.hook_policy import (
    EditRequest,
    WorktreeAction,
    WorktreeRequest,
    evaluate_worktree_policy,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_policy_denies_a_normalized_target_branch_edit(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)

    denial = evaluate_worktree_policy(EditRequest((tmp_path / "README.md",)), cwd=tmp_path)

    assert denial is not None
    assert "Direct agent edits" in denial.reason
    assert "target branch 'main'" in denial.reason


def test_policy_denies_a_normalized_direct_worktree_operation(tmp_path: Path) -> None:
    denial = evaluate_worktree_policy(WorktreeRequest(WorktreeAction("add")), cwd=tmp_path)

    assert denial is not None
    assert "git worktree add" in denial.reason
    assert "new-feature <feature-name>" in denial.reason


def test_policy_allows_bootstrap_until_the_first_commit(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    request = EditRequest((tmp_path / "README.md",))
    assert evaluate_worktree_policy(request, cwd=tmp_path) is None
    init_git_repo(tmp_path)
    assert evaluate_worktree_policy(request, cwd=tmp_path) is not None
    subprocess.run(["git", "checkout", "--orphan", "orphan"], cwd=tmp_path, check=True)
    (tmp_path / ".new-feature.toml").write_text('target_branch = "orphan"\n', encoding="utf-8")
    assert evaluate_worktree_policy(request, cwd=tmp_path) is not None


@pytest.mark.parametrize("relative", [False, True])
def test_policy_allows_only_the_ignored_root_sidecar(tmp_path: Path, relative: bool) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    sidecar = tmp_path / ".new-feature.local.toml"
    target = sidecar.relative_to(tmp_path) if relative else sidecar
    assert evaluate_worktree_policy(EditRequest((target,)), cwd=tmp_path) is not None
    ensure_generated_paths_ignored(tmp_path)
    assert evaluate_worktree_policy(EditRequest((target,)), cwd=tmp_path) is None
    assert evaluate_worktree_policy(EditRequest((target, tmp_path / "README.md")), cwd=tmp_path) is not None
    nested = tmp_path / "nested/.new-feature.local.toml"
    assert evaluate_worktree_policy(EditRequest((nested,)), cwd=tmp_path) is not None
    sidecar.write_text("push = false\n", encoding="utf-8")
    subprocess.run(["git", "add", "--force", sidecar.name], cwd=tmp_path, check=True)
    assert evaluate_worktree_policy(EditRequest((target,)), cwd=tmp_path) is not None


def test_policy_rejects_a_sidecar_symlink_to_tracked_source(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    source = tmp_path / "config-source.toml"
    source.write_text("push = false\n", encoding="utf-8")
    subprocess.run(["git", "add", source.name], cwd=tmp_path, check=True)
    ensure_generated_paths_ignored(tmp_path)
    sidecar = tmp_path / ".new-feature.local.toml"
    sidecar.symlink_to(source)
    assert evaluate_worktree_policy(EditRequest((sidecar,)), cwd=tmp_path) is not None
