from __future__ import annotations

import subprocess

import pytest

from new_feature import cli
from new_feature.git import resolve_revision
from new_feature.manifest import load_manifest
from tests.conftest import init_git_repo


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def prepare(root, monkeypatch):
    init_git_repo(root)
    monkeypatch.chdir(root)
    assert cli.main(["create", "demo", "--no-agent"]) == 0
    feature = root / ".worktrees/demo"
    (feature / "feature.txt").write_text("feature\n")
    git(feature, "add", "feature.txt")
    git(feature, "commit", "-m", "Feature")
    return resolve_revision(root, "HEAD")


@pytest.mark.parametrize("fail_gate", [False, True])
def test_gate_completed_exact_merge_is_preserved(tmp_path, monkeypatch, fail_gate):
    before = prepare(tmp_path, monkeypatch)
    completed = []

    def gate(_commands, *, cwd, **_kwargs):
        if cwd == tmp_path:
            git(cwd, "commit", "-m", "Manually complete merge")
            completed.append(resolve_revision(cwd, "HEAD"))
            if fail_gate:
                raise cli.NewFeatureError("gate failed after manual commit")

    monkeypatch.setattr(cli, "run_commands", gate)
    assert cli.main(["merge", "demo"]) == (1 if fail_gate else 0)
    assert resolve_revision(tmp_path, "HEAD") == completed[0] != before
    assert load_manifest(tmp_path).features["demo"].status == ("active" if fail_gate else "merged")
    assert not git(tmp_path, "status", "--porcelain")


@pytest.mark.parametrize("change", ["commit", "staged", "unstaged", "untracked", "branch", "quit", "feature"])
@pytest.mark.parametrize("fail_gate", [False, True])
def test_intervening_work_is_never_committed_or_erased(tmp_path, monkeypatch, capsys, change, fail_gate):
    before = prepare(tmp_path, monkeypatch)
    state = []

    def gate(_commands, *, cwd, **_kwargs):
        if cwd != tmp_path:
            return
        if change in {"commit", "branch"}:
            git(cwd, "commit", "-m", "Manual merge")
            if change == "commit":
                (cwd / "manual.txt").write_text("user work\n")
                git(cwd, "add", "manual.txt")
                git(cwd, "commit", "-m", "Manual followup")
            else:
                git(cwd, "switch", "-c", "manual")
        elif change == "quit":
            git(cwd, "merge", "--quit")
        elif change == "feature":
            feature = cwd / ".worktrees/demo"
            (feature / "later.txt").write_text("later\n")
            git(feature, "add", "later.txt")
            git(feature, "commit", "-m", "Concurrent feature")
        else:
            path = cwd / ("manual.txt" if change == "untracked" else "feature.txt")
            path.write_text("user work\n")
            if change == "staged":
                git(cwd, "add", str(path))
        state.append((
            git(cwd, "rev-parse", "HEAD"),
            git(cwd, "status", "--porcelain"),
            git(cwd, "diff"),
            git(cwd, "diff", "--cached"),
        ))
        if fail_gate:
            raise cli.NewFeatureError("gate failed")

    monkeypatch.setattr(cli, "run_commands", gate)
    assert cli.main(["merge", "demo"]) == 1
    assert "preserv" in capsys.readouterr().err.lower()
    assert state == [
        (
            git(tmp_path, "rev-parse", "HEAD"),
            git(tmp_path, "status", "--porcelain"),
            git(tmp_path, "diff"),
            git(tmp_path, "diff", "--cached"),
        )
    ]
    assert load_manifest(tmp_path).features["demo"].status == "active"
    if change not in {"commit", "branch"}:
        assert resolve_revision(tmp_path, "HEAD") == before


@pytest.mark.parametrize("change", ["branch", "unstaged", "untracked", "parents", "revision"])
def test_unexpected_merge_command_result_is_not_owned(tmp_path, monkeypatch, capsys, change):
    prepare(tmp_path, monkeypatch)
    merge = cli.merge_feature_branch
    observed = []

    def interrupted(root, **kwargs):
        merge(root, **kwargs)
        if change in {"branch", "revision"}:
            git(root, "commit", "-m", "Manual merge")
            if change == "branch":
                git(root, "switch", "-c", "manual")
            else:
                git(root, "commit", "--allow-empty", "-m", "Concurrent unrelated commit")
        elif change == "parents":
            (root / ".git/MERGE_HEAD").write_text(resolve_revision(root, "HEAD") + "\n")
        else:
            (root / ("manual.txt" if change == "untracked" else "feature.txt")).write_text("user work\n")
        observed.append((git(root, "rev-parse", "HEAD"), git(root, "status", "--porcelain")))

    monkeypatch.setattr(cli, "merge_feature_branch", interrupted)
    assert cli.main(["merge", "demo"]) == 1
    assert "preserv" in capsys.readouterr().err
    assert observed == [(git(tmp_path, "rev-parse", "HEAD"), git(tmp_path, "status", "--porcelain"))]


def test_post_commit_hook_edits_are_preserved(tmp_path, monkeypatch, capsys):
    before = prepare(tmp_path, monkeypatch)
    hook = tmp_path / ".git/hooks/post-commit"
    hook.write_text("#!/bin/sh\nprintf 'manual work\\n' > manual.txt\n")
    hook.chmod(0o755)
    assert cli.main(["merge", "demo"]) == 1
    assert "preserv" in capsys.readouterr().err
    assert resolve_revision(tmp_path, "HEAD") != before
    assert (tmp_path / "manual.txt").read_text() == "manual work\n"


def test_unreadable_unmerged_index_stops_rollback(tmp_path, monkeypatch, capsys):
    prepare(tmp_path, monkeypatch)

    def gate(_commands, *, cwd, **_kwargs):
        if cwd != tmp_path:
            return
        blob = git(cwd, "rev-parse", ":feature.txt")
        subprocess.run(
            ["git", "update-index", "--index-info"],
            cwd=cwd,
            text=True,
            check=True,
            input=f"0 {'0' * 40}\tfeature.txt\n100644 {blob} 1\tfeature.txt\n100644 {blob} 2\tfeature.txt\n",
        )
        raise cli.NewFeatureError("gate failed")

    monkeypatch.setattr(cli, "run_commands", gate)
    assert cli.main(["merge", "demo"]) == 1
    assert "cannot verify merge ownership; target checkout preserved" in capsys.readouterr().err
    assert "feature.txt" in git(tmp_path, "ls-files", "--unmerged")


@pytest.mark.parametrize("git_args", [(), ("--no-edit",), ("--ff-only",)])
def test_unchanged_failed_gates_restore_owned_merge(tmp_path, monkeypatch, git_args):
    before = prepare(tmp_path, monkeypatch)
    ignored = tmp_path / "scratch.private"
    (tmp_path / ".git/info/exclude").write_text(".new-feature/\n.worktrees/\nscratch.private\n")
    ignored.write_text("private user data\n")

    def gate(_commands, *, cwd, **_kwargs):
        if cwd == tmp_path:
            raise cli.NewFeatureError("gate failed")

    monkeypatch.setattr(cli, "run_commands", gate)
    assert cli.main(["merge", "demo", *git_args]) == 1
    assert resolve_revision(tmp_path, "HEAD") == before
    assert not git(tmp_path, "status", "--porcelain")
    assert ignored.read_text() == "private user data\n"
