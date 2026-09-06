from __future__ import annotations

import subprocess

import pytest

from scripts.prepare_release import release_state, release_version
from tests.conftest import init_git_repo


@pytest.mark.parametrize(
    ("current", "published", "expected"),
    [
        ("1.1.30", ["1.1.30"], "1.1.31"),
        ("1.2.0", ["1.1.30"], "1.2.0"),
        ("1.1.9", ["1.1.10"], "1.1.11"),
        ("0.1.0", [], "0.1.0"),
    ],
)
def test_release_version(current, published, expected):
    assert release_version(current, published) == expected


def test_release_retries_reuse_commit_and_stale_runs_skip(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    init_git_repo(tmp_path)
    source = git("rev-parse", "HEAD")
    assert release_state(tmp_path, source) == "new"
    git("commit", "--allow-empty", "-m", "Release 1.1.31", "-m", f"Source-Commit: {source}")
    assert release_state(tmp_path, source) == "retry"
    git("commit", "--allow-empty", "-m", "Next source change")
    assert release_state(tmp_path, source) == "stale"
