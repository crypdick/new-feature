from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature import cli
from new_feature.cli_parser import parse_args
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _repo_with_feature_commit(repo: Path, monkeypatch: pytest.MonkeyPatch, *, config: str = "") -> Path:
    init_git_repo(repo, f'[project]\nname = "demo"\n{config}')
    (repo / "notes.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-m", "notes")
    monkeypatch.chdir(repo)
    assert cli.main(["my-feature", "--no-agent"]) == 0
    worktree = repo / ".worktrees" / "my-feature"
    (worktree / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "Feature")
    return worktree


def _make_target_dirty(repo: Path) -> None:
    (repo / "notes.txt").write_text("edited\n", encoding="utf-8")
    (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(repo, "add", "staged.txt")
    (repo / "scratch.txt").write_text("untracked\n", encoding="utf-8")


DIRTY_STATUS = " M notes.txt\nA  staged.txt\n?? scratch.txt\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["merge", "--ignore-dirty", "demo"],
        ["merge", "demo", "--ignore-dirty"],
    ],
)
def test_merge_ignore_dirty_is_a_wrapper_option(argv: list[str]) -> None:
    args = parse_args(argv)
    assert args.ignore_dirty is True
    assert args.git_args == []


def test_merge_without_flag_points_to_ignore_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo_with_feature_commit(tmp_path, monkeypatch)
    _make_target_dirty(tmp_path)

    assert cli.main(["merge", "my-feature"]) == 1
    assert "--ignore-dirty" in capsys.readouterr().err


def test_merge_ignore_dirty_merges_and_restores_target_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_feature_commit(tmp_path, monkeypatch)
    _make_target_dirty(tmp_path)

    assert cli.main(["merge", "--ignore-dirty", "my-feature"]) == 0

    assert _git(tmp_path, "log", "-1", "--format=%s") == "Merge feature my-feature\n"
    assert _git(tmp_path, "ls-tree", "--name-only", "HEAD").split() == [
        "feature.txt",
        "notes.txt",
        "pyproject.toml",
    ]
    assert _git(tmp_path, "show", "HEAD:notes.txt") == "base\n"
    assert _git(tmp_path, "status", "--porcelain") == DIRTY_STATUS
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "edited\n"
    assert not _git(tmp_path, "stash", "list")


def test_merge_ignore_dirty_restores_target_changes_after_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_feature_commit(tmp_path, monkeypatch, config='\n[tool.new-feature]\npost_merge = ["false"]\n')
    original_head = _git(tmp_path, "rev-parse", "HEAD")
    _make_target_dirty(tmp_path)

    assert cli.main(["merge", "--ignore-dirty", "my-feature"]) == 1

    assert _git(tmp_path, "rev-parse", "HEAD") == original_head
    assert _git(tmp_path, "status", "--porcelain") == DIRTY_STATUS
    assert not _git(tmp_path, "stash", "list")


def test_merge_ignore_dirty_refuses_overlapping_edits_before_stashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree = _repo_with_feature_commit(tmp_path, monkeypatch)
    (worktree / "notes.txt").write_text("feature edit\n", encoding="utf-8")
    _git(worktree, "commit", "-am", "Edit notes")
    original_head = _git(tmp_path, "rev-parse", "HEAD")
    _make_target_dirty(tmp_path)

    assert cli.main(["merge", "--ignore-dirty", "my-feature"]) == 1

    assert "uncommitted target changes touch paths this merge changes: notes.txt;" in capsys.readouterr().err
    assert _git(tmp_path, "rev-parse", "HEAD") == original_head
    assert _git(tmp_path, "status", "--porcelain") == DIRTY_STATUS
    assert not _git(tmp_path, "stash", "list")


def test_merge_ignore_dirty_refuses_untracked_file_the_feature_adds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo_with_feature_commit(tmp_path, monkeypatch)
    (tmp_path / "feature.txt").write_text("local copy\n", encoding="utf-8")

    assert cli.main(["merge", "--ignore-dirty", "my-feature"]) == 1

    assert "touch paths this merge changes: feature.txt;" in capsys.readouterr().err
    assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == "local copy\n"
    assert not _git(tmp_path, "stash", "list")


def test_merge_ignore_dirty_keeps_stash_when_a_concurrent_writer_blocks_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo_with_feature_commit(tmp_path, monkeypatch)
    _make_target_dirty(tmp_path)
    publish = cli._publish

    def publish_after_another_writer_creates_scratch(*args: object) -> None:
        (tmp_path / "scratch.txt").write_text("other writer\n", encoding="utf-8")
        publish(*args)

    monkeypatch.setattr(cli, "_publish", publish_after_another_writer_creates_scratch)

    assert cli.main(["merge", "--ignore-dirty", "my-feature"]) == 1

    assert _git(tmp_path, "log", "-1", "--format=%s") == "Merge feature my-feature\n"
    stash = _git(tmp_path, "stash", "list", "--format=%H").strip()
    assert _git(tmp_path, "show", f"{stash}:notes.txt") == "edited\n"
    assert f"git stash apply --index {stash}" in capsys.readouterr().err


def _push_enabled_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    remote = tmp_path / "remote.git"
    upstream = tmp_path / "upstream"
    subprocess.run(["git", "init", "--bare", "-b", "main", remote], check=True)
    init_git_repo(repo)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")
    _repo_with_feature_commit(repo, monkeypatch, config="\n[tool.new-feature]\npush = true\n")
    _git(repo, "push")
    subprocess.run(["git", "clone", str(remote), str(upstream)], check=True)
    _git(upstream, "config", "user.email", "test@example.com")
    _git(upstream, "config", "user.name", "Test User")
    return repo, upstream


def test_merge_ignore_dirty_checks_overlap_against_origin_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, upstream = _push_enabled_repo(tmp_path, monkeypatch)
    (upstream / "notes.txt").write_text("published edit\n", encoding="utf-8")
    _git(upstream, "commit", "-am", "Published notes edit")
    _git(upstream, "push")
    _make_target_dirty(repo)

    assert cli.main(["merge", "--ignore-dirty", "my-feature"]) == 1

    assert "touch paths this merge changes: notes.txt;" in capsys.readouterr().err
    assert _git(repo, "status", "--porcelain") == DIRTY_STATUS


def test_merge_ignore_dirty_with_unpushed_target_commits_merges_and_pushes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _upstream = _push_enabled_repo(tmp_path, monkeypatch)
    (repo / "local.txt").write_text("unpushed\n", encoding="utf-8")
    _git(repo, "add", "local.txt")
    _git(repo, "commit", "-m", "Unpushed local commit")
    _make_target_dirty(repo)

    assert cli.main(["merge", "--ignore-dirty", "my-feature"]) == 0

    assert _git(repo, "status", "--porcelain") == DIRTY_STATUS
    assert _git(repo, "rev-parse", "HEAD") == _git(repo, "rev-parse", "origin/main")


def test_create_ignore_dirty_pulls_without_touching_target_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    upstream = tmp_path / "upstream"
    repo.mkdir()
    init_git_repo(repo, '[project]\nname = "demo"\n\n[tool.new-feature]\npull_before_create = true\n')
    (repo / "notes.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-m", "notes")
    subprocess.run(["git", "init", "--bare", remote], check=True)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(upstream)], check=True)
    _git(upstream, "config", "user.email", "test@example.com")
    _git(upstream, "config", "user.name", "Test User")
    (upstream / "upstream.txt").write_text("latest\n", encoding="utf-8")
    _git(upstream, "add", "upstream.txt")
    _git(upstream, "commit", "-m", "upstream")
    _git(upstream, "push")
    monkeypatch.chdir(repo)
    _make_target_dirty(repo)

    assert cli.main(["refused", "--no-agent"]) == 1
    assert "--ignore-dirty" in capsys.readouterr().err

    assert cli.main(["my-feature", "--no-agent", "--ignore-dirty"]) == 0

    assert (repo / "upstream.txt").read_text(encoding="utf-8") == "latest\n"
    assert (repo / ".worktrees" / "my-feature" / "upstream.txt").read_text(encoding="utf-8") == "latest\n"
    assert not (repo / ".worktrees" / "my-feature" / "scratch.txt").exists()
    assert _git(repo, "status", "--porcelain") == DIRTY_STATUS


def test_merge_ignore_dirty_on_clean_target_merges_normally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_feature_commit(tmp_path, monkeypatch)

    assert cli.main(["merge", "--ignore-dirty", "my-feature"]) == 0

    assert _git(tmp_path, "log", "-1", "--format=%s") == "Merge feature my-feature\n"
    assert not _git(tmp_path, "status", "--porcelain")
    assert not _git(tmp_path, "stash", "list")


def test_merge_ignore_dirty_leaves_other_stash_entries_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_feature_commit(tmp_path, monkeypatch)
    (tmp_path / "notes.txt").write_text("someone else's work\n", encoding="utf-8")
    _git(tmp_path, "stash", "push", "--message", "unrelated")
    _make_target_dirty(tmp_path)

    assert cli.main(["merge", "--ignore-dirty", "my-feature"]) == 0

    assert _git(tmp_path, "status", "--porcelain") == DIRTY_STATUS
    assert _git(tmp_path, "stash", "list", "--format=%gs") == "On main: unrelated\n"
    assert _git(tmp_path, "show", "stash@{0}:notes.txt") == "someone else's work\n"


def test_merge_ignore_dirty_tolerates_stash_entry_dropped_during_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_feature_commit(
        tmp_path, monkeypatch, config='\n[tool.new-feature]\npost_merge = ["git stash clear"]\n'
    )
    _make_target_dirty(tmp_path)

    assert cli.main(["merge", "--ignore-dirty", "my-feature"]) == 0

    assert _git(tmp_path, "log", "-1", "--format=%s") == "Merge feature my-feature\n"
    assert _git(tmp_path, "status", "--porcelain") == DIRTY_STATUS


def test_merge_ignore_dirty_reports_merge_and_restore_failures_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo_with_feature_commit(
        tmp_path,
        monkeypatch,
        config='\n[tool.new-feature]\npost_merge = ["echo collision > scratch.txt; exit 1"]\n',
    )
    _make_target_dirty(tmp_path)

    assert cli.main(["merge", "--ignore-dirty", "my-feature"]) == 1

    error = capsys.readouterr().err
    stash = _git(tmp_path, "stash", "list", "--format=%H").strip()
    assert "merge failed and the target checkout could not be restored" in error
    assert f"git stash apply --index {stash}" in error
    assert _git(tmp_path, "show", f"{stash}^3:scratch.txt") == "untracked\n"


def test_merge_ignore_dirty_keeps_stash_entries_pushed_during_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_feature_commit(tmp_path, monkeypatch)
    _make_target_dirty(tmp_path)
    publish = cli._publish

    def publish_after_another_process_stashes(*args: object) -> None:
        (tmp_path / "other.txt").write_text("other\n", encoding="utf-8")
        _git(tmp_path, "stash", "push", "--include-untracked", "--message", "concurrent")
        publish(*args)

    monkeypatch.setattr(cli, "_publish", publish_after_another_process_stashes)

    assert cli.main(["merge", "--ignore-dirty", "my-feature"]) == 0

    assert _git(tmp_path, "status", "--porcelain") == DIRTY_STATUS
    assert _git(tmp_path, "stash", "list", "--format=%gs") == "On main: concurrent\n"


def test_merge_ignore_dirty_still_refuses_changes_git_cannot_stash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    library = tmp_path / "library"
    library.mkdir()
    init_git_repo(library)
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo_with_feature_commit(repo, monkeypatch)
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "add", str(library), "library"],
        cwd=repo,
        check=True,
    )
    _git(repo, "commit", "-m", "Add library")
    (repo / "library" / "README.md").write_text("dirty submodule\n", encoding="utf-8")

    assert cli.main(["merge", "--ignore-dirty", "my-feature"]) == 1

    assert "target checkout has uncommitted changes" in capsys.readouterr().err
    assert not _git(repo, "stash", "list")
    assert (repo / "library" / "README.md").read_text(encoding="utf-8") == "dirty submodule\n"


def test_merge_ignore_dirty_refuses_when_custom_git_args_hide_a_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree = _repo_with_feature_commit(tmp_path, monkeypatch)
    (worktree / "notes.txt").write_text("feature edit\n", encoding="utf-8")
    _git(worktree, "commit", "-am", "Feature notes edit")
    (tmp_path / "notes.txt").write_text("target edit\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "Target notes edit")
    original_head = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "scratch.txt").write_text("untracked\n", encoding="utf-8")

    assert cli.main(["merge", "--ignore-dirty", "my-feature", "--no-ff"]) == 1

    assert "--ignore-dirty cannot predict which paths the merge changes" in capsys.readouterr().err
    assert _git(tmp_path, "rev-parse", "HEAD") == original_head
    assert _git(tmp_path, "status", "--porcelain") == "?? scratch.txt\n"
    assert not _git(tmp_path, "stash", "list")
