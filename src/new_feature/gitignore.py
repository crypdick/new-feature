from __future__ import annotations

from pathlib import Path

GENERATED_PATTERNS = [".new-feature/", ".worktrees/"]


def ensure_generated_paths_ignored(repo_root: Path) -> None:
    gitignore = repo_root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    changed = False
    for pattern in GENERATED_PATTERNS:
        if pattern not in existing:
            existing.append(pattern)
            changed = True
    if changed or not gitignore.exists():
        gitignore.write_text("\n".join(existing) + "\n", encoding="utf-8")
