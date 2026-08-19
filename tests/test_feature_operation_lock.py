from __future__ import annotations

from contextlib import nullcontext
from threading import Event, Thread
from typing import TYPE_CHECKING

import pytest

from new_feature import cli
from new_feature.errors import NewFeatureError
from new_feature.manifest import FeatureRecord, Manifest

if TYPE_CHECKING:
    from pathlib import Path


def test_concurrent_same_feature_merge_and_teardown_fail_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = FeatureRecord(
        name="demo",
        slug="demo",
        branch="demo",
        worktree=".worktrees/demo",
        target_branch="main",
        status="active",
        created_at="2026-08-19T00:00:00Z",
    )
    manifest = Manifest(features={"demo": record})
    first_check_started = Event()
    release_first_check = Event()
    check_calls = 0
    results: list[int] = []
    errors: list[NewFeatureError] = []

    monkeypatch.setattr(cli, "load_project_config", lambda _root: cli.ProjectConfig())
    monkeypatch.setattr(cli, "manifest_lock", lambda _root: nullcontext())
    monkeypatch.setattr(cli, "load_manifest", lambda _root: manifest)
    monkeypatch.setattr(cli, "worktree_is_clean", lambda _worktree: True)
    monkeypatch.setattr(cli, "ensure_merge_is_clean", lambda _root, *, branch, target_branch: None)
    monkeypatch.setattr(cli, "_merge_target", lambda _root, _config, _key, current: current)

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
