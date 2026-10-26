"""Inspect staged and working-tree changes in one managed checkout."""

from __future__ import annotations

import json
import subprocess  # noqa: S404 - invoke Git with literal argv
import sys
from pathlib import Path  # noqa: TC003 - beartype requires annotation types at runtime
from typing import cast

from new_feature.control_checkout import require_managed_worktree
from new_feature.errors import NewFeatureError
from new_feature.git import git_environment, inert_git_options
from new_feature.inspection import write_json
from new_feature.lifecycle import now
from new_feature.manifest import FeatureRecord, feature_execution_lock, load_manifest
from new_feature.slug import feature_key, slugify

_STATUS_LABELS = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "T": "type-changed",
    "U": "unmerged",
}
_CONFLICTS = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


def inspect_changes(
    root: Path, name: str, *, json_output: bool, expected_generation: str | None = None
) -> int:
    """Report a change snapshot only if checkout identity remains unchanged."""
    slug = slugify(name)
    with feature_execution_lock(root, slug):
        record = load_manifest(root).features.get(feature_key(slug))
        if record is None:
            raise NewFeatureError(f"unknown feature: {name}")
        if expected_generation is not None and (
            not record.generation or expected_generation != record.generation
        ):
            raise NewFeatureError(f"feature generation changed: {slug}; refresh inventory")
        try:
            identity = _checkout_identity(root, record)
            changes = _read_changes(root / record.worktree)
            current = load_manifest(root).features.get(feature_key(slug))
            if current != record or identity != _checkout_identity(root, record):
                raise NewFeatureError(f"feature changed during inspection: {slug}; refresh inventory")
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
            raise NewFeatureError(f"cannot inspect feature changes: {exc}") from exc
        report: dict[str, object] = {
            "command": "changes",
            "ok": True,
            "slug": record.slug,
            "branch": record.branch,
            "worktree": str((root / record.worktree).resolve()),
            "generation": record.generation or None,
            "observed_at": now(),
            "changes": changes,
        }
        # NOTE: README.md documents snapshot generation guards and change states.
        if json_output:
            write_json(report)
        else:
            _write_human(report, changes)
    return 0


def _checkout_identity(root: Path, record: FeatureRecord) -> tuple[int, int, int, int, bytes]:
    worktree = require_managed_worktree(root, root / record.worktree, record.branch)
    directory = worktree.stat()
    git_file = worktree / ".git"
    marker = git_file.stat()
    return directory.st_dev, directory.st_ino, marker.st_dev, marker.st_ino, git_file.read_bytes()


def _read_changes(worktree: Path) -> dict[str, object]:
    result = subprocess.run(  # noqa: S603 - literal Git command with inert configuration options
        [  # noqa: S607 - Git is a required executable on PATH
            "git",
            "--no-optional-locks",
            *inert_git_options(worktree),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        cwd=worktree,
        env=git_environment(),
        capture_output=True,
        check=False,
        timeout=5,
    )
    if result.returncode:
        raise NewFeatureError(f"git status failed: {result.stderr.decode('utf-8', errors='replace').strip()}")
    fields = iter(result.stdout.decode("utf-8").split("\0"))
    files: list[dict[str, str]] = []
    summary = dict.fromkeys(
        ("modified", "added", "deleted", "renamed", "untracked", "staged", "conflicts"), 0
    )
    for field in fields:
        if not field:
            continue
        status, path = field[:2], field[3:]
        if len(field) < 4 or field[2] != " ":
            raise NewFeatureError("invalid git status output")
        item = {"path": path}
        category = _describe_status(status, item)
        if "R" in status or "C" in status:
            original = next(fields, "")
            if not original:
                raise NewFeatureError("invalid git rename output")
            item["original_path"] = original
        summary[category] += 1
        if status[0] not in {" ", "?"} and status not in _CONFLICTS:
            summary["staged"] += 1
        files.append(item)
    return {
        "state": "modified" if files else "clean",
        "summary": summary,
        "files": sorted(files, key=lambda item: item["path"]),
    }


def _describe_status(status: str, item: dict[str, str]) -> str:
    if status == "??":
        item["worktree"] = "untracked"
        return "untracked"
    if status in _CONFLICTS:
        item.update(index="unmerged", worktree="unmerged")
        return "conflicts"
    for side, code in zip(("index", "worktree"), status, strict=True):
        if code != " ":
            if code not in _STATUS_LABELS:
                raise NewFeatureError("invalid git status code")
            item[side] = _STATUS_LABELS[code]
    for code, category in (("D", "deleted"), ("A", "added"), ("R", "renamed")):
        if code in status:
            return category
    return "modified"


def _write_human(report: dict[str, object], changes: dict[str, object]) -> None:
    sys.stdout.write(
        f"{json.dumps(report['worktree'])} generation={report['generation']} observed_at={report['observed_at']}\n"
    )
    files = cast("list[dict[str, str]]", changes["files"])
    if not files:
        sys.stdout.write("No changed files\n")
    for item in files:
        original = f"{json.dumps(item['original_path'])} -> " if "original_path" in item else ""
        sys.stdout.write(
            f"{item.get('index', '-')}\t{item.get('worktree', '-')}\t{original}{json.dumps(item['path'])}\n"
        )
