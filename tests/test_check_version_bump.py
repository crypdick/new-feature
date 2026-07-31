from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.conftest import init_git_repo

SCRIPT = Path(__file__).parents[1] / "scripts" / "prek_hooks" / "check_version_bump.py"


def test_main_push_requires_version_change(tmp_path: Path) -> None:
    init_git_repo(tmp_path, '[project]\nname = "demo"\nversion = "1.0.0"\n')
    previous = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    (tmp_path / "README.md").write_text("change\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "change"], cwd=tmp_path, check=True)
    unchanged = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    blocked = run_hook(tmp_path, unchanged, "refs/heads/main", previous)
    assert blocked.returncode == 1
    assert "uv version --bump patch" in blocked.stderr
    assert run_hook(tmp_path, unchanged, "refs/heads/feature", previous).returncode == 0

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.1"\n', encoding="utf-8"
    )
    subprocess.run(["git", "add", "pyproject.toml"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "bump version"], cwd=tmp_path, check=True)
    bumped = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    assert run_hook(tmp_path, bumped, "refs/heads/main", previous).returncode == 0


def run_hook(
    repo: Path, local_sha: str, remote_ref: str, remote_sha: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=repo,
        env={
            **os.environ,
            "PRE_COMMIT_TO_REF": local_sha,
            "PRE_COMMIT_REMOTE_BRANCH": remote_ref,
            "PRE_COMMIT_FROM_REF": remote_sha,
        },
        text=True,
        capture_output=True,
        check=False,
    )
