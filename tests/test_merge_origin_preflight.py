"""With push enabled, merge refuses origin problems before pre-merge checks or target changes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from new_feature import cli
from tests.test_ignore_dirty import _git, _push_enabled_repo

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _repo_with_check_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    repo, upstream = _push_enabled_repo(tmp_path, monkeypatch)
    marker = tmp_path / "checks-ran"
    (repo / ".new-feature.local.toml").write_text(f'pre_merge = ["touch {marker}"]\n', encoding="utf-8")
    _git(upstream, "pull", "--quiet")
    return repo, upstream, marker


def _publish(upstream: Path, name: str, content: str) -> None:
    (upstream / name).write_text(content, encoding="utf-8")
    _git(upstream, "add", name)
    _git(upstream, "commit", "--quiet", "-m", f"Publish {name}")
    _git(upstream, "push", "--quiet")


def test_merge_refuses_conflict_with_origin_before_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, upstream, marker = _repo_with_check_marker(tmp_path, monkeypatch)
    worktree = repo / ".worktrees" / "my-feature"
    (worktree / "notes.txt").write_text("feature\n", encoding="utf-8")
    _git(worktree, "commit", "--quiet", "-am", "Feature notes edit")
    _publish(upstream, "notes.txt", "published\n")
    original_head = _git(repo, "rev-parse", "HEAD")

    assert cli.main(["merge", "my-feature"]) == 1

    assert "feature branch conflicts with the target branch" in capsys.readouterr().err
    assert not marker.exists()
    assert _git(repo, "rev-parse", "HEAD") == original_head


def test_merge_refuses_diverged_target_before_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, upstream, marker = _repo_with_check_marker(tmp_path, monkeypatch)
    _publish(upstream, "published.txt", "published\n")
    (repo / "local.txt").write_text("local\n", encoding="utf-8")
    _git(repo, "add", "local.txt")
    _git(repo, "commit", "--quiet", "-m", "Unpushed local commit")

    assert cli.main(["merge", "my-feature"]) == 1

    assert "target branch 'main' has diverged from origin/main" in capsys.readouterr().err
    assert not marker.exists()


def test_merge_refuses_unusable_push_destination_before_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _upstream, marker = _repo_with_check_marker(tmp_path, monkeypatch)
    _git(repo, "remote", "set-url", "--push", "origin", str(tmp_path / "missing.git"))
    original_head = _git(repo, "rev-parse", "HEAD")

    assert cli.main(["merge", "my-feature"]) == 1

    assert "cannot push main to origin" in capsys.readouterr().err
    assert not marker.exists()
    assert _git(repo, "rev-parse", "HEAD") == original_head


def test_merge_onto_published_commits_passes_preflight_and_pushes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, upstream, marker = _repo_with_check_marker(tmp_path, monkeypatch)
    _publish(upstream, "published.txt", "published\n")

    assert cli.main(["merge", "my-feature"]) == 0

    assert marker.exists()
    assert (repo / "published.txt").read_text(encoding="utf-8") == "published\n"
    assert _git(repo, "rev-parse", "HEAD") == _git(repo, "rev-parse", "origin/main")
