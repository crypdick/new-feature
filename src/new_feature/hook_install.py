"""Install provider-owned i-insist rule registrations.

Guards are written under a caller-supplied base directory, so the same
installers serve repository-local installs (base is the repository root) and
user-level installs (base is the home directory).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from new_feature.atomic_file import atomic_text_write
from new_feature.errors import NewFeatureError


def install_rules(base: Path) -> Path:
    """Write the current provider-owned registration."""
    ensure_runner()
    path = base / ".i-insist" / "new-feature.toml"
    source = Path(__file__).with_name("rules.toml").read_text(encoding="utf-8")
    # NOTE: docs/ARCHITECTURE.md describes replacement of provider-owned registrations.
    atomic_text_write(path.resolve(), source, default_mode=0o600)
    return path


def ensure_runner() -> None:
    """Ensure the runner supports the checker protocol, then verify registration."""
    # NOTE: docs/ARCHITECTURE.md documents PyPI bootstrap and hook enablement.
    try:
        result = (
            subprocess.run(["i-insist", "--version"], capture_output=True, text=True, check=False)
            if shutil.which("i-insist")
            else None
        )
        current = (
            re.fullmatch(r"i-insist (\d+)\.(\d+)\.(\d+)", result.stdout.strip())
            if result is not None and result.returncode == 0
            else None
        )
        if current is None or tuple(map(int, current.groups())) < (0, 4, 0):
            subprocess.run(["uv", "tool", "install", "--upgrade", "i-insist>=0.4.0"], check=True)
        subprocess.run(["i-insist", "ensure"], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise NewFeatureError(
            "i-insist setup failed; install or upgrade i-insist, enable its hooks, then retry"
        ) from exc
