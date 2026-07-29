from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING

import pytest

from new_feature import cli
from new_feature.config import ProjectConfig
from new_feature.errors import NewFeatureError
from new_feature.manifest import FeatureRecord, Manifest

if TYPE_CHECKING:
    from pathlib import Path


def test_failed_push_keeps_the_merge_recorded_and_can_be_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = FeatureRecord(
        name="my-feature",
        slug="my-feature",
        branch="feature/my-feature",
        worktree=".worktrees/my-feature",
        target_branch="main",
        status="active",
        created_at="2026-07-10T12:00:00Z",
        env={},
    )
    manifest = Manifest(features={"my_feature": record})
    merged: list[str] = []
    pushed: list[str] = []

    monkeypatch.setattr(cli, "load_project_config", lambda _root: ProjectConfig(push=True))
    monkeypatch.setattr(cli, "manifest_lock", lambda _root: nullcontext())
    monkeypatch.setattr(cli, "load_manifest", lambda _root: manifest)
    monkeypatch.setattr(cli, "run_commands", lambda _commands, *, cwd, env, failure_log: None)
    monkeypatch.setattr(cli, "worktree_is_clean", lambda _worktree: True)
    monkeypatch.setattr(cli, "ensure_merge_is_clean", lambda _root, *, branch, target_branch: None)
    monkeypatch.setattr(
        cli,
        "begin_merge_without_commit",
        lambda _root, *, branch, target_branch: merged.append(branch),
    )
    monkeypatch.setattr(cli, "commit_merge", lambda _root, *, name: None)
    monkeypatch.setattr(cli, "resolve_revision", lambda _root, _ref: "target-before")

    def push(_root: Path, *, target_branch: str) -> None:
        pushed.append(target_branch)
        if len(pushed) == 1:
            raise NewFeatureError("push failed")

    monkeypatch.setattr(cli, "push_target", push)
    monkeypatch.setattr(cli, "save_manifest", lambda _root, _manifest: None)

    with pytest.raises(NewFeatureError, match="push failed"):
        cli._merge(tmp_path, "my-feature")
    assert record.status == "merged"

    assert cli._merge(tmp_path, "my-feature") == 0
    assert merged == ["feature/my-feature"]
    assert pushed == ["main", "main"]
