from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature.gitignore import ensure_generated_paths_ignored
from new_feature.rule_checker import should_block

if TYPE_CHECKING:
    from pathlib import Path


def blocked(paths: tuple[Path, ...], *, cwd: Path) -> bool:
    return should_block(
        "target-branch",
        {
            "kind": "file_edit",
            "cwd": str(cwd),
            "paths": [str(path) for path in paths],
        },
    )


def test_policy_allows_bootstrap_until_the_first_commit(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    request = (tmp_path / "README.md",)
    assert not blocked(request, cwd=tmp_path)
    init_git_repo(tmp_path)
    assert blocked(request, cwd=tmp_path)
    subprocess.run(["git", "checkout", "--orphan", "orphan"], cwd=tmp_path, check=True)
    (tmp_path / ".new-feature.toml").write_text('target_branch = "orphan"\n', encoding="utf-8")
    assert blocked(request, cwd=tmp_path)


@pytest.mark.parametrize("relative", [False, True])
def test_policy_allows_ignored_untracked_sidecars(tmp_path: Path, relative: bool) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    sidecar = tmp_path / ".new-feature.local.toml"
    target = sidecar.relative_to(tmp_path) if relative else sidecar
    assert blocked((target,), cwd=tmp_path)
    ensure_generated_paths_ignored(tmp_path)
    assert not blocked((target,), cwd=tmp_path)
    assert blocked((target, tmp_path / "README.md"), cwd=tmp_path)
    nested = tmp_path / "nested/.new-feature.local.toml"
    assert not blocked((nested,), cwd=tmp_path)
    sidecar.write_text("push = false\n", encoding="utf-8")
    subprocess.run(["git", "add", "--force", sidecar.name], cwd=tmp_path, check=True)
    assert blocked((target,), cwd=tmp_path)


def test_policy_rejects_a_sidecar_symlink_to_tracked_source(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    source = tmp_path / "config-source.toml"
    source.write_text("push = false\n", encoding="utf-8")
    subprocess.run(["git", "add", source.name], cwd=tmp_path, check=True)
    ensure_generated_paths_ignored(tmp_path)
    sidecar = tmp_path / ".new-feature.local.toml"
    sidecar.symlink_to(source)
    assert blocked((sidecar,), cwd=tmp_path)


@pytest.mark.parametrize("relative", [False, True])
def test_policy_allows_files_in_ignored_directories(tmp_path: Path, relative: bool) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("drafts/\n", encoding="utf-8")
    draft = tmp_path / "drafts/nested/new note.md"
    target = draft.relative_to(tmp_path) if relative else draft
    assert not blocked((target,), cwd=tmp_path)
    draft.parent.mkdir(parents=True)
    draft.write_text("local work", encoding="utf-8")
    assert not blocked((target,), cwd=tmp_path)
    assert blocked((target, tmp_path / "README.md"), cwd=tmp_path)
    subprocess.run(["git", "add", "--force", str(draft)], cwd=tmp_path, check=True)
    assert blocked((target,), cwd=tmp_path)


def test_policy_rejects_ignored_directory_symlink_to_tracked_source(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("drafts/\n", encoding="utf-8")
    (tmp_path / "drafts").symlink_to(tmp_path, target_is_directory=True)
    assert blocked((tmp_path / "drafts/README.md",), cwd=tmp_path)


def test_policy_rejects_ignored_symlink_outside_repository(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    project = tmp_path / "project"
    project.mkdir()
    init_git_repo(project)
    (project / ".gitignore").write_text("drafts\n", encoding="utf-8")
    (project / "drafts").symlink_to(tmp_path / "external-file")
    assert blocked((project / "drafts",), cwd=project)


def shell_blocked(command: str, *, cwd: Path) -> bool:
    return should_block("target-branch", {"kind": "shell", "cwd": str(cwd), "command": command})


@pytest.mark.parametrize(
    "command",
    [
        "sed -i s/demo/x/ README.md",
        "sed -i.bak -e s/demo/x/ README.md",
        "perl -pi -e s/demo/x/ README.md",
        "cat > README.md <<'EOF'\nx\nEOF",
        "echo x >>README.md",
        "printf x 2>/dev/null >| README.md",
        "echo x &> README.md",
        "echo x | tee -a README.md",
        "cp /etc/hostname README.md",
        "mv README.md moved.md",
        "rm -f README.md",
        "rm -- README.md",
        "truncate -s 0 README.md",
        "cd sub && echo x > ../README.md",
        "touch new-file.py",
    ],
)
def test_policy_rejects_shell_writes_on_target_branch(tmp_path: Path, command: str) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    (tmp_path / "sub").mkdir()
    assert shell_blocked(command, cwd=tmp_path)


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "FOO=bar",
        "echo x | tee -",
        "cat README.md",
        "sed s/demo/x/ README.md",
        "grep demo README.md > /dev/null 2>&1",
        "echo x > drafts/note.md",
        "rm -rf drafts",
        "cp README.md /tmp/elsewhere.md",
        "echo x > /tmp/elsewhere.md",
    ],
)
def test_policy_allows_shell_reads_and_ignored_writes(tmp_path: Path, command: str) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("drafts/\n", encoding="utf-8")
    (tmp_path / "drafts").mkdir()
    assert not shell_blocked(command, cwd=tmp_path)


def test_policy_allows_shell_writes_on_feature_branch(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=tmp_path, check=True)
    assert not shell_blocked("sed -i s/demo/x/ README.md", cwd=tmp_path)


def shell_changed(command: str, *, cwd: Path) -> bool:
    event = {"kind": "shell", "cwd": str(cwd), "command": command}
    assert not should_block("target-branch", event)
    return should_block("target-shell-changes", event)


def test_post_check_flags_tracked_changes_from_unparsed_shell_writes(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    readme = tmp_path / "README.md"
    assert not shell_changed("true", cwd=tmp_path)
    event = {"kind": "shell", "cwd": str(tmp_path), "command": "python3 edit.py"}
    assert not should_block("target-branch", event)
    readme.write_text("# changed by a script\n", encoding="utf-8")
    assert should_block("target-shell-changes", event)


def test_post_check_ignores_changes_present_before_the_command(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("# human edit\n", encoding="utf-8")
    assert not shell_changed("git status", cwd=tmp_path)
    event = {"kind": "shell", "cwd": str(tmp_path), "command": "python3 edit.py"}
    assert not should_block("target-branch", event)
    readme.write_text("# human edit, then a script\n", encoding="utf-8")
    assert should_block("target-shell-changes", event)
    assert not should_block("target-shell-changes", event)


def test_post_check_flags_deleted_tracked_files_and_skips_feature_branches(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    event = {"kind": "shell", "cwd": str(tmp_path), "command": "python3 cleanup.py"}
    assert not should_block("target-branch", event)
    (tmp_path / "README.md").unlink()
    assert should_block("target-shell-changes", event)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=tmp_path, check=True)
    assert not should_block("target-shell-changes", event)


def test_post_check_without_a_record_flags_existing_changes(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("# changed\n", encoding="utf-8")
    event = {"kind": "shell", "cwd": str(tmp_path), "command": "python3 edit.py"}
    assert should_block("target-shell-changes", event)
