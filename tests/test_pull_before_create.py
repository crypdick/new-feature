from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature.cli import main
from new_feature.errors import NewFeatureError
from new_feature.git import pull_target

if TYPE_CHECKING:
    from pathlib import Path


def test_pull_before_create_fast_forwards_only_for_new_worktrees(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tests.conftest import init_git_repo

    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    upstream = tmp_path / "upstream"
    repo.mkdir()
    init_git_repo(repo, '[project]\nname = "demo"\n\n[tool.new-feature]\npull_before_create = true\n')
    subprocess.run(["git", "init", "--bare", remote], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True)
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(upstream)], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=upstream, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=upstream, check=True)
    (upstream / "upstream.txt").write_text("latest\n", encoding="utf-8")
    subprocess.run(["git", "add", "upstream.txt"], cwd=upstream, check=True)
    subprocess.run(["git", "commit", "-m", "upstream"], cwd=upstream, check=True)
    subprocess.run(["git", "push"], cwd=upstream, check=True)
    monkeypatch.chdir(repo)

    original_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True)
    assert main(["dry-run", "--dry-run"]) == 0
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True) == original_head
    assert main(["my-feature", "--no-agent"]) == 0
    assert (repo / ".worktrees" / "my-feature" / "upstream.txt").read_text(encoding="utf-8") == "latest\n"

    (upstream / "later.txt").write_text("later\n", encoding="utf-8")
    subprocess.run(["git", "add", "later.txt"], cwd=upstream, check=True)
    subprocess.run(["git", "commit", "-m", "later upstream"], cwd=upstream, check=True)
    subprocess.run(["git", "push"], cwd=upstream, check=True)
    pulled_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True)
    assert main(["my-feature", "--no-agent"]) == 0
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True) == pulled_head

    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "local"], cwd=repo, check=True)
    assert main(["diverged", "--no-agent"]) == 1
    assert "Not possible to fast-forward" in capsys.readouterr().err
    assert not (repo / ".worktrees" / "diverged").exists()


def test_pull_target_requires_clean_configured_target(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    (tmp_path / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(NewFeatureError, match="target checkout has uncommitted changes"):
        pull_target(tmp_path, target_branch="main")

    (tmp_path / "dirty.txt").unlink()
    subprocess.run(["git", "switch", "-c", "other"], cwd=tmp_path, check=True)
    with pytest.raises(NewFeatureError, match="target branch 'main' is not checked out"):
        pull_target(tmp_path, target_branch="main")
