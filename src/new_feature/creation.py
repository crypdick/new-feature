"""Create managed worktrees, inert branch imports, and their runtime environments."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 - runtime annotation checking
from uuid import uuid4

from new_feature import agent as agent_module
from new_feature.allocator import allocate_env
from new_feature.commands import run_commands
from new_feature.config import ProjectConfig, config_fingerprint, load_project_config
from new_feature.control_checkout import require_managed_worktree
from new_feature.errors import NewFeatureError
from new_feature.feature_state import require_setup_complete, reusable_feature_worktree
from new_feature.git import create_worktree, import_worktree, pull_target
from new_feature.gitignore import ensure_generated_paths_ignored
from new_feature.inspection import warn_if_config_changed, write_json
from new_feature.lifecycle import now
from new_feature.manifest import (
    FeatureRecord,
    feature_operation_lock,
    load_manifest,
    manifest_lock,
    record_feature_status,
    save_manifest,
    target_merge_lock,
)
from new_feature.output import command_output
from new_feature.slug import feature_key, slugify
from new_feature.teardown import teardown
from new_feature.worktree_guidance import build_worktree_ready_message


@dataclass(frozen=True)
class CreationOptions:
    """Hold explicit creation, import, and bootstrap choices."""

    no_agent: bool
    dry_run: bool
    agent_options: agent_module.AgentLaunchOptions
    json_output: bool = False
    from_ref: str | None = None
    bootstrap: bool = False


def create_feature(root: Path, name: str, options: CreationOptions) -> int:
    no_agent, dry_run = options.no_agent or options.from_ref is not None, options.dry_run
    agent_options, json_output = options.agent_options, options.json_output
    config = load_project_config(root)
    agent_command = _resolve_create_agent(config, no_agent=no_agent, agent_options=agent_options)
    slug = slugify(name)
    key = feature_key(slug)
    worktree = root / ".worktrees" / slug

    if dry_run:
        return _preview_creation(root, name, config)

    agent_exit_code: int | None = None
    agent_error: dict[str, object] | None = None
    with command_output(json_output=json_output):
        ensure_generated_paths_ignored(root)
        with feature_operation_lock(root, slug):
            if options.from_ref is None and not options.bootstrap:
                config = _pull_config_before_create(root, key=key, config=config)
            agent_command = _resolve_create_agent(config, no_agent=no_agent, agent_options=agent_options)

            record, created = _prepare_feature(root, name, config, options)
            worktree, env = root / record.worktree, record.env
            if (created and options.from_ref is None) or options.bootstrap:
                record = _bootstrap_feature(root, record, config, imported=options.bootstrap)
            else:
                warn_if_config_changed(config, record)
        if agent_command is None:
            if not json_output:
                sys.stdout.write(build_worktree_ready_message(worktree) + "\n")
        else:
            prompt = agent_module.resolve_prompt(
                agent_module.build_initial_prompt(record.slug),
                config.create_prompt,
                agent_options.prompt_override,
            )
            agent_exit_code, agent_error = _launch_created_agent(
                agent_command, worktree, env, prompt, json_output=json_output
            )
    if json_output:
        write_json({
            "command": "create",
            "ok": agent_error is None,
            "status": "created" if created else "reused",
            "feature": {
                "name": record.name,
                "slug": record.slug,
                "branch": record.branch,
                "target_branch": record.target_branch,
                "worktree": str(worktree.resolve()),
                "status": record.status,
            },
            "agent_exit_code": agent_exit_code,
            "agent_error": agent_error,
        })
    return agent_exit_code or 0


def _preview_creation(root: Path, name: str, config: ProjectConfig) -> int:
    slug = slugify(name)
    manifest = load_manifest(root)
    record = manifest.features.get(feature_key(slug))
    if record is None:
        env = allocate_env(
            config=config,
            manifest=manifest,
            name=name,
            slug=slug,
            branch=slug,
            worktree=root / ".worktrees" / slug,
            repo_root=root,
        )
    else:
        reusable_feature_worktree(root, record)
        env = record.env
    for env_key, env_value in sorted(env.items()):
        sys.stdout.write(f"{env_key}={env_value}\n")
    return 0


def _launch_created_agent(
    command: tuple[str, ...], worktree: Path, env: dict[str, str], prompt: str, *, json_output: bool
) -> tuple[int, dict[str, object] | None]:
    try:
        exit_code = agent_module.launch_interactive_agent(command, worktree, env, prompt)
    except NewFeatureError as exc:
        if not json_output:
            raise
        return 1, {"code": "agent-failed", "message": str(exc)}
    if exit_code != 0:
        return exit_code, {"code": "agent-failed", "message": f"agent exited with status {exit_code}"}
    return exit_code, None


def _resolve_create_agent(
    config: ProjectConfig,
    *,
    no_agent: bool,
    agent_options: agent_module.AgentLaunchOptions,
) -> tuple[str, ...] | None:
    # NOTE: README.md documents session detection and explicit --agent precedence.
    if agent_options.agent_override is None and (
        os.environ.get("CODEX_CI") == "1" or os.environ.get("CLAUDE_CODE_CHILD_SESSION") == "1"
    ):
        no_agent = True
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


def _prepare_feature(
    root: Path, name: str, config: ProjectConfig, options: CreationOptions
) -> tuple[FeatureRecord, bool]:
    slug = slugify(name)
    worktree = root / ".worktrees" / slug
    key = feature_key(slug)
    with manifest_lock(root):
        manifest = load_manifest(root)
        record = manifest.features.get(key)
        if record is not None:
            _reuse_feature(root, record, options)
            if options.bootstrap:
                save_manifest(root, manifest)
            return record, False
        if options.bootstrap:
            raise NewFeatureError("--bootstrap requires an existing inert feature")
        env = allocate_env(
            config=config,
            manifest=manifest,
            name=name,
            slug=slug,
            branch=slug,
            worktree=worktree,
            repo_root=root,
        )
        owns_branch = True
        if options.from_ref is not None:
            owns_branch = import_worktree(root, branch=slug, worktree=worktree, source=options.from_ref)
        else:
            create_worktree(root, branch=slug, worktree=worktree, target_branch=config.target_branch)
        # NOTE: README.md documents inert imports, branch ownership, and durable generation tokens.
        record = FeatureRecord(
            name=name,
            slug=slug,
            branch=slug,
            worktree=str(worktree.relative_to(root)),
            target_branch=config.target_branch,
            status="inert" if options.from_ref is not None else "initializing",
            owns_branch=owns_branch,
            generation=uuid4().hex,
            created_at=now(),
            config_fingerprint=config_fingerprint(config),
            env=env,
        )
        manifest.features[key] = record
        save_manifest(root, manifest)
        return record, True


def _reuse_feature(root: Path, record: FeatureRecord, options: CreationOptions) -> None:
    if options.from_ref is not None:
        raise NewFeatureError("feature already exists; omit --from to reuse it")
    if record.status == "inert":
        if not options.bootstrap:
            require_setup_complete(record)
        require_managed_worktree(root, root / record.worktree, record.branch)
        record.status = "initializing"
    else:
        if options.bootstrap:
            raise NewFeatureError("--bootstrap requires an inert feature")
        reusable_feature_worktree(root, record)


def _bootstrap_feature(
    root: Path, record: FeatureRecord, config: ProjectConfig, *, imported: bool
) -> FeatureRecord:
    try:
        run_commands(config.setup, cwd=root / record.worktree, env=record.env)
        return record_feature_status(root, feature_key(record.slug), status="active")
    except BaseException as setup_error:
        if imported:
            record_feature_status(root, feature_key(record.slug), status="inert")
            raise
        try:
            teardown(root, record.slug, force=True)
        except BaseException as teardown_error:
            raise NewFeatureError(
                f"setup failed ({setup_error}); forced teardown failed ({teardown_error})"
            ) from teardown_error
        raise
