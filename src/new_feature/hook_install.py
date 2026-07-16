"""Install repository-local agent worktree guards for Codex and Claude Code."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 - package-wide beartype needs annotation types at runtime
from typing import cast

from new_feature.atomic_file import atomic_text_write
from new_feature.errors import NewFeatureError

type JsonObject = dict[str, object]

_CODEX_MARKERS = (
    "new-feature codex-hook",
    "-m new_feature codex-hook",
    "require-worktree-edit.py",
)
_CLAUDE_MARKERS = (
    "new-feature claude-hook",
    "-m new_feature claude-hook",
)


def install_codex_hook(repo_root: Path) -> Path:
    """Install or update the Codex target-branch guard and return its configuration path."""
    return _install_guard(
        repo_root / ".codex" / "hooks.json",
        _hook_group(
            matcher="Bash|Edit|Write|apply_patch",
            command="new-feature codex-hook",
            status_message="Checking new-feature repository guard",
        ),
        markers=_CODEX_MARKERS,
    )


def install_claude_hook(repo_root: Path) -> Path:
    """Install or update the Claude Code target-branch guard and return its settings path."""
    return _install_guard(
        repo_root / ".claude" / "settings.json",
        _hook_group(
            matcher="Bash|Edit|Write|MultiEdit|NotebookEdit",
            command="new-feature claude-hook",
        ),
        markers=_CLAUDE_MARKERS,
    )


def _install_guard(hooks_path: Path, hook: JsonObject, *, markers: tuple[str, ...]) -> Path:
    document = _load_hooks_document(hooks_path)
    pre_tool_use = _pre_tool_use_groups(document)
    _install_dedicated_group(pre_tool_use, hook, markers=markers)
    _atomic_json_write(hooks_path, document)
    return hooks_path


def _load_hooks_document(path: Path) -> JsonObject:
    if not path.exists():
        return {"hooks": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise NewFeatureError(f"cannot read hooks file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise NewFeatureError(f"hooks file must contain a JSON object: {path}")
    return cast("JsonObject", value)


def _pre_tool_use_groups(document: JsonObject) -> list[object]:
    hooks = document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise NewFeatureError("hooks file field 'hooks' must be a JSON object")
    groups = hooks.setdefault("PreToolUse", [])
    if not isinstance(groups, list):
        raise NewFeatureError("hooks file field 'hooks.PreToolUse' must be a JSON array")
    return groups


def _hook_group(*, matcher: str, command: str, status_message: str | None = None) -> JsonObject:
    handler: JsonObject = {"type": "command", "command": command, "timeout": 10}
    if status_message is not None:
        handler["statusMessage"] = status_message
    return {"matcher": matcher, "hooks": [handler]}


def _install_dedicated_group(groups: list[object], hook: JsonObject, *, markers: tuple[str, ...]) -> None:
    updated: list[object] = []
    insertion_index: int | None = None
    for group in groups:
        if not isinstance(group, dict):
            updated.append(group)
            continue
        handlers = group.get("hooks", [])
        if not isinstance(handlers, list):
            updated.append(group)
            continue
        retained = [handler for handler in handlers if not _is_guard_handler(handler, markers)]
        if len(retained) == len(handlers):
            updated.append(group)
            continue
        if insertion_index is None:
            insertion_index = len(updated)
        if retained:
            updated.append({**group, "hooks": retained})

    updated.insert(len(updated) if insertion_index is None else insertion_index, hook)
    groups[:] = updated


def _is_guard_handler(handler: object, markers: tuple[str, ...]) -> bool:
    if not isinstance(handler, dict):
        return False
    command = handler.get("command")
    return isinstance(command, str) and any(marker in command for marker in markers)


def _atomic_json_write(path: Path, document: JsonObject) -> None:
    atomic_text_write(path, f"{json.dumps(document, indent=2)}\n", default_mode=0o600)
