"""Run feature lifecycle commands from parsed command-line input."""

from __future__ import annotations

import argparse  # noqa: TC003 - package-wide beartype needs annotation types at runtime
import os
import sys
from pathlib import Path
from typing import cast

from new_feature import agent as agent_module
from new_feature.agent_hook import TextStream, run_agent_hook
from new_feature.allocator import allocate_env
from new_feature.cli_parser import parse_args
from new_feature.commands import run_commands
from new_feature.config import ProjectConfig, config_fingerprint, load_project_config
from new_feature.errors import NewFeatureError
from new_feature.feature_state import IntegrationState, inspect_feature, inspect_integration
from new_feature.git import (
    begin_merge_without_commit,
    branch_exists,
    commit_merge,
    create_worktree,
    ensure_merge_is_clean,
    pull_target,
    push_target,
    remove_worktree_and_branch,
    repo_root,
    resolve_revision,
    rollback_merge,
    worktree_branch,
    worktree_is_clean,
)
from new_feature.gitignore import ensure_generated_paths_ignored
from new_feature.hook_install import install_claude_hook, install_codex_hook
from new_feature.lifecycle import now
from new_feature.manifest import FeatureRecord, load_manifest, manifest_lock, save_manifest, target_merge_lock
from new_feature.recovery import repair_feature
from new_feature.slug import feature_key, slugify
from new_feature.worktree_guidance import build_teardown_reminder, build_worktree_ready_message

_INTERNAL_HOOK_COMMANDS = frozenset({"codex-hook", "claude-hook"})
_INSTALL_HOOK_COMMANDS = frozenset({"install-codex-hook", "install-claude-hook"})


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface and return its process exit status."""
    raw_argv = sys.argv[1:] if argv is None else argv
    if len(raw_argv) == 1 and raw_argv[0] in _INTERNAL_HOOK_COMMANDS:
        return run_agent_hook(cast("TextStream", sys.stdin), cast("TextStream", sys.stdout), cwd=Path.cwd())
    args = parse_args(raw_argv)
    try:
        return _run(args)
    except NewFeatureError as exc:
        print(f"new-feature: {exc}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    if args.command in _INSTALL_HOOK_COMMANDS:
        return _install_hook(args)
    return _dispatch(args, repo_root(Path.cwd()))


def _install_hook(args: argparse.Namespace) -> int:
    base = Path.home() if args.global_scope else repo_root(Path.cwd())
    if args.command == "install-codex-hook":
        path = install_codex_hook(base)
        print(f"Installed Codex target-branch guard in {path}")
        print("Restart Codex, then review and trust the hook with /hooks.")
    else:
        path = install_claude_hook(base, local=args.local_scope)
        print(f"Installed Claude Code target-branch guard in {path}")
        print("Restart Claude Code so the session reloads its hooks, then review them with /hooks.")
    if args.global_scope:
        print("The guard now applies to every repository on this machine.")
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
    if args.command == "merge":
        return _merge(root, args.name)
    if args.command == "teardown":
        return _teardown(root, args.name, force=args.force)
    if args.command == "list":
        return _list_features(root)
    if args.command == "doctor":
        return _doctor(root, repair=args.repair)
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
            _reusable_feature_worktree(root, record)
            env = record.env
        for env_key, env_value in sorted(env.items()):
            print(f"{env_key}={env_value}")
        return 0

    config = _pull_config_before_create(root, key=key, config=config)
    agent_command = _resolve_create_agent(config, no_agent=no_agent, agent_options=agent_options)

    ensure_generated_paths_ignored(root)
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
                status="active",
                created_at=now(),
                config_fingerprint=config_fingerprint(config),
                env=env,
            )
            manifest.features[key] = record
            save_manifest(root, manifest)
            created = True
        else:
            worktree = _reusable_feature_worktree(root, record)
            env = record.env

    if created:
        try:
            run_commands(config.setup, cwd=worktree, env=env)
        except BaseException as setup_error:
            try:
                _teardown(root, slug, force=True)
            except BaseException as teardown_error:
                raise NewFeatureError(
                    f"setup failed ({setup_error}); forced teardown failed ({teardown_error})"
                ) from teardown_error
            raise
    else:
        _warn_if_config_changed(config, record)
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
    pull_target(root, target_branch=config.target_branch)
    return load_project_config(root)


def _reusable_feature_worktree(root: Path, record: FeatureRecord) -> Path:
    """Return an existing active feature's worktree or explain why it cannot be reopened."""
    if record.status != "active":
        raise NewFeatureError(
            f"feature has already been merged: {record.slug}; "
            f"run `new-feature teardown {record.slug}` before creating it again"
        )

    worktree = root / record.worktree
    issues: list[str] = []
    if not worktree.is_dir():
        issues.append("missing worktree")
    if not branch_exists(root, record.branch):
        issues.append("missing branch")
    if issues:
        detail = " and ".join(issues)
        raise NewFeatureError(
            f"feature cannot be reopened: {record.slug} ({detail}); "
            "run `new-feature doctor --repair` before retrying"
        )
    return worktree


def _merge_failure_log(root: Path, record: FeatureRecord, *, phase: str) -> Path:
    """Return a unique retained-output path for one merge-check phase."""
    timestamp = now().replace(":", "-")
    return (
        root
        / ".new-feature"
        / "diagnostics"
        / "merge-failures"
        / record.slug
        / f"{timestamp}-{os.getpid()}-{phase}.log"
    )


def _record_merged(root: Path, key: str, name: str) -> FeatureRecord:
    with manifest_lock(root):
        manifest = load_manifest(root)
        record = manifest.features.get(key)
        if record is None:
            raise NewFeatureError(f"unknown feature after merge: {name}")
        record.status = "merged"
        record.merged_at = now()
        save_manifest(root, manifest)
        return record


def _commit_feature_merge(
    root: Path, config: ProjectConfig, key: str, record: FeatureRecord
) -> FeatureRecord:
    begin_merge_without_commit(root, branch=record.branch, target_branch=record.target_branch)
    run_commands(
        config.post_merge,
        cwd=root,
        env=record.env,
        failure_log=_merge_failure_log(root, record, phase="post-merge"),
    )
    commit_merge(root, name=record.name)
    return _record_merged(root, key, record.name)


def _merge_target(root: Path, config: ProjectConfig, key: str, record: FeatureRecord) -> FeatureRecord:
    with target_merge_lock(root):
        if not worktree_is_clean(root):
            raise NewFeatureError(
                "target checkout has uncommitted changes; commit or stash them before merging"
            )
        target_revision = resolve_revision(root, record.target_branch)
        try:
            record = _commit_feature_merge(root, config, key, record)
        except BaseException as merge_error:
            try:
                rollback_merge(root, revision=target_revision)
            except NewFeatureError as rollback_error:
                raise NewFeatureError(
                    f"merge failed and the target checkout could not be restored: {rollback_error}"
                ) from merge_error
            raise
        if config.push:
            push_target(root, target_branch=record.target_branch)
        return record


def _merge(root: Path, name: str) -> int:
    config = load_project_config(root)
    key = feature_key(slugify(name))
    with manifest_lock(root):
        manifest = load_manifest(root)
        record = manifest.features.get(key)
        if record is None:
            raise NewFeatureError(f"unknown feature: {name}")
    _warn_if_config_changed(config, record)
    if record.status == "merged":
        with target_merge_lock(root):
            if config.push:
                push_target(root, target_branch=record.target_branch)
        print(build_teardown_reminder(record.slug))
        return 0
    worktree = root / record.worktree
    if not worktree_is_clean(worktree):
        raise NewFeatureError("feature worktree has uncommitted changes; commit them before merging")
    ensure_merge_is_clean(root, branch=record.branch, target_branch=record.target_branch)
    if config.pre_merge:
        print("new-feature: running pre-merge checks", file=sys.stderr, flush=True)
    # NOTE: README.md documents retained merge-check diagnostics.
    run_commands(
        config.pre_merge,
        cwd=worktree,
        env=record.env,
        failure_log=_merge_failure_log(root, record, phase="pre-merge"),
    )
    if not worktree_is_clean(worktree):
        raise NewFeatureError("feature worktree has uncommitted changes; commit them before merging")
    record = _merge_target(root, config, key, record)
    print(build_teardown_reminder(record.slug))
    return 0


def _teardown(root: Path, name: str, *, force: bool) -> int:
    config = load_project_config(root)
    slug = slugify(name)
    key = feature_key(slug)
    with manifest_lock(root):
        manifest = load_manifest(root)
        record = manifest.features.get(key)
    if record is None:
        # NOTE: README.md's Lifecycle section documents this constrained unmanaged path.
        worktree = root / ".worktrees" / slug
        if not worktree.is_dir():
            raise NewFeatureError(f"unknown feature: {name}")
        branch = worktree_branch(worktree)
        target_branch = config.target_branch
    else:
        _warn_if_config_changed(config, record)
        worktree = root / record.worktree
        branch = record.branch
        target_branch = record.target_branch
    if not worktree.is_dir():
        raise NewFeatureError(
            "feature worktree is missing; run `new-feature doctor --repair` to recover an integrated branch"
        )
    force_branch = False
    if not force:
        if not worktree_is_clean(worktree):
            raise NewFeatureError("feature worktree has uncommitted changes; pass --force to abandon them")
        if branch is None:
            raise NewFeatureError("unmanaged worktree is detached; pass --force to abandon it")
        integration = inspect_integration(root, branch=branch, target_branch=target_branch)
        if integration is IntegrationState.UNMERGED:
            raise NewFeatureError("feature branch has unmerged commits; pass --force to abandon them")
        force_branch = integration is IntegrationState.PATCH_EQUIVALENT
    if record is None:
        print("new-feature: unmanaged worktree; skipping configured teardown commands", file=sys.stderr)
    else:
        run_commands(config.teardown, cwd=worktree, env=record.env)
    remove_worktree_and_branch(
        root,
        branch=branch,
        worktree=worktree,
        force=force,
        force_branch=force_branch,
    )
    if record is not None:
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
                message = repair_feature(root, record, state)
                if message:
                    del manifest.features[key]
                    repaired.add(key)
                    print(f"repaired: {message}")
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
