from __future__ import annotations

import subprocess
from threading import Event, Thread
from typing import TYPE_CHECKING

import pytest

from new_feature import cli
from new_feature.errors import NewFeatureError
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


def test_concurrent_same_feature_merge_and_teardown_fail_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["demo", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees/demo"
    (worktree / "feature.txt").write_text("feature work\n")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Feature work"], cwd=worktree, check=True)
    first_check_started = Event()
    release_first_check = Event()
    check_calls = 0
    results: list[int] = []
    errors: list[NewFeatureError] = []

    def run_commands(_commands, *, cwd, env, failure_log=None):
        del cwd, env, failure_log
        nonlocal check_calls
        check_calls += 1
        if check_calls == 1:
            first_check_started.set()
            assert release_first_check.wait(timeout=5)

    monkeypatch.setattr(cli, "run_commands", run_commands)

    def merge() -> None:
        try:
            results.append(cli._dispatch(cli.parse_args(["merge", "demo"]), tmp_path))
        except NewFeatureError as exc:
            errors.append(exc)

    first = Thread(target=merge)
    first.start()
    assert first_check_started.wait(timeout=5)
    try:
        with pytest.raises(NewFeatureError, match="feature operation already in progress: demo"):
            cli._dispatch(cli.parse_args(["merge", "demo"]), tmp_path)
        with pytest.raises(NewFeatureError, match="feature operation already in progress: demo"):
            cli._dispatch(cli.parse_args(["teardown", "demo"]), tmp_path)
        assert check_calls == 1
    finally:
        release_first_check.set()
        first.join(timeout=5)

    assert not first.is_alive()
    assert not errors
    assert results == [0]
    assert (tmp_path / "feature.txt").read_text() == "feature work\n"
