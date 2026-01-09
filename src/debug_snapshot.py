from __future__ import annotations

import logging
import os
import sys

from .config import load_settings
from .massive_client import MassiveClient
from .strategy import find_unusual_activity
from .alerts import format_alert_message


logger = logging.getLogger("debug_snapshot")


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    handler.setFormatter(formatter)
    if not logger.handlers:
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def main() -> None:
    _configure_logging()
    settings = load_settings()
    settings.debug_mode = True
    symbol = os.getenv("DEBUG_TICKER", "SPY").upper()

    client = MassiveClient(settings=settings)
    try:
        snapshot = client.get_option_chain_snapshot(symbol)
        if not snapshot or not snapshot.results:
            logger.info("No snapshot data | ticker=%s", symbol)
            return

        contract_count = sum(len(result.contracts or []) for result in snapshot.results)
        logger.info("Snapshot loaded | ticker=%s | contract_count=%s", symbol, contract_count)

        candidates = []
        for result in snapshot.results:
            candidates.extend(find_unusual_activity(result, settings))

        logger.info("Candidates passing filters | ticker=%s | count=%d", symbol, len(candidates))
        for candidate in candidates[:3]:
            logger.info(
                "Example alert | ticker=%s | message=%s",
                symbol,
                format_alert_message(candidate).replace("\n", " | "),
            )
    finally:
        client.close()


if __name__ == "__main__":
    main()
