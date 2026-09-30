from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from new_feature.cli import main
from new_feature.git import repo_root
from new_feature.manifest import Manifest, load_manifest, save_manifest
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


def test_lifecycle_commands_use_owning_checkout_from_managed_worktree(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["first", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees/first"
    monkeypatch.chdir(worktree)
    assert repo_root(worktree) == worktree
    capsys.readouterr()
    assert main(["list"]) == 0
    assert "first" in capsys.readouterr().out
    assert main(["doctor"]) == 0
    assert main(["second", "--no-agent"]) == 0
    assert set(load_manifest(tmp_path).features) == {"first", "second"}
    assert not (worktree / ".new-feature/manifest.toml").exists()
    assert main(["merge", "first"]) == 0
    assert load_manifest(tmp_path).features["first"].status == "merged"
    assert main(["teardown", "second"]) == 0


def test_teardown_can_remove_its_invoking_checkout(tmp_path: Path, monkeypatch):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["first", "--no-agent"]) == 0
    monkeypatch.chdir(tmp_path / ".worktrees/first")
    try:
        assert main(["teardown", "first", "--force"]) == 0
        assert not (tmp_path / ".worktrees/first").exists()
    finally:
        monkeypatch.chdir(tmp_path)


def test_ordinary_linked_checkout_can_own_managed_features(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    linked = tmp_path / "linked"
    subprocess.run(["git", "worktree", "add", "-b", "linked", str(linked)], cwd=tmp_path, check=True)
    monkeypatch.chdir(linked)
    assert main(["first", "--no-agent"]) == 0
    assert "first" in load_manifest(linked).features
    assert load_manifest(tmp_path).features == {}
    monkeypatch.chdir(linked / ".worktrees/first")
    capsys.readouterr()
    assert main(["list"]) == 0
    assert "first" in capsys.readouterr().out


def test_ambiguous_manifest_ownership_fails(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["first", "--no-agent"]) == 0
    linked = tmp_path / "linked"
    subprocess.run(["git", "worktree", "add", "-b", "linked", str(linked)], cwd=tmp_path, check=True)
    record = load_manifest(tmp_path).features["first"]
    record.worktree = str(tmp_path / record.worktree)
    save_manifest(linked, Manifest(features={"first": record}))
    monkeypatch.chdir(tmp_path / ".worktrees/first")
    assert main(["list"]) == 1
    assert "ambiguous" in capsys.readouterr().err


def test_inherited_git_context_does_not_select_ownership(tmp_path: Path, monkeypatch, capsys):
    owner = tmp_path / "owner"
    wrong = tmp_path / "wrong"
    owner.mkdir()
    wrong.mkdir()
    init_git_repo(owner)
    init_git_repo(wrong)
    monkeypatch.chdir(owner)
    assert main(["first", "--no-agent"]) == 0
    monkeypatch.chdir(owner / ".worktrees/first")
    monkeypatch.setenv("GIT_DIR", str(wrong / ".git"))
    capsys.readouterr()
    assert main(["list"]) == 0
    assert "first" in capsys.readouterr().out


def test_corrupt_sibling_manifest_does_not_break_owner_inspection(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["first", "--no-agent"]) == 0
    sibling = tmp_path / "sibling"
    subprocess.run(["git", "worktree", "add", "-b", "sibling", str(sibling)], cwd=tmp_path, check=True)
    (sibling / ".new-feature").mkdir()
    (sibling / ".new-feature/manifest.toml").write_text("broken = [", encoding="utf-8")
    monkeypatch.chdir(tmp_path / ".worktrees/first")
    capsys.readouterr()
    assert main(["list"]) == 0
    assert "first" in capsys.readouterr().out


def test_corrupt_likely_owner_manifest_fails_closed(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["first", "--no-agent"]) == 0
    (tmp_path / ".new-feature/manifest.toml").write_text("broken = [", encoding="utf-8")
    monkeypatch.chdir(tmp_path / ".worktrees/first")
    assert main(["list"]) == 1
    assert "invalid feature manifest" in capsys.readouterr().err


def test_recorded_path_requires_matching_git_branch(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["first", "--no-agent"]) == 0
    monkeypatch.chdir(tmp_path / ".worktrees/first")
    subprocess.run(["git", "checkout", "-b", "other"], check=True)
    assert main(["list"]) == 1
    assert "branch does not match" in capsys.readouterr().err
