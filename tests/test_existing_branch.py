from __future__ import annotations

import subprocess

import pytest

from new_feature.cli import main
from new_feature.manifest import load_manifest
from tests.conftest import init_git_repo


def test_existing_branch_stays_inert_until_explicit_bootstrap(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    subprocess.run(["git", "branch", "review"], cwd=tmp_path, check=True)
    (tmp_path / ".new-feature.toml").write_text(
        'setup = ["touch bootstrapped"]\nteardown = ["touch cleaned"]\n'
    )
    monkeypatch.chdir(tmp_path)
    assert main(["create", "review", "--from", "review"]) == 0
    worktree = tmp_path / ".worktrees" / "review"
    assert not (worktree / "bootstrapped").exists()
    record = load_manifest(tmp_path).features["review"]
    assert record.status == "inert"
    assert record.owns_branch is False
    assert main(["exec", "review", "--", "true"]) == 1
    assert main(["create", "review", "--bootstrap", "--no-agent"]) == 0
    assert (worktree / "bootstrapped").exists()
    assert load_manifest(tmp_path).features["review"].status == "active"


def test_inert_teardown_preserves_existing_branch_and_skips_cleanup(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    subprocess.run(["git", "branch", "review"], cwd=tmp_path, check=True)
    (tmp_path / ".new-feature.toml").write_text('teardown = ["exit 9"]\n')
    monkeypatch.chdir(tmp_path)
    assert main(["create", "review", "--from", "review"]) == 0
    assert main(["teardown", "review"]) == 0
    assert not (tmp_path / ".worktrees" / "review").exists()
    subprocess.run(["git", "show-ref", "--verify", "refs/heads/review"], cwd=tmp_path, check=True)


def test_remote_branch_import_creates_owned_local_branch(tmp_path, monkeypatch, capsys):
    import json

    init_git_repo(tmp_path)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/review", "HEAD"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["create", "review-copy", "--from", "origin/review", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["feature"]["status"] == "inert"
    assert load_manifest(tmp_path).features["review_copy"].owns_branch is True
    assert main(["teardown", "review-copy"]) == 0
    subprocess.run(["git", "show-ref", "--verify", "refs/remotes/origin/review"], cwd=tmp_path, check=True)
    assert (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/heads/review-copy"], cwd=tmp_path, check=False
        ).returncode
        == 1
    )


def test_import_suppresses_hooks_smudge_process_and_fsmonitor(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    (tmp_path / ".gitattributes").write_text("README.md filter=unsafe\n")
    subprocess.run(["git", "add", ".gitattributes"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "attributes"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "review"], cwd=tmp_path, check=True)
    marker = tmp_path / "executed"
    hook = tmp_path / ".git/hooks/post-checkout"
    hook.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    hook.chmod(0o755)
    monitor = tmp_path / ".git/monitor"
    monitor.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    monitor.chmod(0o755)
    for key, value in [
        ("core.fsmonitor", str(monitor)),
        ("filter.unsafe.smudge", f'touch "{marker}"; cat'),
        ("filter.unsafe.process", f'touch "{marker}"; exit 1'),
        ("filter.unsafe.required", "true"),
    ]:
        subprocess.run(["git", "config", key, value], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["create", "review", "--from", "review"]) == 0
    assert not marker.exists()
    assert (tmp_path / ".worktrees/review/README.md").read_text() == "# demo\n"


def test_clean_only_filter_does_not_prevent_import(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    subprocess.run(["git", "branch", "review"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "filter.clean-only.clean", "cat"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["create", "review", "--from", "review"]) == 0
    assert load_manifest(tmp_path).features["review"].status == "inert"


def test_import_ignores_default_agent_and_bootstrap_failure_preserves_work(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    subprocess.run(["git", "branch", "review"], cwd=tmp_path, check=True)
    (tmp_path / ".new-feature.toml").write_text(
        'default_agent="missing-agent"\nsetup=["echo preserve > valuable; exit 7"]\nteardown=["exit 9"]\n'
    )
    monkeypatch.chdir(tmp_path)
    assert main(["create", "review", "--from", "review"]) == 0
    worktree = tmp_path / ".worktrees/review"
    assert main(["create", "review", "--bootstrap", "--no-agent"]) == 1
    assert (worktree / "valuable").read_text() == "preserve\n"
    record = load_manifest(tmp_path).features["review"]
    assert record.status == "inert"
    assert record.owns_branch is False
    assert main(["teardown", "review"]) == 1
    assert main(["teardown", "review", "--force"]) == 0
    subprocess.run(["git", "show-ref", "--verify", "refs/heads/review"], cwd=tmp_path, check=True)


def test_imported_local_branch_under_new_name_owns_only_copy(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    subprocess.run(["git", "branch", "review"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["create", "copy", "--from", "refs/heads/review"]) == 0
    assert load_manifest(tmp_path).features["copy"].owns_branch is True
    assert main(["teardown", "copy"]) == 0
    subprocess.run(["git", "show-ref", "--verify", "refs/heads/review"], cwd=tmp_path, check=True)
    assert (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/heads/copy"], cwd=tmp_path, check=False
        ).returncode
        == 1
    )


@pytest.mark.parametrize("source", ["missing", "--help", "main~0", "refs/tags/review"])
def test_import_rejects_nonbranch_sources_without_creating_feature(tmp_path, monkeypatch, source):
    init_git_repo(tmp_path)
    subprocess.run(["git", "tag", "review"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/heads/main"], cwd=tmp_path, check=True
    )
    monkeypatch.chdir(tmp_path)
    assert main(["create", "imported", "--from=" + source]) == 1
    assert not (tmp_path / ".worktrees/imported").exists()
    assert not load_manifest(tmp_path).features
    assert (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/heads/imported"], cwd=tmp_path, check=False
        ).returncode
        == 1
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["--from", "main", "--bootstrap"],
        ["--from", "main", "--agent", "codex"],
        ["--from", "main", "--prompt", "hello"],
        ["--bootstrap", "--dry-run"],
    ],
)
def test_import_rejects_incompatible_options(tmp_path, monkeypatch, arguments):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["create", "imported", *arguments, "--json"]) == 2
    assert not (tmp_path / ".worktrees/imported").exists()
    assert not load_manifest(tmp_path).features


def test_import_resolves_remote_default_branch_alias(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"],
        cwd=tmp_path,
        check=True,
    )
    monkeypatch.chdir(tmp_path)
    assert main(["create", "imported", "--from", "origin/HEAD"]) == 0
    assert load_manifest(tmp_path).features["imported"].status == "inert"
