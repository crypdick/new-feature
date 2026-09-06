from __future__ import annotations

import subprocess
from threading import Event, Thread

import pytest

from new_feature import cli, git
from new_feature.allocator import allocate_env
from new_feature.config import PortEnvSpec, ProjectConfig
from new_feature.errors import NewFeatureError
from new_feature.manifest import FeatureRecord, Manifest, load_manifest, save_manifest
from tests.conftest import init_git_repo


def test_failed_target_checkout_preserves_current_branch(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["create", "demo", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees/demo"
    (worktree / "feature.txt").write_text("feature\n")
    subprocess.run(["git", "add", "."], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Feature"], cwd=worktree, check=True)
    subprocess.run(["git", "checkout", "-b", "other"], check=True)
    (tmp_path / "other.txt").write_text("preserve me\n")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", "Other"], check=True)
    before = git.resolve_revision(tmp_path, "HEAD")
    subprocess.run(["git", "worktree", "add", str(tmp_path / ".worktrees/target"), "main"], check=True)

    assert cli.main(["merge", "demo"]) == 1

    assert git.worktree_branch(tmp_path) == "other"
    assert git.resolve_revision(tmp_path, "HEAD") == before
    assert (tmp_path / "other.txt").read_text() == "preserve me\n"


def test_setup_owns_feature_until_ready(tmp_path, monkeypatch):
    init_git_repo(tmp_path, '[tool.new-feature]\nsetup = ["false"]\n')
    started, release = Event(), Event()
    errors = []
    run_commands = cli.run_commands

    def gated(commands, **kwargs):
        if commands == ["false"]:
            started.set()
            assert release.wait(5)
        return run_commands(commands, **kwargs)

    def create():
        try:
            cli._dispatch(cli.parse_args(["create", "demo", "--no-agent"]), tmp_path)
        except NewFeatureError as error:
            errors.append(str(error))

    monkeypatch.setattr(cli, "run_commands", gated)
    worker = Thread(target=create)
    worker.start()
    assert started.wait(5)
    try:
        for args in (
            ["create", "demo", "--no-agent"],
            ["merge", "demo"],
            ["teardown", "demo"],
            ["doctor", "--repair"],
        ):
            with pytest.raises(NewFeatureError, match="feature operation already in progress"):
                cli._dispatch(cli.parse_args(args), tmp_path)
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert errors == ["command failed with exit code 1: false"]
    assert not (tmp_path / ".worktrees/demo").exists()


def test_interrupted_setup_cannot_be_reopened_or_merged(tmp_path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["create", "demo", "--no-agent"]) == 0
    manifest = load_manifest(tmp_path)
    manifest.features["demo"].status = "initializing"
    save_manifest(tmp_path, manifest)
    for args in (["create", "demo", "--no-agent"], ["create", "demo", "--dry-run"], ["merge", "demo"]):
        assert cli.main(args) == 1
        assert "setup did not complete" in capsys.readouterr().err
    assert cli.main(["doctor", "--repair"]) == 1
    assert "setup-incomplete" in capsys.readouterr().out
    assert (tmp_path / ".worktrees/demo").exists()
    assert cli.main(["teardown", "demo"]) == 0


def test_port_allocations_share_reservations_across_keys(tmp_path, monkeypatch):
    # Availability is independent of the reservation invariant under test.
    monkeypatch.setattr("new_feature.allocator._port_available", lambda _port: True)
    config = ProjectConfig(env={"WEB_PORT": PortEnvSpec(42000, 42003), "API_PORT": PortEnvSpec(42000, 42003)})
    manifest = Manifest(
        features={
            "previous": FeatureRecord(
                name="previous",
                slug="previous",
                branch="previous",
                worktree=".worktrees/previous",
                target_branch="main",
                status="active",
                created_at="",
                env={"WEB_PORT": "42001", "API_PORT": "42000"},
            )
        }
    )

    env = allocate_env(
        config=config,
        manifest=manifest,
        name="demo",
        slug="demo",
        branch="demo",
        worktree=tmp_path / "demo",
        repo_root=tmp_path,
    )

    assert env["WEB_PORT"] == "42002"
    assert env["API_PORT"] == "42003"


@pytest.mark.parametrize("external_merge", [False, True])
def test_merge_reconciles_already_integrated_active_feature(tmp_path, monkeypatch, external_merge):
    init_git_repo(tmp_path, '[tool.new-feature]\npre_merge = ["false"]\npost_merge = ["false"]\n')
    monkeypatch.chdir(tmp_path)
    assert cli.main(["create", "demo", "--no-agent"]) == 0
    if external_merge:
        worktree = tmp_path / ".worktrees/demo"
        (worktree / "feature.txt").write_text("feature\n")
        subprocess.run(["git", "add", "."], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "Feature"], cwd=worktree, check=True)
        subprocess.run(["git", "merge", "demo"], check=True)
    before = git.resolve_revision(tmp_path, "HEAD")
    assert cli.main(["merge", "demo"]) == 0
    assert git.resolve_revision(tmp_path, "HEAD") == before
    assert load_manifest(tmp_path).features["demo"].status == "merged"
    assert cli.main(["merge", "demo"]) == 0


def test_merge_rechecks_integration_after_pre_merge(tmp_path, monkeypatch):
    init_git_repo(
        tmp_path,
        """
[tool.new-feature] # temporal-ok
pre_merge = ['git -C "$NEW_FEATURE_REPO_ROOT" merge "$NEW_FEATURE_BRANCH"']
post_merge = ["false"]
""",
    )
    monkeypatch.chdir(tmp_path)
    assert cli.main(["create", "demo", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees/demo"
    (worktree / "feature.txt").write_text("feature\n")
    subprocess.run(["git", "add", "."], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Feature"], cwd=worktree, check=True)
    feature_head = git.resolve_revision(worktree, "HEAD")
    assert cli.main(["merge", "demo"]) == 0
    assert git.resolve_revision(tmp_path, "HEAD") == feature_head
    assert load_manifest(tmp_path).features["demo"].status == "merged"


def test_doctor_tolerates_teardown_between_inspection_and_repair(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["create", "demo", "--no-agent"]) == 0
    inspect_feature = cli.inspect_feature

    def inspect_then_teardown(*args):
        state = inspect_feature(*args)
        assert cli.main(["teardown", "demo"]) == 0
        return state

    monkeypatch.setattr(cli, "inspect_feature", inspect_then_teardown)
    assert cli.main(["doctor", "--repair"]) == 0
    assert not load_manifest(tmp_path).features


def test_merge_requires_clean_target_checkout(tmp_path, monkeypatch, capsys) -> None:
    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)

    assert cli.main(["my-feature", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees" / "my-feature"
    (worktree / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Feature"], cwd=worktree, check=True)
    (tmp_path / "unfinished.txt").write_text("user work\n", encoding="utf-8")

    assert cli.main(["merge", "my-feature"]) == 1
    assert "target checkout has uncommitted changes" in capsys.readouterr().err
