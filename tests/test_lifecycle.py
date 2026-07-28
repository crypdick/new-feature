from __future__ import annotations

import subprocess
from contextlib import nullcontext
from threading import Event, Thread
from typing import TYPE_CHECKING

import pytest

from new_feature import cli, git
from new_feature.cli import main
from new_feature.errors import NewFeatureError
from new_feature.git import remove_worktree_and_branch
from new_feature.manifest import FeatureRecord, Manifest, load_manifest

if TYPE_CHECKING:
    from pathlib import Path


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
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=tmp_path, text=True)
    assert load_manifest(tmp_path).features["my_feature"].status == "active"


def test_merge_interrupt_aborts_prepared_target_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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

    def interrupt_post_merge(_commands: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        del env
        if cwd == tmp_path:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_commands", interrupt_post_merge)

    with pytest.raises(KeyboardInterrupt):
        main(["merge", "my-feature"])

    assert (
        subprocess.run(["git", "rev-parse", "--verify", "MERGE_HEAD"], cwd=tmp_path, check=False).returncode
        != 0
    )
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=tmp_path, text=True)
    assert not (tmp_path / "feature.txt").exists()
    assert load_manifest(tmp_path).features["my_feature"].status == "active"


def test_merge_runs_checks_commits_and_prints_teardown_reminder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(
        tmp_path,
        """
[project]
name = "demo"

[tool.new-feature] # temporal-ok
pre_merge = ["test -f feature.txt"]
post_merge = ["test -f feature.txt"]
push = false
""",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["my-feature", "--no-agent"]) == 0
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "ignore generated state"], cwd=tmp_path, check=True)
    worktree = tmp_path / ".worktrees" / "my-feature"
    (worktree / "feature.txt").write_text("done\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "add feature"], cwd=worktree, check=True)
    capsys.readouterr()

    assert main(["merge", "my-feature"]) == 0
    assert capsys.readouterr().out == (
        "Feature merged. Remember to `new-feature teardown my-feature` when you are done with the worktree.\n"
    )
    assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == "done\n"
    assert load_manifest(tmp_path).features["my_feature"].status == "merged"


def test_concurrent_merges_serialize_target_checkout_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = Manifest(
        features={
            "first": FeatureRecord(
                name="first",
                slug="first",
                branch="first",
                worktree=".worktrees/first",
                target_branch="main",
                status="active",
                created_at="2026-07-26T00:00:00Z",
            ),
            "second": FeatureRecord(
                name="second",
                slug="second",
                branch="second",
                worktree=".worktrees/second",
                target_branch="main",
                status="active",
                created_at="2026-07-26T00:00:00Z",
            ),
        }
    )
    first_started = Event()
    release_first = Event()
    second_started = Event()
    mutations: list[str] = []
    results: list[int] = []

    monkeypatch.setattr(cli, "load_project_config", lambda _root: cli.ProjectConfig())
    monkeypatch.setattr(cli, "manifest_lock", lambda _root: nullcontext())
    monkeypatch.setattr(cli, "load_manifest", lambda _root: manifest)
    monkeypatch.setattr(cli, "save_manifest", lambda _root, _manifest: None)
    monkeypatch.setattr(cli, "run_commands", lambda _commands, *, cwd, env: None)
    monkeypatch.setattr(cli, "worktree_is_clean", lambda _worktree: True)
    monkeypatch.setattr(cli, "commit_merge", lambda _root, *, name: None)

    def begin_merge(_root: Path, *, branch: str, target_branch: str) -> None:
        assert target_branch == "main"
        mutations.append(branch)
        if branch == "first":
            first_started.set()
            assert release_first.wait(timeout=5)
        else:
            second_started.set()

    monkeypatch.setattr(cli, "begin_merge_without_commit", begin_merge)

    def merge(name: str) -> None:
        results.append(cli._merge(tmp_path, name))

    first = Thread(target=merge, args=("first",))
    second = Thread(target=merge, args=("second",))
    first.start()
    assert first_started.wait(timeout=5)
    second.start()
    assert not second_started.wait(timeout=0.1)
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert mutations == ["first", "second"]
    assert results == [0, 0]


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
    assert not branches.strip()
