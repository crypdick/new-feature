from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from new_feature import git
from new_feature.cli import main
from new_feature.errors import NewFeatureError
from new_feature.git import remove_worktree_and_branch
from new_feature.manifest import load_manifest


def test_remove_worktree_and_branch_recovers_when_git_removes_only_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "feature"
    worktree.mkdir()
    calls: list[tuple[str, ...]] = []

    def fake_git(_cwd: Path, *args: str, capture: bool = False):
        del capture
        calls.append(args)
        if args[:2] == ("worktree", "remove"):
            worktree.rmdir()
            raise NewFeatureError("git command failed: worktree remove")
        return subprocess.CompletedProcess(["git", *args], 0, stdout="")

    monkeypatch.setattr(git, "_git", fake_git)

    remove_worktree_and_branch(tmp_path, branch="feature", worktree=worktree, force=False)

    assert calls == [
        ("worktree", "remove", str(worktree)),
        ("worktree", "prune"),
        ("branch", "-d", "feature"),
    ]


def test_remove_worktree_and_branch_preserves_a_failed_removal_when_worktree_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "feature"
    worktree.mkdir()

    def fake_git(_cwd: Path, *args: str, capture: bool = False):
        del _cwd, args, capture
        raise NewFeatureError("git command failed: worktree remove")

    monkeypatch.setattr(git, "_git", fake_git)

    with pytest.raises(NewFeatureError, match="worktree remove"):
        remove_worktree_and_branch(tmp_path, branch="feature", worktree=worktree, force=False)

    assert worktree.exists()


def test_merge_rejects_conflicts_before_changing_the_target_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)
    assert main(["my-feature", "--no-agent"]) == 0
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "ignore generated state"], cwd=tmp_path, check=True)
    worktree = tmp_path / ".worktrees" / "my-feature"
    (worktree / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "feature change"], cwd=worktree, check=True)
    (tmp_path / "feature.txt").write_text("main\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "main change"], cwd=tmp_path, check=True)

    assert main(["merge", "my-feature"]) == 1
    assert "feature branch conflicts with the target branch" in capsys.readouterr().err
    assert (
        subprocess.run(["git", "rev-parse", "--verify", "MERGE_HEAD"], cwd=tmp_path, check=False).returncode
        != 0
    )
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=tmp_path, text=True) == ""
    assert load_manifest(tmp_path).features["my_feature"].status == "active"


def test_teardown_reports_a_missing_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)
    assert main(["my-feature", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees" / "my-feature"
    subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=tmp_path, check=True)

    assert main(["teardown", "my-feature"]) == 1
    assert "feature worktree is missing" in capsys.readouterr().err
    assert "my_feature" in load_manifest(tmp_path).features


def test_doctor_repair_removes_a_missing_worktree_with_a_merged_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)
    assert main(["my-feature", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees" / "my-feature"
    subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=tmp_path, check=True)

    assert main(["doctor", "--repair"]) == 0
    assert "removed missing worktree and merged branch my-feature" in capsys.readouterr().out
    assert load_manifest(tmp_path).features == {}
    branches = subprocess.check_output(["git", "branch", "--list", "my-feature"], cwd=tmp_path, text=True)
    assert branches.strip() == ""
