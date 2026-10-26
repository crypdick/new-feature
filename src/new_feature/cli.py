"""Run feature lifecycle commands from parsed command-line input."""

from __future__ import annotations

import argparse  # noqa: TC003 - package-wide beartype needs annotation types at runtime
import sys
from contextlib import nullcontext
from pathlib import Path

from new_feature import agent as agent_module
from new_feature.changes import inspect_changes
from new_feature.cli_parser import parse_args, wants_json
from new_feature.commands import run_commands
from new_feature.config import ProjectConfig, load_project_config
from new_feature.control_checkout import control_root
from new_feature.creation import CreationOptions, create_feature
from new_feature.errors import NewFeatureError
from new_feature.execution import execute_feature
from new_feature.feature_state import (
    require_setup_complete,
)
from new_feature.git import (
    branch_paths,
    checkout_target,
    commit_merge,
    ensure_merge_is_clean,
    is_branch_merged,
    merge_feature_branch,
    merge_in_progress,
    push_target,
    repo_root,
    worktree_is_clean,
)
from new_feature.gitignore import ensure_generated_paths_ignored
from new_feature.hook_install import install_rules
from new_feature.inspection import doctor, list_features, warn_if_config_changed, write_json
from new_feature.lifecycle import merge_failure_log
from new_feature.manifest import (
    FeatureRecord,
    feature_operation_lock,
    load_manifest,
    manifest_lock,
    record_feature_status,
    target_merge_lock,
)
from new_feature.merge_transaction import MergeTransaction
from new_feature.navigation import print_feature_completions, print_feature_path, print_shell_completion
from new_feature.prune import prune_features
from new_feature.rule_checker import main as check_rule
from new_feature.slug import feature_key, slugify
from new_feature.teardown import teardown
from new_feature.untracked import copy_local_files, local_paths, validate_local_paths
from new_feature.worktree_guidance import build_teardown_reminder


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface and return its process exit status."""
    raw_argv = sys.argv[1:] if argv is None else argv
    if len(raw_argv) == 2 and raw_argv[0] == "check-rule":
        return check_rule(raw_argv[1])
    json_requested = wants_json(raw_argv)
    try:
        args = parse_args(raw_argv)
    except SystemExit as exc:
        if not json_requested or exc.code == 0:
            raise
        write_json({
            "error": {"code": "invalid-arguments", "message": "invalid command arguments; see stderr"}
        })
        return 2
    try:
        return _run(args)
    except NewFeatureError as exc:
        if getattr(args, "json_output", False):
            write_json({"error": {"code": "command-failed", "message": str(exc)}})
        print(f"new-feature: {exc}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    if args.command == "completion" and args.shell:
        return print_shell_completion(args.shell)
    if args.command == "install-rules":
        return _install_rules(args)
    return _dispatch(args, control_root(Path.cwd()))


def _install_rules(args: argparse.Namespace) -> int:
    base = Path.home() if args.global_scope else repo_root(Path.cwd())
    path = install_rules(base)
    print(f"Installed i-insist rules in {path}")
    print("i-insist hooks are enabled. Restart the harness to load changes.")
    return 0


def _dispatch(args: argparse.Namespace, root: Path) -> int:
    if args.command == "setup":
        return _setup(root, agent_options=agent_module.AgentLaunchOptions(args.agent, args.prompt))
    if args.command == "create":
        return create_feature(
            root,
            args.name,
            CreationOptions(
                no_agent=args.no_agent,
                dry_run=args.dry_run,
                json_output=args.json_output,
                agent_options=agent_module.AgentLaunchOptions(args.agent, args.prompt),
                from_ref=args.from_ref,
                bootstrap=args.bootstrap,
            ),
        )
    if args.command in {"merge", "teardown"}:
        preview = args.command == "teardown" and args.dry_run
        with nullcontext() if preview else feature_operation_lock(root, slugify(args.name)):
            return (
                _merge(
                    root, args.name, git_args=tuple(args.git_args), include_untracked=args.include_untracked
                )
                if args.command == "merge"
                else teardown(root, args.name, force=args.force, dry_run=args.dry_run)
            )
    if args.command == "exec":
        return execute_feature(root, args.name, args.argv)
    return _dispatch_inspection(args, root)


def _dispatch_inspection(args: argparse.Namespace, root: Path) -> int:
    if args.command == "path":
        return print_feature_path(root, args.name)
    if args.command == "completion":
        return print_feature_completions(root)
    if args.command == "prune":
        return prune_features(root, dry_run=args.dry_run, json_output=args.json_output)
    if args.command == "changes":
        return inspect_changes(
            root, args.name, json_output=args.json_output, expected_generation=args.expected_generation
        )
    if args.command == "list":
        return list_features(root, json_output=args.json_output)
    if args.command == "doctor":
        return doctor(root, repair=args.repair, json_output=args.json_output)
    raise NewFeatureError(f"unknown command: {args.command}")


def _setup(root: Path, *, agent_options: agent_module.AgentLaunchOptions) -> int:
    config = load_project_config(root)
    ensure_generated_paths_ignored(root)
    agent_command = agent_module.resolve_agent(config, agent_options.agent_override)
    if agent_command is None:
        raise agent_module.agent_required_error(prompt_requested=agent_options.prompt_override is not None)
    prompt = agent_module.resolve_prompt(
        agent_module.build_setup_prompt(), config.setup_prompt, agent_options.prompt_override
    )
    return agent_module.launch_interactive_agent(agent_command, root, {}, prompt)


def _commit_feature_merge(
    root: Path,
    config: ProjectConfig,
    record: FeatureRecord,
    *,
    git_args: tuple[str, ...],
    transaction: MergeTransaction,
) -> FeatureRecord:
    if not is_branch_merged(root, branch=record.branch, target_branch=record.target_branch):
        merge_feature_branch(
            root,
            branch=record.branch,
            target_branch=record.target_branch,
            git_args=git_args,
        )
        # NOTE: README.md documents that custom Git arguments may commit before post-merge checks.
        pending_commit = merge_in_progress(root) or not worktree_is_clean(root)
        if not pending_commit and not is_branch_merged(
            root, branch=record.branch, target_branch=record.target_branch
        ):
            raise NewFeatureError("git merge did not integrate the feature branch")
        transaction.prepared()
        run_commands(
            config.post_merge,
            cwd=root,
            env=record.env,
            failure_log=merge_failure_log(root, record.slug, phase="post-merge"),
        )
        if transaction.pending_commit():
            commit_merge(root, name=record.name, git_args=git_args)
            transaction.committed()
    return record_feature_status(root, feature_key(record.slug), status="merged")


def _merge_target(
    root: Path,
    config: ProjectConfig,
    record: FeatureRecord,
    *,
    git_args: tuple[str, ...],
    local_files: tuple[Path, ...] | None = None,
) -> FeatureRecord:
    with target_merge_lock(root):
        if not worktree_is_clean(root):
            raise NewFeatureError(
                "target checkout has uncommitted changes; commit or stash them before merging"
            )
        tracked = (
            set()
            if local_files is None
            else branch_paths(root, record.target_branch) | branch_paths(root, record.branch)
        )
        if local_files is not None:
            validate_local_paths(root, root / record.worktree, local_files, tracked)
        # NOTE: docs/ARCHITECTURE.md requires target selection before rollback ownership.
        checkout_target(root, target_branch=record.target_branch)
        transaction = MergeTransaction(root, record.branch)
        try:
            record = _commit_feature_merge(root, config, record, git_args=git_args, transaction=transaction)
        except BaseException as merge_error:
            try:
                transaction.rollback()
            except NewFeatureError as rollback_error:
                raise NewFeatureError(
                    f"merge failed and the target checkout could not be restored: {rollback_error}"
                ) from merge_error
            raise
        if local_files is not None:
            copy_local_files(
                root, root / record.worktree, local_files, branch_paths(root, record.target_branch)
            )
        if config.push:
            push_target(root, target_branch=record.target_branch)
        return record


def _merge(root: Path, name: str, *, git_args: tuple[str, ...] = (), include_untracked: bool = False) -> int:
    config = load_project_config(root)
    key = feature_key(slugify(name))
    with manifest_lock(root):
        manifest = load_manifest(root)
        record = manifest.features.get(key)
        if record is None:
            raise NewFeatureError(f"unknown feature: {name}")
    require_setup_complete(record)
    warn_if_config_changed(config, record)
    worktree = root / record.worktree
    _require_feature_clean(worktree, include_untracked=include_untracked)
    with target_merge_lock(root):
        # NOTE: docs/ARCHITECTURE.md documents Git-derived integration; README.md covers push retries.
        already_merged = is_branch_merged(root, branch=record.branch, target_branch=record.target_branch)
        if already_merged:
            if include_untracked:
                if not worktree_is_clean(root, allow_untracked=True):
                    raise NewFeatureError(
                        "target checkout has uncommitted tracked changes; commit or stash them before merging"
                    )
                paths = local_paths(worktree, config.safe_to_delete)
                tracked = branch_paths(root, record.target_branch)
                validate_local_paths(root, worktree, paths, tracked)
                checkout_target(root, target_branch=record.target_branch)
                copy_local_files(root, worktree, paths, tracked)
            if record.status != "merged":
                record_feature_status(root, key, status="merged")
            if config.push:
                push_target(root, target_branch=record.target_branch)
    if already_merged:
        return _finish_merge(root, config, record)
    if not git_args:
        ensure_merge_is_clean(root, branch=record.branch, target_branch=record.target_branch)
    if config.pre_merge:
        print("new-feature: running pre-merge checks", file=sys.stderr, flush=True)
    # NOTE: README.md documents retained merge-check diagnostics.
    run_commands(
        config.pre_merge,
        cwd=worktree,
        env=record.env,
        failure_log=merge_failure_log(root, record.slug, phase="pre-merge"),
    )
    _require_feature_clean(worktree, include_untracked=include_untracked)
    local_files = local_paths(worktree, config.safe_to_delete) if include_untracked else None
    record = _merge_target(root, config, record, git_args=git_args, local_files=local_files)
    return _finish_merge(root, config, record)


def _finish_merge(root: Path, config: ProjectConfig, record: FeatureRecord) -> int:
    # NOTE: README.md documents optional teardown after merge, local file transfer, and push.
    if not config.auto_teardown:
        print(build_teardown_reminder(record.slug))
        return 0
    print("Feature merged. Running automatic teardown.", flush=True)
    try:
        return teardown(root, record.slug, force=False)
    except NewFeatureError as exc:
        raise NewFeatureError(f"merge succeeded but auto-teardown failed: {exc}") from exc


def _require_feature_clean(worktree: Path, *, include_untracked: bool) -> None:
    clean = (
        worktree_is_clean(worktree, allow_untracked=True)
        if include_untracked
        else worktree_is_clean(worktree)
    )
    if not clean:
        raise NewFeatureError("feature worktree has uncommitted changes; commit them before merging")
