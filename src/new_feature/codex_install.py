"""Install the repository-local Codex worktree guard."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 - package-wide beartype needs annotation types at runtime
from typing import cast

from new_feature.atomic_file import atomic_text_write
from new_feature.errors import NewFeatureError

type JsonObject = dict[str, object]

_HOOK_MARKERS = ("new-feature codex-hook", "-m new_feature codex-hook")
_LEGACY_HOOK_MARKER = "require-worktree-edit.py"


def install_codex_hook(repo_root: Path) -> Path:
    """Install or update the Codex guard and return its configuration path."""
    """Install or update the target-branch guard in this repository."""
    hooks_path = repo_root / ".codex" / "hooks.json"
    document = _load_hooks_document(hooks_path)
    pre_tool_use = _pre_tool_use_groups(document)
    hook = _hook_group()

    _install_dedicated_group(pre_tool_use, hook)

    _atomic_json_write(hooks_path, document)
    return hooks_path


def _load_hooks_document(path: Path) -> JsonObject:
    if not path.exists():
        return {"hooks": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise NewFeatureError(f"cannot read Codex hooks file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise NewFeatureError(f"Codex hooks file must contain a JSON object: {path}")
    return cast("JsonObject", value)


def _pre_tool_use_groups(document: JsonObject) -> list[object]:
    hooks = document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise NewFeatureError("Codex hooks file field 'hooks' must be a JSON object")
    groups = hooks.setdefault("PreToolUse", [])
    if not isinstance(groups, list):
        raise NewFeatureError("Codex hooks file field 'hooks.PreToolUse' must be a JSON array")
    return groups


def _hook_group() -> JsonObject:
    return {
        "matcher": "Bash|Edit|Write|apply_patch",
        "hooks": [
            {
                "type": "command",
                "command": "new-feature codex-hook",
                "timeout": 10,
                "statusMessage": "Checking new-feature repository guard",
            }
        ],
    }


def _install_dedicated_group(groups: list[object], hook: JsonObject) -> None:
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
        retained = [handler for handler in handlers if not _is_guard_handler(handler)]
        if len(retained) == len(handlers):
            updated.append(group)
            continue
        if insertion_index is None:
            insertion_index = len(updated)
        if retained:
            updated.append({**group, "hooks": retained})

    updated.insert(len(updated) if insertion_index is None else insertion_index, hook)
    groups[:] = updated


def _is_guard_handler(handler: object) -> bool:
    return isinstance(handler, dict) and _is_guard_command(handler.get("command"))


def _is_guard_command(command: object) -> bool:
    return isinstance(command, str) and (
        any(marker in command for marker in _HOOK_MARKERS) or _LEGACY_HOOK_MARKER in command
    )


def _atomic_json_write(path: Path, document: JsonObject) -> None:
    atomic_text_write(path, f"{json.dumps(document, indent=2)}\n", default_mode=0o600)
