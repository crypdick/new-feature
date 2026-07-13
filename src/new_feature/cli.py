from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from new_feature.agent import build_initial_prompt, launch_interactive_agent
from new_feature.allocator import allocate_env
from new_feature.commands import run_commands
from new_feature.config import ProjectConfig, config_fingerprint, load_project_config
from new_feature.errors import NewFeatureError
from new_feature.feature_state import inspect_feature
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

_COMMANDS = {"create", "merge-feature", "teardown", "list", "doctor"}


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

    feature_list = subparsers.add_parser("list", help="list managed feature worktrees")
    feature_list.set_defaults(command="list")

    doctor = subparsers.add_parser("doctor", help="diagnose manifest and worktree state")
    doctor.add_argument("--repair", action="store_true")
    doctor.set_defaults(command="doctor")
    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    if argv and argv[0] not in _COMMANDS and not argv[0].startswith("-"):
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
        return _dispatch(args, root)
    except NewFeatureError as exc:
        print(f"new-feature: {exc}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace, root: Path) -> int:
    if args.command == "create":
        return _create(root, args.name, no_agent=args.no_agent, dry_run=args.dry_run)
    if args.command == "merge-feature":
        return _merge_feature(root, args.name)
    if args.command == "teardown":
        return _teardown(root, args.name, force=args.force)
    if args.command == "list":
        return _list_features(root)
    if args.command == "doctor":
        return _doctor(root, repair=args.repair)
    raise NewFeatureError(f"unknown command: {args.command}")


def _create(root: Path, name: str, *, no_agent: bool, dry_run: bool) -> int:
    config = load_project_config(root)
    slug = slugify(name)
    key = feature_key(slug)
    branch = f"{config.branch_prefix}{slug}"
    worktree = root / ".worktrees" / slug

    if dry_run:
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
        for env_key, env_value in sorted(env.items()):
            print(f"{env_key}={env_value}")
        return 0

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
        create_worktree(root, branch=branch, worktree=worktree, target_branch=config.target_branch)
        manifest.features[key] = FeatureRecord(
            name=name,
            slug=slug,
            branch=branch,
            worktree=str(worktree.relative_to(root)),
            target_branch=config.target_branch,
            status="active",
            created_at=_now(),
            config_fingerprint=config_fingerprint(config),
            env=env,
        )
        save_manifest(root, manifest)

    try:
        run_commands(config.setup, cwd=worktree, env=env)
    except NewFeatureError as setup_error:
        try:
            _teardown(root, slug, force=True)
        except NewFeatureError as teardown_error:
            raise NewFeatureError(
                f"setup failed ({setup_error}); forced teardown failed ({teardown_error})"
            ) from setup_error
        raise
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
    _warn_if_config_changed(config, record)
    worktree = root / record.worktree
    run_commands(config.pre_merge, cwd=worktree, env=record.env)
    if not worktree_is_clean(worktree):
        raise NewFeatureError("feature worktree has uncommitted changes; commit them before merging")
    if not worktree_is_clean(root):
        raise NewFeatureError("target checkout has uncommitted changes; commit or stash them before merging")
    try:
        begin_merge_without_commit(root, branch=record.branch, target_branch=record.target_branch)
        run_commands(config.post_merge, cwd=root, env=record.env)
        commit_merge(root, name=record.name)
    except NewFeatureError:
        abort_merge(root)
        raise
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
    _warn_if_config_changed(config, record)
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


def _list_features(root: Path) -> int:
    config = load_project_config(root)
    fingerprint = config_fingerprint(config)
    manifest = load_manifest(root)
    print("NAME\tSTATE\tBRANCH\tWORKTREE")
    for record in sorted(manifest.features.values(), key=lambda item: item.slug):
        state = inspect_feature(root, record, fingerprint)
        print(f"{record.slug}\t{state.describe()}\t{record.branch}\t{record.worktree}")
    return 0


def _doctor(root: Path, *, repair: bool) -> int:
    config = load_project_config(root)
    fingerprint = config_fingerprint(config)
    manifest = load_manifest(root)
    states = {key: inspect_feature(root, record, fingerprint) for key, record in manifest.features.items()}
    for key, state in sorted(states.items()):
        print(f"{manifest.features[key].slug}: {state.describe()}")

    repaired: set[str] = set()
    if repair:
        with manifest_lock(root):
            manifest = load_manifest(root)
            for key, record in list(manifest.features.items()):
                state = inspect_feature(root, record, fingerprint)
                if state.stale:
                    del manifest.features[key]
                    repaired.add(key)
                    print(f"repaired: removed stale manifest entry {record.slug}")
            if repaired:
                save_manifest(root, manifest)

    remaining_issues = [state for key, state in states.items() if key not in repaired and state.issues()]
    if remaining_issues:
        return 1
    if not states:
        print("doctor: ok")
    return 0


def _warn_if_config_changed(config: ProjectConfig, record: FeatureRecord) -> None:
    if record.config_fingerprint and record.config_fingerprint != config_fingerprint(config):
        print(
            f"new-feature: warning: project configuration changed since {record.slug} was created",
            file=sys.stderr,
        )


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
