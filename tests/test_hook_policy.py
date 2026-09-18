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
def test_policy_allows_only_the_ignored_root_sidecar(tmp_path: Path, relative: bool) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    sidecar = tmp_path / ".new-feature.local.toml"
    target = sidecar.relative_to(tmp_path) if relative else sidecar
    assert blocked((target,), cwd=tmp_path)
    ensure_generated_paths_ignored(tmp_path)
    assert not blocked((target,), cwd=tmp_path)
    assert blocked((target, tmp_path / "README.md"), cwd=tmp_path)
    nested = tmp_path / "nested/.new-feature.local.toml"
    assert blocked((nested,), cwd=tmp_path)
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
