from __future__ import annotations

import pytest

from new_feature.errors import NewFeatureError
from new_feature.hook_install import ensure_runner


def executable(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def test_missing_runner_is_installed_before_registration(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    log = tmp_path / "calls"
    monkeypatch.setenv("CALL_LOG", str(log))
    monkeypatch.setenv("RUNNER_BIN", str(tmp_path / "i-insist"))
    executable(
        tmp_path / "uv",
        """printf '%s\\n' "$*" >> "$CALL_LOG"
printf '#!/bin/sh\\nprintf "ensure\\\\n" >> "$CALL_LOG"\\n' > "$RUNNER_BIN"
/bin/chmod +x "$RUNNER_BIN"
""",
    )
    ensure_runner()
    assert log.read_text().splitlines() == [
        "tool install i-insist",
        "ensure",
    ]


def test_existing_runner_is_checked_without_reinstall(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    executable(tmp_path / "i-insist", "exit 0\n")
    ensure_runner()


def test_disabled_runner_aborts_migration(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    executable(tmp_path / "i-insist", "exit 2\n")
    with pytest.raises(NewFeatureError, match="enable its hooks"):
        ensure_runner()
