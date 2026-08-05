from __future__ import annotations

from typing import TYPE_CHECKING

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
