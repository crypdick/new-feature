from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature.cli import main
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


def create_feature(root: Path, monkeypatch, config: str = "") -> Path:
    init_git_repo(root, "[tool.new-feature]\n" + config)
    (root / ".gitignore").write_text("drafts/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "Ignore drafts"], cwd=root, check=True)
    monkeypatch.chdir(root)
    assert main(["create", "demo", "--no-agent"]) == 0
    return root / ".worktrees/demo"


@pytest.mark.parametrize("flag_first", [False, True])
def test_include_untracked_copies_ignored_and_ordinary_files(tmp_path: Path, monkeypatch, flag_first):
    worktree = create_feature(tmp_path, monkeypatch)
    draft = worktree / "drafts/notes with spaces.md"
    draft.parent.mkdir()
    draft.write_text("valuable draft", encoding="utf-8")
    ordinary = worktree / "local.txt"
    ordinary.write_bytes(b"\x00\xfflocal")
    ordinary.chmod(0o600)
    command = (
        ["merge", "--include-untracked", "demo"] if flag_first else ["merge", "demo", "--include-untracked"]
    )
    assert main(command) == 0
    assert (tmp_path / "drafts/notes with spaces.md").read_text() == "valuable draft"
    assert (tmp_path / "local.txt").read_bytes() == b"\x00\xfflocal"
    assert (tmp_path / "local.txt").stat().st_mode & 0o777 == 0o600
    assert draft.exists()
    assert ordinary.exists()
    assert "local.txt" not in subprocess.check_output(["git", "ls-files"], cwd=tmp_path, text=True)
    assert main(command) == 0


def test_include_safe_to_deletes_generated_and_configured_paths(tmp_path: Path, monkeypatch):
    worktree = create_feature(tmp_path, monkeypatch, 'safe_to_delete=["scratch/", "*.secret"]\n')
    for name in [
        "__pycache__/module.pyc",
        "nested/__pycache__/module.pyc",
        ".venv/bin/python",
        ".pytest_cache/state",
        ".new-feature/state",
        "scratch/work",
        "drafts/local.secret",
    ]:
        path = worktree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("skip", encoding="utf-8")
    (worktree / "drafts/keep.md").write_text("keep", encoding="utf-8")
    assert main(["merge", "demo", "--include-untracked"]) == 0
    assert (tmp_path / "drafts/keep.md").read_text() == "keep"
    assert not (tmp_path / "scratch").exists()
    assert not (tmp_path / ".venv").exists()
    assert not (tmp_path / "nested").exists()
    assert not (tmp_path / "drafts/local.secret").exists()


@pytest.mark.parametrize("collision", ["different", "tracked", "symlink-parent"])
def test_transfer_refuses_conflicts_without_losing_source(tmp_path: Path, monkeypatch, capsys, collision):
    worktree = create_feature(tmp_path, monkeypatch)
    (worktree / "drafts").mkdir()
    source = worktree / "drafts/note"
    source.write_text("feature draft", encoding="utf-8")
    if collision == "symlink-parent":
        external = tmp_path / "outside"
        external.mkdir()
        (tmp_path / "drafts").symlink_to(external, target_is_directory=True)
    else:
        (tmp_path / "drafts").mkdir()
        (tmp_path / "drafts/note").write_text("target draft", encoding="utf-8")
        if collision == "tracked":
            subprocess.run(["git", "add", "--force", "drafts/note"], cwd=tmp_path, check=True)
            subprocess.run(["git", "commit", "-m", "Track target draft"], cwd=tmp_path, check=True)
    before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path)
    assert main(["merge", "demo", "--include-untracked"]) == 1
    assert source.read_text() == "feature draft"
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path) == before
    assert "untracked" in capsys.readouterr().err


def test_merge_without_flag_keeps_ignored_files_only_in_worktree(tmp_path: Path, monkeypatch):
    worktree = create_feature(tmp_path, monkeypatch)
    (worktree / "drafts").mkdir()
    (worktree / "drafts/note").write_text("keep", encoding="utf-8")
    assert main(["merge", "demo"]) == 0
    assert not (tmp_path / "drafts/note").exists()
    assert (worktree / "drafts/note").exists()


def test_failed_post_merge_does_not_transfer_files(tmp_path: Path, monkeypatch):
    worktree = create_feature(tmp_path, monkeypatch, 'post_merge=["exit 1"]\n')
    (worktree / "drafts").mkdir()
    (worktree / "drafts/note").write_text("keep", encoding="utf-8")
    (worktree / "tracked.txt").write_text("feature", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Feature"], cwd=worktree, check=True)
    assert main(["merge", "demo", "--include-untracked"]) == 1
    assert not (tmp_path / "drafts/note").exists()
    assert not (tmp_path / "tracked.txt").exists()
    assert (worktree / "drafts/note").exists()


def test_teardown_removes_only_preserved_local_work_and_disposable_files(tmp_path: Path, monkeypatch, capsys):
    worktree = create_feature(tmp_path, monkeypatch, 'safe_to_delete=["scratch/"]\n')
    for name in ["drafts/note", "scratch/cache", "__pycache__/module.pyc"]:
        path = worktree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep or explicitly discard", encoding="utf-8")
    (worktree / "ordinary.txt").write_text("ordinary local work", encoding="utf-8")
    assert main(["teardown", "demo"]) == 1
    assert "unpreserved" in capsys.readouterr().err
    assert main(["merge", "demo", "--include-untracked"]) == 0
    assert main(["teardown", "demo", "--dry-run"]) == 0
    assert main(["teardown", "demo"]) == 0
    assert not worktree.exists()
    assert (tmp_path / "drafts/note").exists()
    assert (tmp_path / "ordinary.txt").read_text() == "ordinary local work"
    assert not (tmp_path / "scratch").exists()


@pytest.mark.parametrize("change", ["content", "permissions"])
def test_teardown_protects_sources_when_target_copy_changes(tmp_path: Path, monkeypatch, capsys, change):
    worktree = create_feature(tmp_path, monkeypatch)
    (worktree / "drafts").mkdir()
    (worktree / "drafts/note").write_text("keep", encoding="utf-8")
    assert main(["merge", "demo", "--include-untracked"]) == 0
    target = tmp_path / "drafts/note"
    if change == "content":
        target.write_text("edit", encoding="utf-8")
    else:
        target.chmod(0o600)
    assert main(["teardown", "demo"]) == 1
    assert "different file" in capsys.readouterr().err
    assert (worktree / "drafts/note").read_text() == "keep"


def test_transfer_after_git_merge_and_push_retry(tmp_path: Path, monkeypatch, capsys):
    from new_feature import cli
    from new_feature.errors import NewFeatureError

    worktree = create_feature(tmp_path, monkeypatch, "push=true\n")
    (worktree / "drafts").mkdir()
    (worktree / "drafts/note").write_text("keep", encoding="utf-8")
    (worktree / "tracked.txt").write_text("feature", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Feature"], cwd=worktree, check=True)
    pushes = []

    def push(root, *, target_branch):
        pushes.append(target_branch)
        if len(pushes) == 1:
            raise NewFeatureError("push failed")

    monkeypatch.setattr(cli, "push_target", push)
    assert main(["merge", "demo", "--include-untracked"]) == 1
    assert "push failed" in capsys.readouterr().err
    assert (tmp_path / "drafts/note").read_text() == "keep"
    assert (tmp_path / "tracked.txt").read_text() == "feature"
    assert main(["merge", "demo", "--include-untracked"]) == 0
    assert pushes == ["main", "main"]


def test_include_untracked_refuses_dirty_tracked_target(tmp_path: Path, monkeypatch, capsys):
    worktree = create_feature(tmp_path, monkeypatch)
    (tmp_path / ".gitignore").write_text("changed", encoding="utf-8")
    assert main(["merge", "demo", "--include-untracked"]) == 1
    assert "uncommitted tracked changes" in capsys.readouterr().err
    assert worktree.exists()


@pytest.mark.parametrize("source_kind", ["symlink", "repository"])
def test_transfer_refuses_sources_with_ambiguous_ownership(tmp_path: Path, monkeypatch, capsys, source_kind):
    worktree = create_feature(tmp_path, monkeypatch)
    (worktree / "drafts").mkdir()
    source = worktree / "drafts/item"
    if source_kind == "symlink":
        source.symlink_to(worktree / "pyproject.toml")
    else:
        source.mkdir()
        init_git_repo(source)
    assert main(["merge", "demo", "--include-untracked"]) == 1
    assert "requires a regular file" in capsys.readouterr().err
    assert source.exists()


@pytest.mark.parametrize("destination_kind", ["file-parent", "directory"])
def test_transfer_refuses_file_directory_collisions(tmp_path: Path, monkeypatch, capsys, destination_kind):
    worktree = create_feature(tmp_path, monkeypatch)
    (worktree / "drafts").mkdir()
    (worktree / "drafts/note").write_text("keep", encoding="utf-8")
    if destination_kind == "file-parent":
        (tmp_path / "drafts").write_text("target", encoding="utf-8")
    else:
        (tmp_path / "drafts/note").mkdir(parents=True)
    assert main(["merge", "demo", "--include-untracked"]) == 1
    assert "untracked transfer" in capsys.readouterr().err
    assert (worktree / "drafts/note").read_text() == "keep"


def test_copy_failure_preserves_originals_and_completed_copies(tmp_path: Path, monkeypatch, capsys):
    from pathlib import Path

    worktree = create_feature(tmp_path, monkeypatch)
    (worktree / "drafts").mkdir()
    for name in ["one", "two"]:
        (worktree / "drafts" / name).write_text(name, encoding="utf-8")
    link = Path.hardlink_to

    def fail_second(destination, source):
        if destination.name == "two":
            raise OSError("disk error")
        link(destination, source)

    monkeypatch.setattr(Path, "hardlink_to", fail_second)
    assert main(["merge", "demo", "--include-untracked"]) == 1
    assert "originals retained" in capsys.readouterr().err
    assert (worktree / "drafts/one").read_text() == "one"
    assert (worktree / "drafts/two").read_text() == "two"
    assert (tmp_path / "drafts/one").read_text() == "one"
    assert not (tmp_path / "drafts/two").exists()
    assert not list((tmp_path / "drafts").glob(".new-feature-copy-*"))
    monkeypatch.setattr(Path, "hardlink_to", link)
    assert main(["merge", "demo", "--include-untracked"]) == 0
    assert (tmp_path / "drafts/two").read_text() == "two"


@pytest.mark.parametrize("target_kind", ["file", "broken-symlink", "parent-symlink", "parent-file"])
def test_git_merge_does_not_overwrite_existing_ignored_target_work(tmp_path: Path, monkeypatch, target_kind):
    worktree = create_feature(tmp_path, monkeypatch)
    with (tmp_path / ".git/info/exclude").open("a") as excludes:
        excludes.write("\ndrafts\n")
    (worktree / "drafts").mkdir()
    (worktree / "drafts/note").write_text("tracked feature", encoding="utf-8")
    target = tmp_path / "drafts/note"
    if target_kind in {"file", "broken-symlink"}:
        target.parent.mkdir()
        if target_kind == "file":
            target.write_text("target local work", encoding="utf-8")
        else:
            target.symlink_to(tmp_path / "missing")
    elif target_kind == "parent-file":
        target.parent.write_text("target local work", encoding="utf-8")
    else:
        external = tmp_path.with_name(tmp_path.name + "-external")
        external.mkdir()
        target.parent.symlink_to(external, target_is_directory=True)
    subprocess.run(["git", "add", "--force", "drafts/note"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Track feature note"], cwd=worktree, check=True)
    assert main(["merge", "demo", "--include-untracked"]) == 1
    assert (worktree / "drafts/note").read_text() == "tracked feature"
    if target_kind == "file":
        assert target.read_text() == "target local work"
    elif target_kind == "parent-file":
        assert target.parent.read_text() == "target local work"
    elif target_kind == "broken-symlink":
        assert target.is_symlink()
    else:
        assert target.parent.is_symlink()
        assert not (external / "note").exists()


@pytest.mark.parametrize("old_kind", ["file", "symlink"])
def test_git_merge_can_replace_tracked_file_with_directory(tmp_path: Path, monkeypatch, old_kind):
    init_git_repo(tmp_path)
    old = tmp_path / "container"
    if old_kind == "file":
        old.write_text("tracked old file", encoding="utf-8")
    else:
        old.symlink_to("README.md")
    subprocess.run(["git", "add", "container"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Old tracked path"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["create", "demo", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees/demo"
    (worktree / "container").unlink()
    (worktree / "container").mkdir()
    (worktree / "container/new").write_text("new tracked file", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Replace tracked path"], cwd=worktree, check=True)
    assert main(["merge", "demo", "--include-untracked"]) == 0
    assert (tmp_path / "container/new").read_text() == "new tracked file"


@pytest.mark.parametrize("local_file", [False, True])
def test_git_merge_directory_to_file_protects_local_contents(tmp_path: Path, monkeypatch, local_file):
    init_git_repo(tmp_path)
    (tmp_path / "container").mkdir()
    (tmp_path / "container/old").write_text("tracked", encoding="utf-8")
    subprocess.run(["git", "add", "container"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Tracked directory"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["create", "demo", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees/demo"
    (worktree / "container/old").unlink()
    (worktree / "container").rmdir()
    (worktree / "container").write_text("new tracked file", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Replace tracked directory"], cwd=worktree, check=True)
    if local_file:
        with (tmp_path / ".git/info/exclude").open("a") as excludes:
            excludes.write("\ncontainer/local\n")
        (tmp_path / "container/local").write_text("keep", encoding="utf-8")
    assert main(["merge", "demo", "--include-untracked"]) == (1 if local_file else 0)
    if local_file:
        assert (tmp_path / "container/local").read_text() == "keep"
    else:
        assert (tmp_path / "container").read_text() == "new tracked file"
