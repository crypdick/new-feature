"""Run feature lifecycle commands from parsed command-line input."""

from __future__ import annotations

import argparse  # noqa: TC003 - package-wide beartype needs annotation types at runtime
import sys
from contextlib import nullcontext
from pathlib import Path

from new_feature import agent as agent_module
from new_feature.allocator import allocate_env
from new_feature.cli_parser import parse_args
from new_feature.commands import run_commands
from new_feature.config import ProjectConfig, config_fingerprint, load_project_config
from new_feature.control_checkout import control_root
from new_feature.errors import NewFeatureError
from new_feature.execution import execute_feature
from new_feature.feature_state import (
    require_setup_complete,
    reusable_feature_worktree,
)
from new_feature.git import (
    branch_paths,
    checkout_target,
    commit_merge,
    create_worktree,
    ensure_merge_is_clean,
    is_branch_merged,
    merge_feature_branch,
    merge_in_progress,
    pull_target,
    push_target,
    repo_root,
    resolve_revision,
    rollback_merge,
    worktree_is_clean,
)
from new_feature.gitignore import ensure_generated_paths_ignored
from new_feature.hook_install import install_rules
from new_feature.inspection import doctor, list_features, warn_if_config_changed, write_json
from new_feature.lifecycle import merge_failure_log, now
from new_feature.manifest import (
    FeatureRecord,
    FeatureStatus,
    feature_operation_lock,
    load_manifest,
    manifest_lock,
    save_manifest,
    target_merge_lock,
)
from new_feature.rule_checker import main as check_rule
from new_feature.slug import feature_key, slugify
from new_feature.teardown import teardown
from new_feature.untracked import copy_local_files, local_paths, validate_local_paths
from new_feature.worktree_guidance import build_teardown_reminder, build_worktree_ready_message


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface and return its process exit status."""
    raw_argv = sys.argv[1:] if argv is None else argv
    if len(raw_argv) == 2 and raw_argv[0] == "check-rule":
        return check_rule(raw_argv[1])
    json_requested = "--json" in raw_argv and raw_argv[0] in {"list", "status", "doctor"}
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
        return _create(
            root,
            args.name,
            no_agent=args.no_agent,
            dry_run=args.dry_run,
            agent_options=agent_module.AgentLaunchOptions(args.agent, args.prompt),
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


def _create(
    root: Path,
    name: str,
    *,
    no_agent: bool,
    dry_run: bool,
    agent_options: agent_module.AgentLaunchOptions,
) -> int:
    config = load_project_config(root)
    agent_command = _resolve_create_agent(config, no_agent=no_agent, agent_options=agent_options)
    slug = slugify(name)
    key = feature_key(slug)
    branch = slug
    worktree = root / ".worktrees" / slug

    if dry_run:
        manifest = load_manifest(root)
        record = manifest.features.get(key)
        if record is None:
            env = allocate_env(
                config=config,
                manifest=manifest,
                name=name,
                slug=slug,
                branch=branch,
                worktree=worktree,
                repo_root=root,
            )
        else:
            reusable_feature_worktree(root, record)
            env = record.env
        for env_key, env_value in sorted(env.items()):
            print(f"{env_key}={env_value}")
        return 0

    ensure_generated_paths_ignored(root)
    with feature_operation_lock(root, slug):
        config = _pull_config_before_create(root, key=key, config=config)
        agent_command = _resolve_create_agent(config, no_agent=no_agent, agent_options=agent_options)

        created = False
        with manifest_lock(root):
            manifest = load_manifest(root)
            record = manifest.features.get(key)
            if record is None:
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
                record = FeatureRecord(
                    name=name,
                    slug=slug,
                    branch=branch,
                    worktree=str(worktree.relative_to(root)),
                    target_branch=config.target_branch,
                    # NOTE: docs/ARCHITECTURE.md documents setup readiness and operation locks.
                    status="initializing",
                    created_at=now(),
                    config_fingerprint=config_fingerprint(config),
                    env=env,
                )
                manifest.features[key] = record
                save_manifest(root, manifest)
                created = True
            else:
                worktree = reusable_feature_worktree(root, record)
                env = record.env

        if created:
            try:
                run_commands(config.setup, cwd=worktree, env=env)
                record = _record_status(root, key, status="active")
            except BaseException as setup_error:
                try:
                    teardown(root, slug, force=True)
                except BaseException as teardown_error:
                    raise NewFeatureError(
                        f"setup failed ({setup_error}); forced teardown failed ({teardown_error})"
                    ) from teardown_error
                raise
        else:
            warn_if_config_changed(config, record)
    if agent_command is None:
        print(build_worktree_ready_message(worktree))
        return 0
    prompt = agent_module.resolve_prompt(
        agent_module.build_initial_prompt(record.slug), config.create_prompt, agent_options.prompt_override
    )
    return agent_module.launch_interactive_agent(agent_command, worktree, env, prompt)


def _resolve_create_agent(
    config: ProjectConfig,
    *,
    no_agent: bool,
    agent_options: agent_module.AgentLaunchOptions,
) -> tuple[str, ...] | None:
    agent_command = None if no_agent else agent_module.resolve_agent(config, agent_options.agent_override)
    if agent_command is None and agent_options.prompt_override is not None:
        raise agent_module.agent_required_error(prompt_requested=True)
    return agent_command


def _pull_config_before_create(root: Path, *, key: str, config: ProjectConfig) -> ProjectConfig:
    manifest = load_manifest(root)
    if not config.pull_before_create or manifest.features.get(key) is not None:
        return config
    with target_merge_lock(root):
        pull_target(root, target_branch=config.target_branch)
    return load_project_config(root)


def _record_status(root: Path, key: str, *, status: FeatureStatus) -> FeatureRecord:
    with manifest_lock(root):
        manifest = load_manifest(root)
        record = manifest.features.get(key)
        if record is None:
            raise NewFeatureError(f"unknown feature during status update: {key}")
        record.status = status
        if status == "merged":
            record.merged_at = now()
        save_manifest(root, manifest)
        return record


def _commit_feature_merge(
    root: Path,
    config: ProjectConfig,
    key: str,
    record: FeatureRecord,
    *,
    git_args: tuple[str, ...],
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
        run_commands(
            config.post_merge,
            cwd=root,
            env=record.env,
            failure_log=merge_failure_log(root, record.slug, phase="post-merge"),
        )
        if pending_commit:
            commit_merge(root, name=record.name, git_args=git_args)
    return _record_status(root, key, status="merged")


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
        target_revision = resolve_revision(root, "HEAD")
        try:
            record = _commit_feature_merge(root, config, feature_key(record.slug), record, git_args=git_args)
        except BaseException as merge_error:
            try:
                rollback_merge(root, revision=target_revision)
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
        if is_branch_merged(root, branch=record.branch, target_branch=record.target_branch):
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
                _record_status(root, key, status="merged")
            if config.push:
                push_target(root, target_branch=record.target_branch)
            print(build_teardown_reminder(record.slug))
            return 0
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
    print(build_teardown_reminder(record.slug))
    return 0


def _require_feature_clean(worktree: Path, *, include_untracked: bool) -> None:
    clean = (
        worktree_is_clean(worktree, allow_untracked=True)
        if include_untracked
        else worktree_is_clean(worktree)
    )
    if not clean:
        raise NewFeatureError("feature worktree has uncommitted changes; commit them before merging")
