from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Thread
from unittest.mock import Mock

import pytest

from new_feature import commands
from new_feature.cli import main
from new_feature.cli_parser import parse_args
from new_feature.manifest import load_manifest, save_manifest
from tests.conftest import init_git_repo


@pytest.fixture
def feature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    init_git_repo(tmp_path, '[tool.new-feature.env]\nVALUE = { value = "recorded" }\n')
    monkeypatch.chdir(tmp_path)
    assert main(["My Feature", "--no-agent"]) == 0
    return tmp_path / ".worktrees/my-feature"


def test_exec_restores_environment_cwd_and_literal_arguments(feature: Path, monkeypatch):
    monkeypatch.setenv("VALUE", "inherited")
    monkeypatch.setenv("GIT_DIR", str(feature.parent.parent / ".git"))
    script = (
        "import json, os, pathlib, sys; "
        'pathlib.Path("observed.json").write_text(json.dumps('
        '[os.getcwd(), os.getenv("VALUE"), os.getenv("NEW_FEATURE_SLUG"), os.getenv("GIT_DIR"), sys.argv[1:]]))'
    )
    assert (
        main(["exec", "My Feature", "--", sys.executable, "-c", script, "$VALUE; touch injected", "--flag"])
        == 0
    )
    assert json.loads((feature / "observed.json").read_text()) == [
        str(feature),
        "recorded",
        "my-feature",
        None,
        ["$VALUE; touch injected", "--flag"],
    ]
    assert not (feature / "injected").exists()


def test_exec_preserves_exit_code(feature: Path):
    assert main(["exec", "my-feature", "--", sys.executable, "-c", "raise SystemExit(7)"]) == 7


@pytest.mark.parametrize("arguments", [["exec"], ["exec", "my-feature"], ["exec", "my-feature", "--"]])
def test_exec_requires_name_and_command(arguments):
    with pytest.raises(SystemExit) as error:
        parse_args(arguments)
    assert error.value.code == 2


@pytest.mark.parametrize("name", ["my", "missing"])
def test_exec_rejects_unknown_names(feature: Path, name, capsys):
    assert main(["exec", name, "--", "true"]) == 1
    assert f"unknown feature: {name}" in capsys.readouterr().err


@pytest.mark.parametrize("problem", ["initializing", "missing-worktree", "missing-branch", "wrong-branch"])
def test_exec_rejects_unusable_features(feature: Path, problem, capsys):
    root = feature.parent.parent
    manifest = load_manifest(root)
    if problem == "initializing":
        manifest.features["my_feature"].status = "initializing"
        save_manifest(root, manifest)
    elif problem == "missing-worktree":
        subprocess.run(["git", "worktree", "remove", str(feature)], cwd=root, check=True)
    elif problem == "missing-branch":
        subprocess.run(["git", "checkout", "--detach"], cwd=feature, check=True)
        subprocess.run(["git", "branch", "-D", "my-feature"], cwd=root, check=True)
    else:
        subprocess.run(["git", "checkout", "-b", "other"], cwd=feature, check=True)
    assert main(["exec", "my-feature", "--", "true"]) == 1
    assert "new-feature:" in capsys.readouterr().err


def test_exec_reports_missing_executable(feature: Path, capsys):
    assert main(["exec", "my-feature", "--", "missing-new-feature-executable"]) == 1
    assert "cannot start command" in capsys.readouterr().err


def test_parallel_exec_blocks_teardown_until_all_commands_exit(feature: Path, monkeypatch):
    started = [Event(), Event()]
    release = [Event(), Event()]
    results = []
    invocations = 0

    def run(*_args, **_kwargs):
        nonlocal invocations
        index = invocations
        invocations += 1
        started[index].set()
        assert release[index].wait(timeout=5)
        return 0

    monkeypatch.setattr(commands, "run_argv", run)
    threads = [
        Thread(target=lambda: results.append(main(["exec", "my-feature", "--", "true"]))) for _ in range(2)
    ]
    for index, thread in enumerate(threads):
        thread.start()
        assert started[index].wait(timeout=5)
    try:
        assert main(["teardown", "my-feature", "--force"]) == 1
        assert main(["merge", "my-feature"]) == 1
        release[0].set()
        threads[0].join(timeout=5)
        assert main(["teardown", "my-feature", "--force"]) == 1
    finally:
        for event in release:
            event.set()
        for thread in threads:
            thread.join(timeout=5)
    assert results == [0, 0]
    assert main(["teardown", "my-feature", "--force"]) == 0


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_exec_cancellation_kills_process_group(feature: Path, monkeypatch, interruption):
    killed = []

    process = Mock(spec=subprocess.Popen)
    process.pid = 123
    process.wait.side_effect = [interruption, -signal.SIGKILL]

    real_popen = commands.subprocess.Popen
    monkeypatch.setattr(
        commands.subprocess,
        "Popen",
        lambda argv, **kwargs: process if argv[0] == "sleep" else real_popen(argv, **kwargs),
    )
    monkeypatch.setattr(commands.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(interruption):
        main(["exec", "my-feature", "--", "sleep", "60"])
    assert killed == [(123, signal.SIGKILL)]


def test_exec_is_rejected_during_lifecycle_operation(feature: Path, capsys):
    from new_feature.manifest import feature_operation_lock

    with feature_operation_lock(feature.parent.parent, "my-feature"):
        assert main(["exec", "my-feature", "--", "true"]) == 1
    assert "feature operation already in progress" in capsys.readouterr().err
    assert main(["exec", "my-feature", "--", "true"]) == 0


def test_exec_releases_lock_after_failed_command(feature: Path):
    assert main(["exec", "my-feature", "--", "false"]) == 1
    assert main(["teardown", "my-feature", "--force"]) == 0


def test_exec_inherits_standard_streams(feature: Path):
    source = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "new_feature",
            "exec",
            "my-feature",
            "--",
            sys.executable,
            "-c",
            'import sys; print(sys.stdin.read()); print("child error", file=sys.stderr)',
        ],
        cwd=feature,
        env={**os.environ, "PYTHONPATH": source},
        input="child input",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == "child input\n"
    assert result.stderr == "child error\n"


@pytest.mark.skipif(sys.platform != "linux", reason="process-state observation uses Linux procfs")
def test_exec_signal_cleanup_stops_descendants_and_releases_lock(feature: Path):
    ready = feature / "descendant.pid"
    script = (
        "import pathlib, subprocess, sys, time; "
        'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]); '
        'pathlib.Path("descendant.pid").write_text(str(child.pid)); time.sleep(60)'
    )
    launcher = subprocess.Popen(
        [sys.executable, "-m", "new_feature", "exec", "my-feature", "--", sys.executable, "-c", script],
        cwd=feature.parent.parent,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            assert launcher.poll() is None
            time.sleep(0.01)
        assert ready.exists()
        pid = int(ready.read_text())
        launcher.terminate()
        stdout, stderr = launcher.communicate(timeout=5)
        assert launcher.returncode == 143, (stdout, stderr)

        def descendant_running():
            try:
                return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2] != "Z"
            except FileNotFoundError:
                return False

        deadline = time.monotonic() + 5
        while descendant_running() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not descendant_running()
        assert main(["teardown", "my-feature", "--force"]) == 0
    finally:
        if launcher.poll() is None:
            launcher.terminate()
            launcher.wait(timeout=5)


def test_exec_reports_unsupported_execution_lock(feature: Path, monkeypatch, capsys):
    from new_feature import manifest as manifest_module

    def unsupported(*_args):
        raise OSError("locking unavailable")

    monkeypatch.setattr(manifest_module.fcntl, "flock", unsupported)
    assert main(["exec", "my-feature", "--", "true"]) == 1
    assert "cannot acquire feature execution lock: locking unavailable" in capsys.readouterr().err


def test_exec_allows_merged_worktree_inspection(feature: Path):
    assert main(["merge", "my-feature"]) == 0
    assert main(["exec", "my-feature", "--", "true"]) == 0


def test_exec_returns_conventional_status_for_child_signal(feature: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "new_feature",
            "exec",
            "my-feature",
            "--",
            sys.executable,
            "-c",
            "import os, signal; os.kill(os.getpid(), signal.SIGTERM)",
        ],
        cwd=feature,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 143, result.stderr
