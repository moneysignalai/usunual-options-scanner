from __future__ import annotations

import time

from .alerts import build_alert_sinks
from .config import load_settings
from .logging_setup import get_logger, setup_logging
from .massive_client import MassiveAPIError, MassiveClient
from .strategy import find_unusual_activity
from .telegram_client import TelegramClient


def main() -> None:
    # Load config & logging _once_
    settings = load_settings()
    setup_logging(settings)
    logger = get_logger("worker")

    logger.info(
        "Worker starting | tickers=%s | interval=%ss",
        ",".join(settings.ticker_universe),
        settings.scan_interval_seconds,
    )

    client = MassiveClient(settings=settings)

    telegram_client = None
    if settings.enable_telegram:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            logger.error("ENABLE_TELEGRAM=true but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing")
        else:
            telegram_client = TelegramClient(
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
            )
            logger.info("Telegram alerts enabled")

    alert_sinks = build_alert_sinks(logger=logger, telegram_client=telegram_client)

    tickers = settings.ticker_universe
    cycle_count = 0

    try:
        while True:
            cycle_start = time.time()
            alert_count = 0
            cycle_count += 1

            for symbol in tickers:
                try:
                    snapshot = client.get_option_chain_snapshot(symbol)
                except MassiveAPIError as exc:
                    logger.error(
                        "Skipping ticker due to Massive API error | ticker=%s | error=%s",
                        symbol,
                        exc,
                    )
                    continue
                except Exception:
                    logger.exception("Unexpected error while fetching option chain | ticker=%s", symbol)
                    continue

                if snapshot is None:
                    continue

                try:
                    alerts = find_unusual_activity(symbol, snapshot, settings)
                except Exception:
                    logger.exception("Error in unusual-activity strategy | ticker=%s", symbol)
                    continue

                for alert in alerts:
                    alert_count += 1
                    for sink in alert_sinks:
                        try:
                            sink.send(alert)
                        except Exception:
                            logger.exception("Error sending alert via sink | symbol=%s", symbol)

            duration = time.time() - cycle_start
            logger.info(
                "Scan cycle complete | cycle=%s | tickers=%s | alerts=%s | duration=%.2fs",
                cycle_count,
                len(tickers),
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
