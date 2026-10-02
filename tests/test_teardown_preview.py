from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from new_feature.cli import main
from new_feature.manifest import load_manifest
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


def test_teardown_preview_preserves_resources_and_locks(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path, '[project]\nname="demo"\n[tool.new-feature]\nteardown=["touch cleaned"]\n')
    monkeypatch.chdir(tmp_path)
    assert main(["feature", "--no-agent"]) == 0
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in (tmp_path / ".new-feature").rglob("*")
        if path.is_file()
    }
    capsys.readouterr()
    assert main(["teardown", "feature", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert str(tmp_path / ".worktrees" / "feature") in output
    assert "Branch: feature" in output
    assert "Target: main" in output
    assert "touch cleaned" in output
    assert "remove manifest entry" in output
    assert (tmp_path / ".worktrees" / "feature").exists()
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in (tmp_path / ".new-feature").rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (tmp_path / ".worktrees" / "feature" / "cleaned").exists()


def test_unmanaged_preview_creates_no_state(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    worktree = tmp_path / ".worktrees" / "feature"
    subprocess.run(["git", "worktree", "add", "-b", "feature", str(worktree)], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["teardown", "feature", "--dry-run"]) == 0
    assert "skip configured cleanup" in capsys.readouterr().out
    assert not (tmp_path / ".new-feature").exists()


def test_teardown_preview_reports_all_refusals(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["feature", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees" / "feature"
    (worktree / "committed").write_text("change", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "change"], cwd=worktree, check=True)
    (worktree / "dirty").write_text("dirty", encoding="utf-8")
    capsys.readouterr()
    assert main(["teardown", "feature", "--dry-run"]) == 1
    output = capsys.readouterr().out
    assert "unpreserved untracked or ignored files" in output
    assert "unmerged commits" in output
    assert worktree.exists()
    assert main(["teardown", "feature", "--dry-run", "--force"]) == 0


def test_live_process_in_nested_directory_blocks_teardown(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["feature", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees" / "feature"
    nested = worktree / "nested"
    nested.mkdir()
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; print('ready', flush=True); sys.stdin.read()"],
        cwd=nested,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline() == "ready\n"
        capsys.readouterr()
        assert main(["teardown", "feature", "--dry-run"]) == 1
        assert f"PID {process.pid}" in capsys.readouterr().out
        assert main(["teardown", "feature"]) == 1
        assert "processes have working directories" in capsys.readouterr().err
        assert load_manifest(tmp_path).features
        assert main(["teardown", "feature", "--force"]) == 0
        assert not worktree.exists()
        assert process.poll() is None
    finally:
        process.communicate(timeout=5)


def test_unmanaged_detached_preview_has_no_branch_action(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    worktree = tmp_path / ".worktrees" / "feature"
    subprocess.run(["git", "worktree", "add", "--detach", str(worktree)], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["teardown", "feature", "--dry-run"]) == 1
    output = capsys.readouterr().out
    assert "Branch: (detached)" in output
    assert "delete branch" not in output
    assert "unmanaged worktree is detached" in output


def test_missing_proc_scan_is_explained(tmp_path: Path):
    import pytest

    from new_feature.errors import NewFeatureError
    from new_feature.processes import worktree_processes

    with pytest.raises(NewFeatureError, match="cannot inspect process working directories"):
        worktree_processes(tmp_path, proc_root=tmp_path / "missing-proc")


def test_cleanup_child_blocks_removal_after_successful_cleanup(tmp_path: Path, monkeypatch, capsys):
    import os
    import signal

    script = tmp_path / "leave_child.py"
    script.write_text(
        "import os, pathlib, subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "pathlib.Path(os.environ['NEW_FEATURE_REPO_ROOT'], 'child.pid').write_text(str(child.pid))\n",
        encoding="utf-8",
    )
    init_git_repo(
        tmp_path,
        '[project]\nname="demo"\n[tool.new-feature]\nteardown=["python3 leave_child.py"]\n',
    )
    subprocess.run(["git", "add", "leave_child.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "cleanup script"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["feature", "--no-agent"]) == 0
    capsys.readouterr()
    try:
        assert main(["teardown", "feature"]) == 1
        output = capsys.readouterr()
        pid = int((tmp_path / "child.pid").read_text(encoding="utf-8"))
        assert f"PID {pid}" in output.err
        assert (tmp_path / ".worktrees" / "feature").exists()
        assert load_manifest(tmp_path).features
    finally:
        if (tmp_path / "child.pid").exists():
            os.kill(int((tmp_path / "child.pid").read_text(encoding="utf-8")), signal.SIGTERM)


def test_ignored_files_survive_merge_and_block_teardown(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("drafts/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Ignore local drafts"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["feature", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees/feature"
    draft = worktree / "drafts/local note.md"
    draft.parent.mkdir()
    draft.write_text("valuable local work", encoding="utf-8")
    (worktree / "README.md").write_text("feature change\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "Feature change"], cwd=worktree, check=True)
    assert main(["merge", "feature"]) == 0
    assert draft.read_text() == "valuable local work"
    assert not (tmp_path / "drafts/local note.md").exists()
    capsys.readouterr()
    assert main(["teardown", "feature", "--dry-run"]) == 1
    assert "ignored files" in capsys.readouterr().out
    assert main(["teardown", "feature"]) == 1
    assert "ignored files" in capsys.readouterr().err
    assert draft.read_text() == "valuable local work"
    assert load_manifest(tmp_path).features
    assert main(["teardown", "feature", "--force"]) == 0
    assert not worktree.exists()


def test_teardown_retains_ignored_files_created_by_cleanup(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path, '[tool.new-feature]\nteardown=["mkdir -p drafts; echo keep > drafts/note"]\n')
    (tmp_path / ".gitignore").write_text("drafts/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Ignore drafts"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["feature", "--no-agent"]) == 0
    assert main(["teardown", "feature"]) == 1
    assert "ignored files" in capsys.readouterr().err
    assert (tmp_path / ".worktrees/feature/drafts/note").read_text() == "keep\n"


def test_teardown_rechecks_tracked_changes_after_cleanup(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path, '[tool.new-feature]\nteardown=["echo changed >> pyproject.toml"]\n')
    monkeypatch.chdir(tmp_path)
    assert main(["feature", "--no-agent"]) == 0
    assert main(["teardown", "feature"]) == 1
    assert "uncommitted tracked changes" in capsys.readouterr().err
    assert (tmp_path / ".worktrees/feature/pyproject.toml").exists()


def test_teardown_preview_reports_tracked_changes(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["feature", "--no-agent"]) == 0
    (tmp_path / ".worktrees/feature/README.md").write_text("dirty", encoding="utf-8")
    assert main(["teardown", "feature", "--dry-run"]) == 1
    assert "uncommitted changes" in capsys.readouterr().out
