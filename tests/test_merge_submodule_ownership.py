from __future__ import annotations

import subprocess

import pytest

from new_feature import cli
from tests.conftest import init_git_repo


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def prepare(root, monkeypatch):
    dependency = root / "dependency"
    dependency.mkdir()
    init_git_repo(dependency)
    project = root / "project"
    project.mkdir()
    init_git_repo(project)
    git(project, "-c", "protocol.file.allow=always", "submodule", "add", str(dependency), "vendor/lib")
    git(project, "commit", "-am", "Add dependency")
    module = project / "vendor/lib"
    before = git(module, "rev-parse", "HEAD")
    (dependency / "README.md").write_text("updated dependency\n")
    git(dependency, "commit", "-am", "Update dependency")
    incoming = git(dependency, "rev-parse", "HEAD")
    git(module, "fetch", "origin")
    monkeypatch.chdir(project)
    assert cli.main(["create", "demo", "--no-agent"]) == 0
    feature = project / ".worktrees/demo"
    git(feature, "update-index", "--cacheinfo", f"160000,{incoming},vendor/lib")
    git(feature, "commit", "-m", "Bump dependency")
    return project, module, before, incoming


def test_post_merge_can_reconcile_owned_submodule_pin(tmp_path, monkeypatch):
    project, module, before, incoming = prepare(tmp_path, monkeypatch)
    observed = []

    def gate(_commands, *, cwd, **_kwargs):
        if cwd == project:
            observed.append(git(module, "rev-parse", "HEAD"))
            git(project, "submodule", "update", "--no-fetch", "--checkout", "vendor/lib")

    monkeypatch.setattr(cli, "run_commands", gate)
    assert cli.main(["merge", "demo"]) == 0
    assert observed == [before]
    assert git(module, "rev-parse", "HEAD") == incoming
    assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("change", ["tracked", "untracked", "commit"])
def test_post_merge_preserves_independent_submodule_work(tmp_path, monkeypatch, change):
    project, module, _before, _incoming = prepare(tmp_path, monkeypatch)
    observed = []

    def gate(_commands, *, cwd, **_kwargs):
        if cwd != project:
            return
        git(project, "submodule", "update", "--no-fetch", "--checkout", "vendor/lib")
        target = module / ("private.txt" if change == "untracked" else "README.md")
        target.write_text("independent work\n")
        if change == "commit":
            git(
                module,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-am",
                "User work",
            )
        observed.append((git(module, "rev-parse", "HEAD"), git(module, "status", "--porcelain")))

    monkeypatch.setattr(cli, "run_commands", gate)
    assert cli.main(["merge", "demo"]) == 1
    assert observed
    assert observed == [(git(module, "rev-parse", "HEAD"), git(module, "status", "--porcelain"))]
    assert (
        module / ("private.txt" if change == "untracked" else "README.md")
    ).read_text() == "independent work\n"


@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("fail_gate", [False, True])
def test_clean_submodule_reconciliation_keeps_failure_recovery_conservative(
    tmp_path, monkeypatch, complete, fail_gate
):
    project, module, _before, incoming = prepare(tmp_path, monkeypatch)
    captured = []

    def gate(_commands, *, cwd, **_kwargs):
        if cwd != project:
            return
        git(project, "submodule", "update", "--no-fetch", "--checkout", "vendor/lib")
        if complete:
            git(project, "commit", "-m", "Complete prepared merge")
        captured.append((git(project, "rev-parse", "HEAD"), git(project, "write-tree")))
        if fail_gate:
            raise cli.NewFeatureError("post-merge failed")

    monkeypatch.setattr(cli, "run_commands", gate)
    assert cli.main(["merge", "demo"]) == (1 if fail_gate else 0)
    assert git(module, "rev-parse", "HEAD") == incoming
    if fail_gate:
        assert captured == [(git(project, "rev-parse", "HEAD"), git(project, "write-tree"))]
    else:
        assert not git(project, "status", "--porcelain")


@pytest.mark.parametrize("change", ["tracked", "untracked", "branch", "deinitialize"])
def test_submodule_interference_before_prepared_is_preserved(tmp_path, monkeypatch, change):
    _project, module, _before, _incoming = prepare(tmp_path, monkeypatch)
    merge = cli.merge_feature_branch

    def interrupted(root, **kwargs):
        merge(root, **kwargs)
        if change == "deinitialize":
            (module / ".git").rename(module / "preserved-git")
        elif change == "branch":
            git(module, "switch", "-c", "user-branch")
        else:
            (module / ("user.txt" if change == "untracked" else "README.md")).write_text("user work\n")

    monkeypatch.setattr(cli, "merge_feature_branch", interrupted)
    assert cli.main(["merge", "demo"]) == 1
    if change == "deinitialize":
        assert (module / "preserved-git").is_file()
    elif change == "branch":
        assert git(module, "branch", "--show-current") == "user-branch"
    else:
        assert (module / ("user.txt" if change == "untracked" else "README.md")).read_text() == "user work\n"
