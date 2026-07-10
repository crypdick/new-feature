from __future__ import annotations

import logging

from new_feature.app import main, startup_message


def test_main_logs_startup_message(caplog) -> None:
    with caplog.at_level(logging.INFO):
        main()

    assert "new feature started" in caplog.messages


def test_startup_message() -> None:
    assert startup_message() == "new feature started"
