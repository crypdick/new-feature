from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import cast

from new_feature.errors import NewFeatureError

type JsonObject = dict[str, object]

_HOOK_MARKERS = ("new-feature codex-hook", "-m new_feature codex-hook")
_LEGACY_HOOK_MARKER = "require-worktree-edit.py"


def install_codex_hook(repo_root: Path) -> Path:
    """Install or update the target-branch guard in this repository."""
    hooks_path = repo_root / ".codex" / "hooks.json"
    document = _load_hooks_document(hooks_path)
    pre_tool_use = _pre_tool_use_groups(document)
    hook = _hook_group()

    replacement_index = _installed_group_index(pre_tool_use)
    if replacement_index is None:
        pre_tool_use.append(hook)
    else:
        pre_tool_use[replacement_index] = hook

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


def _installed_group_index(groups: list[object]) -> int | None:
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        handlers = group.get("hooks", [])
        if not isinstance(handlers, list):
            continue
        for handler in handlers:
            if isinstance(handler, dict) and _is_guard_command(handler.get("command")):
                return index
    return None


def _is_guard_command(command: object) -> bool:
    return isinstance(command, str) and (
        any(marker in command for marker in _HOOK_MARKERS) or _LEGACY_HOOK_MARKER in command
    )


def _atomic_json_write(path: Path, document: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        _write_json(descriptor, document)
        temporary_path.chmod(mode)
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _write_json(descriptor: int, document: JsonObject) -> None:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
