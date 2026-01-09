from __future__ import annotations

import logging
import os
import sys

from .config import load_settings
from .massive_client import MassiveClient


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

        contracts = snapshot.results or []
        contract_count = len(contracts)
        logger.info(
            "Snapshot loaded | ticker=%s | contract_count=%s", symbol, contract_count
        )
        for contract in contracts[:5]:
            logger.info(
                "Contract sample | opt=%s | strike=%s | exp=%s | type=%s | volume=%s",
                contract.details.ticker,
                contract.details.strike_price,
                contract.details.expiration_date,
                contract.details.contract_type,
                contract.day.volume if contract.day else None,
            )
    finally:
        client.close()


if __name__ == "__main__":
    main()
