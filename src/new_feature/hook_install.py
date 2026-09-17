"""Install agent worktree guards for Codex and Claude Code.

Guards are written under a caller-supplied base directory, so the same
installers serve repository-local installs (base is the repository root) and
user-level installs (base is the home directory).
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import cast

import tomli_w

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


def install_rules(base: Path) -> Path:
    """Install provider-owned rules, preserving existing user configuration."""
    ensure_runner()
    path = base / ".i-insist" / "new-feature.toml"
    source = Path(__file__).with_name("rules.toml").read_text(encoding="utf-8")
    if not path.exists():
        atomic_text_write(path, source, default_mode=0o600)
    else:
        _append_missing_rules(path, source)
    for hooks_path, markers in (
        (base / ".codex" / "hooks.json", _CODEX_MARKERS),
        (base / ".claude" / "settings.json", _CLAUDE_MARKERS),
        (base / ".claude" / "settings.local.json", _CLAUDE_MARKERS),
    ):
        _remove_guard(hooks_path, markers=markers)
    return path


def _append_missing_rules(path: Path, source: str) -> None:
    # NOTE: docs/ARCHITECTURE.md promises to preserve custom rules and append missing defaults.
    try:
        original = path.read_text(encoding="utf-8")
        existing = {rule["id"] for rule in tomllib.loads(original).get("rules", [])}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise NewFeatureError(f"cannot read rules file {path}: {exc}") from exc
    missing = [rule for rule in tomllib.loads(source)["rules"] if rule["id"] not in existing]
    if missing:
        atomic_text_write(path, original + "\n" + tomli_w.dumps({"rules": missing}), default_mode=0o600)


def install_codex_hook(base: Path) -> Path:
    """Install i-insist rules and remove the dedicated native guard handlers."""
    return install_rules(base)


def install_claude_hook(base: Path, *, local: bool = False) -> Path:
    """Install shared .i-insist rules; reject the harness-specific local option."""
    if local:
        raise NewFeatureError(
            "--local is retired; use install-rules and ignore .i-insist/new-feature.toml if needed"
        )
    return install_rules(base)


def _remove_guard(hooks_path: Path, *, markers: tuple[str, ...]) -> None:
    if not hooks_path.exists():
        return
    hooks_path = hooks_path.resolve()
    document = _load_hooks_document(hooks_path)
    pre_tool_use = _pre_tool_use_groups(document)
    original = json.dumps(document)
    _remove_dedicated_group(pre_tool_use, markers=markers)
    if json.dumps(document) != original:
        _atomic_json_write(hooks_path, document)


def _load_hooks_document(path: Path) -> JsonObject:
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


def _remove_dedicated_group(groups: list[object], *, markers: tuple[str, ...]) -> None:
    updated: list[object] = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            updated.append(group)
            continue
        handlers = group["hooks"]
        retained = [handler for handler in handlers if not _is_guard_handler(handler, markers)]
        if len(retained) == len(handlers):
            updated.append(group)
        else:
            # Codex trust keys include group positions; retain empty groups.
            updated.append({**group, "hooks": retained})
    groups[:] = updated


def _is_guard_handler(handler: object, markers: tuple[str, ...]) -> bool:
    if not isinstance(handler, dict):
        return False
    command = handler.get("command")
    if not isinstance(command, str):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if len(words) == 2 and Path(words[0]).name == "new-feature":
        return f"new-feature {words[1]}" in markers
    if words and Path(words[0]).name.startswith("python"):
        return (len(words) == 4 and words[1] == "-m" and " ".join(words[1:]) in markers) or (
            len(words) == 2
            and Path(words[1]).name == "require-worktree-edit.py"
            and "require-worktree-edit.py" in markers
        )
    return False


def _atomic_json_write(path: Path, document: JsonObject) -> None:
    atomic_text_write(path, f"{json.dumps(document, indent=2)}\n", default_mode=0o600)


def ensure_runner() -> None:
    """Install the standalone runner if absent, then verify its registration."""
    try:
        if shutil.which("i-insist") is None:
            subprocess.run(
                ["uv", "tool", "install", "git+https://github.com/crypdick/i-insist@main"], check=True
            )
        subprocess.run(["i-insist", "ensure"], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise NewFeatureError(
            "i-insist setup failed; install or upgrade i-insist, enable its hooks, then retry"
        ) from exc
