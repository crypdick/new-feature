from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature.cli import main
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def clone(tmp_path: Path, remote: Path, name: str) -> Path:
    checkout = tmp_path / name
    subprocess.run(["git", "clone", "-q", str(remote), str(checkout)], check=True)
    git(checkout, "config", "user.email", "test@example.com")
    git(checkout, "config", "user.name", "Test User")
    # The deploy log lives outside the checkout so it records the merged tree only.
    (checkout / ".new-feature.local.toml").write_text(
        f"push = true\npost_merge = ['ls > {tmp_path / name}.deployed']\n", encoding="utf-8"
    )
    return checkout


def feature(checkout: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.chdir(checkout)
    assert main([name, "--no-agent"]) == 0
    worktree = checkout / ".worktrees" / name
    (worktree / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    git(worktree, "add", f"{name}.txt")
    git(worktree, "commit", "-q", "-m", name)


@pytest.fixture
def clones(tmp_path: Path) -> tuple[Path, Path, Path]:
    seed, remote = tmp_path / "seed", tmp_path / "remote.git"
    seed.mkdir()
    init_git_repo(seed)
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(remote)], check=True)
    return remote, clone(tmp_path, remote, "first"), clone(tmp_path, remote, "second")


def test_merge_includes_a_concurrently_pushed_merge(
    tmp_path: Path, clones: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, first, second = clones
    feature(first, monkeypatch, "alpha")
    feature(second, monkeypatch, "beta")
    monkeypatch.chdir(first)
    assert main(["merge", "alpha"]) == 0
    monkeypatch.chdir(second)
    assert main(["merge", "beta"]) == 0
    assert {"alpha.txt", "beta.txt"} <= set((tmp_path / "second.deployed").read_text().split())
    assert git(remote, "rev-parse", "main") == git(second, "rev-parse", "main")
    assert git(remote, "ls-tree", "--name-only", "main").split() == ["README.md", "alpha.txt", "beta.txt"]


def test_merge_refuses_a_target_that_diverged_from_origin(
    tmp_path: Path, clones: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, first, second = clones
    feature(first, monkeypatch, "alpha")
    monkeypatch.chdir(first)
    assert main(["merge", "alpha"]) == 0
    (second / "local.txt").write_text("unpublished\n", encoding="utf-8")
    git(second, "add", "local.txt")
    git(second, "commit", "-q", "-m", "Unpublished target commit")
    feature(second, monkeypatch, "beta")
    before = git(second, "rev-parse", "main")
    assert main(["merge", "beta"]) == 1
    assert not (tmp_path / "second.deployed").exists()
    assert git(second, "rev-parse", "main") == before
    assert git(remote, "ls-tree", "--name-only", "main").split() == ["README.md", "alpha.txt"]


def test_merge_publishes_unpushed_target_commits_when_origin_is_behind(
    clones: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, first, _ = clones
    (first / "local.txt").write_text("unpublished\n", encoding="utf-8")
    git(first, "add", "local.txt")
    git(first, "commit", "-q", "-m", "Unpublished target commit")
    feature(first, monkeypatch, "alpha")
    assert main(["merge", "alpha"]) == 0
    assert git(remote, "ls-tree", "--name-only", "main").split() == ["README.md", "alpha.txt", "local.txt"]
