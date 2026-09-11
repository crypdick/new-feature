from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from new_feature.cli import main
from tests.conftest import init_git_repo


@pytest.mark.parametrize("command", [["list"], ["doctor"], ["doctor", "--repair"]])
@pytest.mark.parametrize("damage", ["gitfile", "index"])
def test_inspection_reports_corrupt_worktree_and_preserves_it(tmp_path, monkeypatch, capsys, command, damage):
    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)
    assert main(["broken", "--no-agent"]) == 0
    assert main(["healthy", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees" / "broken"
    gitfile = worktree / ".git"
    if damage == "gitfile":
        gitfile.write_text("")
        subprocess.run(["git", "update-ref", "-d", "refs/heads/broken"], check=True)
        error = "invalid gitfile format"
    else:
        gitdir = Path(gitfile.read_text().removeprefix("gitdir: ").strip())
        (gitdir / "index").write_bytes(b"broken")
        error = "index file smaller than expected"
    (worktree / "rescue.txt").write_text("keep this work\n")
    manifest = tmp_path / ".new-feature" / "manifest.toml"
    original_manifest = manifest.read_bytes()
    capsys.readouterr()

    assert main(command) == (0 if command == ["list"] else 1)

    output = capsys.readouterr()
    assert "worktree-error" in output.out
    assert "healthy" in output.out
    assert error in output.err
    assert (worktree / "rescue.txt").read_text() == "keep this work\n"
    assert manifest.read_bytes() == original_manifest
