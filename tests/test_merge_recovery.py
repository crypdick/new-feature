from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature import cli
from new_feature.errors import NewFeatureError
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


def test_successful_git_noop_cannot_record_or_push_a_merge(tmp_path: Path, monkeypatch, capsys):
    from new_feature.manifest import load_manifest

    init_git_repo(tmp_path, "[tool.new-feature]\npush=true\nauto-teardown=true\n")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["create", "demo", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees/demo"
    (worktree / "feature.txt").write_text("feature", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Feature"], cwd=worktree, check=True)
    before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path)
    monkeypatch.setattr(cli, "merge_feature_branch", lambda *_args, **_kwargs: None)
    pushes = []
    monkeypatch.setattr(cli, "push_target", lambda *_args, **_kwargs: pushes.append(True))
    assert cli.main(["merge", "demo"]) == 1
    assert "did not integrate" in capsys.readouterr().err
    assert load_manifest(tmp_path).features["demo"].status == "active"
    assert pushes == []
    assert worktree.exists()
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path) == before


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
    from new_feature.manifest import load_manifest

    init_git_repo(tmp_path, "[tool.new-feature]\npush=true\n")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["my-feature", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees/my-feature"
    (worktree / "feature.txt").write_text("feature\n")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Feature"], cwd=worktree, check=True)
    pushed = []

    def push(_root: Path, *, target_branch: str) -> None:
        pushed.append(target_branch)
        if len(pushed) == 1:
            raise NewFeatureError("push failed")

    monkeypatch.setattr(cli, "push_target", push)
    with pytest.raises(NewFeatureError, match="push failed"):
        cli._merge(tmp_path, "my-feature")
    assert load_manifest(tmp_path).features["my_feature"].status == "merged"
    merged = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path)
    assert cli._merge(tmp_path, "my-feature") == 0
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path) == merged
    assert pushed == ["main", "main"]


@pytest.mark.parametrize("help_flag", ["--help", "-h"])
def test_merge_help_after_feature_never_runs_lifecycle(monkeypatch, capsys, help_flag):
    from new_feature import cli

    def unexpected_dispatch(*_args, **_kwargs):
        pytest.fail("help must exit before repository lookup or lifecycle execution")

    monkeypatch.setattr(cli, "_run", unexpected_dispatch)
    with pytest.raises(SystemExit) as exc:
        cli.main(["merge", "my-feature", help_flag])
    assert exc.value.code == 0
    assert "check and merge" in capsys.readouterr().out.lower()
