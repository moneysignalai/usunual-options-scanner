from __future__ import annotations

import time

from .alerts import build_alert_sinks
from .config import load_settings
from .logging_setup import get_logger, setup_logging
from .massive_client import MassiveAPIError, MassiveClient
from .strategy import find_unusual_activity
from .telegram_client import TelegramClient


def main() -> None:
    settings = load_settings()
    setup_logging(settings)
    logger = get_logger("worker")

    if not settings.massive_api_key:
        logger.error("Missing MASSIVE_API_KEY; exiting")
        return

    client = MassiveClient(settings.massive_api_key, settings.massive_base_url, logger=logger)
    telegram_client = None
    if settings.enable_telegram and settings.telegram_bot_token and settings.telegram_chat_id:
        telegram_client = TelegramClient(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            logger=logger,
        )
    elif settings.enable_telegram:
        logger.error("Telegram enabled but missing token or chat id")

    sinks = list(build_alert_sinks(logger, settings.enable_telegram, telegram_client))

    logger.info(
        "Worker starting | tickers=%s | interval=%s",
        ",".join(settings.ticker_universe),
        settings.scan_interval_seconds,
    )

    try:
        while True:
            cycle_count = 0
            alert_count = 0
            cycle_start = time.time()

            for ticker in settings.ticker_universe:
                cycle_count += 1
                try:
                    chain = client.get_option_chain_snapshot(ticker)
                    candidates = find_unusual_activity(chain, settings)
                    for candidate in candidates:
                        for sink in sinks:
                            sink.send(candidate)
                        alert_count += 1
                except MassiveAPIError:
                    logger.error("Skipping ticker due to Massive API error | ticker=%s", ticker)
                except Exception:
                    logger.exception("Unhandled error processing ticker | ticker=%s", ticker)

            duration = time.time() - cycle_start
            logger.info(
                "Scan cycle complete | tickers=%s | alerts=%s | duration=%.2fs",
                cycle_count,
                alert_count,
                duration,
            )
            time.sleep(settings.scan_interval_seconds)
    finally:
        client.close()
        if telegram_client:
            telegram_client.close()


if __name__ == "__main__":
    main()
