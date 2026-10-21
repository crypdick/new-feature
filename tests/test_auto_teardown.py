from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from new_feature.cli import main
from new_feature.manifest import load_manifest
from tests.conftest import init_git_repo


@pytest.fixture
def feature(tmp_path: Path, monkeypatch):
    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    (tmp_path / ".new-feature.local.toml").write_text("auto-teardown = true\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["demo", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees/demo"
    (worktree / "feature.txt").write_text("done\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "add feature"], cwd=worktree, check=True)
    return tmp_path


@pytest.mark.parametrize("already_merged", [False, True])
def test_auto_teardown_removes_worktree_branch_and_record(feature: Path, already_merged: bool, capsys):
    if already_merged:
        subprocess.run(["git", "merge", "demo"], cwd=feature, check=True)
    capsys.readouterr()

    assert main(["merge", "demo"]) == 0

    assert not (feature / ".worktrees/demo").exists()
    assert load_manifest(feature).features == {}
    branch = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/demo"], cwd=feature, check=False
    )
    assert branch.returncode == 1
    assert (feature / "feature.txt").read_text(encoding="utf-8") == "done\n"
    assert "teardown now" not in capsys.readouterr().out


def test_auto_teardown_runs_cleanup_after_push_and_retries_failed_push(feature: Path, capsys):
    remote = feature / "remote.git"
    (feature / ".new-feature.local.toml").write_text(
        "auto-teardown = true\npush = true\n"
        'teardown = [\'test "$(git -C "$NEW_FEATURE_REPO_ROOT" rev-parse origin/main)" = '
        '"$(git -C "$NEW_FEATURE_REPO_ROOT" rev-parse main)" && '
        'printf "%s" "$NEW_FEATURE_SLUG" > "$NEW_FEATURE_REPO_ROOT/cleaned"\']\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=feature, check=True)

    assert main(["merge", "demo"]) == 1
    assert (feature / ".worktrees/demo").exists()
    assert not (feature / "cleaned").exists()
    assert load_manifest(feature).features["demo"].status == "merged"
    capsys.readouterr()

    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    assert main(["merge", "demo"]) == 0
    assert (feature / "cleaned").read_text(encoding="utf-8") == "demo"
    assert not (feature / ".worktrees/demo").exists()
    assert load_manifest(feature).features == {}


@pytest.mark.parametrize("phase", ["pre_merge", "post_merge"])
def test_failed_checks_skip_auto_teardown(feature: Path, phase: str):
    (feature / ".new-feature.local.toml").write_text(
        f'auto-teardown = true\n{phase} = ["false"]\n'
        "teardown = ['touch \"$NEW_FEATURE_REPO_ROOT/cleaned\"']\n",
        encoding="utf-8",
    )

    assert main(["merge", "demo"]) == 1
    assert (feature / ".worktrees/demo").exists()
    assert not (feature / "cleaned").exists()
    assert not (feature / "feature.txt").exists()
    assert load_manifest(feature).features["demo"].status == "active"


def test_auto_teardown_failure_retains_merge_and_can_be_retried(feature: Path, capsys):
    config_path = feature / ".new-feature.local.toml"
    config_path.write_text('auto-teardown = true\nteardown = ["false"]\n', encoding="utf-8")
    capsys.readouterr()

    assert main(["merge", "demo"]) == 1
    assert "merge succeeded but auto-teardown failed" in capsys.readouterr().err
    assert (feature / ".worktrees/demo").exists()
    assert (feature / "feature.txt").exists()
    assert load_manifest(feature).features["demo"].status == "merged"

    config_path.write_text("auto-teardown = true\n", encoding="utf-8")
    assert main(["merge", "demo"]) == 0
    assert not (feature / ".worktrees/demo").exists()


def test_auto_teardown_protects_unpreserved_ignored_files(feature: Path, capsys):
    with (feature / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
        exclude.write("\ndraft.txt\n")
    draft = feature / ".worktrees/demo/draft.txt"
    draft.write_text("keep\n", encoding="utf-8")

    assert main(["merge", "demo"]) == 1
    assert "merge succeeded but auto-teardown failed" in capsys.readouterr().err
    assert draft.read_text(encoding="utf-8") == "keep\n"
    assert load_manifest(feature).features["demo"].status == "merged"

    assert main(["merge", "--include-untracked", "demo"]) == 0
    assert (feature / "draft.txt").read_text(encoding="utf-8") == "keep\n"
    assert not (feature / ".worktrees/demo").exists()


def test_auto_teardown_from_feature_ignores_own_process(feature: Path, monkeypatch):
    monkeypatch.chdir(feature / ".worktrees/demo")
    assert main(["merge", "demo"]) == 0
    assert Path.cwd() == feature
    assert not (feature / ".worktrees/demo").exists()


def test_auto_teardown_from_feature_keeps_process_guard(feature: Path, capsys):
    worktree = feature / ".worktrees/demo"
    shell = subprocess.Popen(
        [sys.executable, "-c", "import sys; print('ready', flush=True); sys.stdin.read()"],
        cwd=worktree,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert shell.stdout.readline() == "ready\n"
        assert main(["merge", "demo"]) == 1
        assert f"PID {shell.pid}" in capsys.readouterr().err
        assert (feature / "feature.txt").exists()
        assert load_manifest(feature).features["demo"].status == "merged"
    finally:
        shell.communicate(timeout=5)

    assert main(["merge", "demo"]) == 0
    assert not worktree.exists()
