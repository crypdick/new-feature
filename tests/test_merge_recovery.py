from __future__ import annotations

import subprocess
from contextlib import nullcontext
from typing import TYPE_CHECKING

import pytest

from new_feature import cli
from new_feature.config import ProjectConfig
from new_feature.errors import NewFeatureError
from new_feature.manifest import FeatureRecord, Manifest
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("commit_change", [False, True])
def test_repeat_merge_checks_current_worktree_and_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit_change: bool
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["create", "demo", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees" / "demo"
    note = worktree / "feature.txt"
    note.write_text("first\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Add feature"], cwd=worktree, check=True)
    assert cli.main(["merge", "demo"]) == 0
    assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == "first\n"

    note.write_text("second\n", encoding="utf-8")
    if commit_change:
        subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "Extend feature"], cwd=worktree, check=True)
        assert cli.main(["merge", "demo"]) == 0
        assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == "second\n"
        subprocess.run(["git", "merge-base", "--is-ancestor", "demo", "main"], cwd=tmp_path, check=True)
    else:
        assert cli.main(["merge", "demo"]) == 1
        assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == "first\n"


def test_merge_passes_strategy_options_to_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "conflict.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "conflict.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Add conflict fixture"], cwd=tmp_path, check=True)
    assert cli.main(["create", "demo", "--no-agent"]) == 0

    worktree = tmp_path / ".worktrees" / "demo"
    (worktree / "conflict.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "conflict.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Feature value"], cwd=worktree, check=True)

    (tmp_path / "conflict.txt").write_text("target\n", encoding="utf-8")
    subprocess.run(["git", "add", "conflict.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Target value"], cwd=tmp_path, check=True)

    assert cli.main(["merge", "demo", "-X", "theirs", "--no-edit"]) == 0
    assert (tmp_path / "conflict.txt").read_text(encoding="utf-8") == "feature\n"
    merge_parents = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert len(merge_parents) == 3


def test_merge_honors_ff_only_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["create", "demo", "--no-agent"]) == 0

    worktree = tmp_path / ".worktrees" / "demo"
    (worktree / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Feature value"], cwd=worktree, check=True)
    feature_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=worktree, check=True, capture_output=True, text=True
    ).stdout.strip()

    assert cli.main(["merge", "demo", "--ff-only"]) == 0
    target_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert target_revision == feature_revision


def test_merge_honors_no_commit_and_edit_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_EDITOR", "true")
    assert cli.main(["create", "demo", "--no-agent"]) == 0

    worktree = tmp_path / ".worktrees" / "demo"
    (worktree / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Feature value"], cwd=worktree, check=True)

    assert cli.main(["merge", "demo", "--no-commit", "--no-ff", "--edit"]) == 0
    merge_parents = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert len(merge_parents) == 3


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
    monkeypatch.setattr(cli, "is_branch_merged", lambda _root, *, branch, target_branch: bool(merged))
    monkeypatch.setattr(cli, "ensure_merge_is_clean", lambda _root, *, branch, target_branch: None)
    monkeypatch.setattr(
        cli,
        "merge_feature_branch",
        lambda _root, *, branch, target_branch, git_args=(): merged.append(branch),
    )
    monkeypatch.setattr(cli, "commit_merge", lambda _root, *, name, git_args=(): None)
    monkeypatch.setattr(cli, "merge_in_progress", lambda _root: True)
    monkeypatch.setattr(cli, "checkout_target", lambda *_args, **_kwargs: None)
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
