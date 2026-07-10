from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def startup_message() -> str:
    return "new feature started"


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info(startup_message())
