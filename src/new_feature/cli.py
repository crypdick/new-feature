from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from new_feature.agent import build_initial_prompt, launch_interactive_agent
from new_feature.allocator import allocate_env
from new_feature.commands import run_commands
from new_feature.config import load_project_config
from new_feature.errors import NewFeatureError
from new_feature.git import (
    abort_merge,
    begin_merge_without_commit,
    commit_merge,
    create_worktree,
    is_branch_merged,
    push_target,
    remove_worktree_and_branch,
    repo_root,
    worktree_is_clean,
)
from new_feature.gitignore import ensure_generated_paths_ignored
from new_feature.manifest import FeatureRecord, load_manifest, manifest_lock, save_manifest
from new_feature.slug import feature_key, slugify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="new-feature",
        description="Create isolated feature worktrees and launch an interactive agent.",
    )
    subparsers = parser.add_subparsers(dest="command")

    create = subparsers.add_parser("create", help="create a feature worktree")
    create.add_argument("name")
    create.add_argument("--no-agent", action="store_true")
    create.add_argument("--dry-run", action="store_true")
    create.set_defaults(command="create")

    merge = subparsers.add_parser("merge-feature")
    merge.add_argument("name")
    merge.set_defaults(command="merge-feature")

    teardown = subparsers.add_parser("teardown")
    teardown.add_argument("name")
    teardown.add_argument("--force", action="store_true")
    teardown.set_defaults(command="teardown")
    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    if argv and argv[0] not in {"create", "merge-feature", "teardown"} and not argv[0].startswith("-"):
        argv = ["create", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.error("feature name or subcommand is required")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        root = repo_root(Path.cwd())
        if args.command == "create":
            return _create(root, args.name, no_agent=args.no_agent, dry_run=args.dry_run)
        if args.command == "merge-feature":
            return _merge_feature(root, args.name)
        if args.command == "teardown":
            return _teardown(root, args.name, force=args.force)
        raise NewFeatureError(f"unknown command: {args.command}")
    except NewFeatureError as exc:
        print(f"new-feature: {exc}", file=sys.stderr)
        return 1


def _create(root: Path, name: str, *, no_agent: bool, dry_run: bool) -> int:
    config = load_project_config(root)
    slug = slugify(name)
    key = feature_key(slug)
    branch = f"{config.branch_prefix}{slug}"
    worktree = root / ".worktrees" / slug

    ensure_generated_paths_ignored(root)
    with manifest_lock(root):
        manifest = load_manifest(root)
        if key in manifest.features:
            raise NewFeatureError(f"feature already exists: {slug}")
        env = allocate_env(
            config=config,
            manifest=manifest,
            name=name,
            slug=slug,
            branch=branch,
            worktree=worktree,
            repo_root=root,
        )
        if dry_run:
            for env_key, env_value in sorted(env.items()):
                print(f"{env_key}={env_value}")
            return 0
        create_worktree(root, branch=branch, worktree=worktree, target_branch=config.target_branch)
        manifest.features[key] = FeatureRecord(
            name=name,
            slug=slug,
            branch=branch,
            worktree=str(worktree.relative_to(root)),
            target_branch=config.target_branch,
            status="active",
            created_at=_now(),
            env=env,
        )
        save_manifest(root, manifest)

    run_commands(config.setup, cwd=worktree, env=env)
    if no_agent:
        return 0
    prompt = build_initial_prompt(slug)
    return launch_interactive_agent(config.agent, worktree, env, prompt)


def _merge_feature(root: Path, name: str) -> int:
    config = load_project_config(root)
    key = feature_key(slugify(name))
    with manifest_lock(root):
        manifest = load_manifest(root)
        record = manifest.features.get(key)
        if record is None:
            raise NewFeatureError(f"unknown feature: {name}")
    worktree = root / record.worktree
    run_commands(config.pre_merge, cwd=worktree, env=record.env)
    if not worktree_is_clean(worktree):
        raise NewFeatureError("feature worktree has uncommitted changes; commit them before merging")
    if not worktree_is_clean(root):
        raise NewFeatureError("target checkout has uncommitted changes; commit or stash them before merging")
    begin_merge_without_commit(root, branch=record.branch, target_branch=record.target_branch)
    try:
        run_commands(config.post_merge, cwd=root, env=record.env)
    except NewFeatureError:
        abort_merge(root)
        raise
    commit_merge(root, name=record.name)
    if config.push:
        push_target(root, target_branch=record.target_branch)
    with manifest_lock(root):
        manifest = load_manifest(root)
        record = manifest.features.get(key)
        if record is None:
            raise NewFeatureError(f"unknown feature after merge: {name}")
        record.status = "merged"
        record.merged_at = _now()
        save_manifest(root, manifest)
    return 0


def _teardown(root: Path, name: str, *, force: bool) -> int:
    config = load_project_config(root)
    key = feature_key(slugify(name))
    with manifest_lock(root):
        manifest = load_manifest(root)
        record = manifest.features.get(key)
        if record is None:
            raise NewFeatureError(f"unknown feature: {name}")
    worktree = root / record.worktree
    if not force:
        if not worktree_is_clean(worktree):
            raise NewFeatureError("feature worktree has uncommitted changes; pass --force to abandon them")
        if not is_branch_merged(root, branch=record.branch, target_branch=record.target_branch):
            raise NewFeatureError("feature branch has unmerged commits; pass --force to abandon them")
    run_commands(config.teardown, cwd=worktree, env=record.env)
    remove_worktree_and_branch(root, branch=record.branch, worktree=worktree, force=force)
    with manifest_lock(root):
        manifest = load_manifest(root)
        del manifest.features[key]
        save_manifest(root, manifest)
    return 0


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
