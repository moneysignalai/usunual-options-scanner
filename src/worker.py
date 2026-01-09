from __future__ import annotations

import logging
import time
from typing import List

from .alerts import Alert, AlertSink, build_alert_sinks
from .config import load_settings
from .massive_client import MassiveClient
from .strategy import (
    StrategyContext,
    find_unusual_activity,
)


def create_logger() -> logging.Logger:
    """
    Configure root logger for the worker.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger = logging.getLogger("worker")
    return logger


def process_ticker(
    ticker: str,
    massive_client: MassiveClient,
    strategy_ctx: StrategyContext,
    logger: logging.Logger,
) -> List[Alert]:
    """
    Fetches option snapshot data for a single ticker and runs strategy logic
    to find unusual options activity, returning a list of Alerts.
    """
    logger.info("Processing ticker | ticker=%s", ticker)

    # Pull a fresh snapshot from Massive
    snapshot = massive_client.fetch_option_chain_snapshot(ticker)
    strategy_ctx.last_snapshot = snapshot

    # Strategy: find unusual activity
    alerts = find_unusual_activity(snapshot, strategy_ctx)
    if alerts:
        logger.info(
            "Found %d alerts for ticker %s", len(alerts), ticker
        )
    else:
        logger.info("No alerts found for ticker %s", ticker)

    return alerts


def dispatch_alerts(
    alerts: List[Alert],
    sinks: List[AlertSink],
    logger: logging.Logger,
) -> None:
    """
    Sends each alert to all configured sinks (e.g., Telegram, console).
    """
    for alert in alerts:
        for sink in sinks:
            try:
                sink.send(alert)
            except Exception as exc:
                logger.exception(
                    "Error while sending alert to sink | sink=%s | error=%s",
                    sink.__class__.__name__,
                    exc,
                )


def main() -> None:
    logger = create_logger()

    settings = load_settings()
    massive_client = MassiveClient(api_key=settings.massive_api_key, logger=logger)

    # Prepare strategy context (can hold per-run / per-ticker state)
    strategy_ctx = StrategyContext(
        min_premium_usd=50_000.0,
        min_open_interest=100,
        max_dte_days=14,
    )

    # Build alert sinks (Telegram, console, etc.) once at startup
    alert_sinks: List[AlertSink] = build_alert_sinks(settings, logger)

    logger.info(
        "Worker starting | tickers=%s | interval=%ss",
        ",".join(settings.ticker_universe),
        settings.scan_interval_seconds,
    )

    # Main loop
    while True:
        for ticker in settings.ticker_universe:
            try:
                alerts = process_ticker(
                    ticker=ticker,
                    massive_client=massive_client,
                    strategy_ctx=strategy_ctx,
                    logger=logger,
                )
                if alerts:
                    dispatch_alerts(alerts, alert_sinks, logger)
            except Exception as exc:
                logger.exception(
                    "Unexpected error while processing ticker | ticker=%s | error=%s",
                    ticker,
                    exc,
                )

        logger.info(
            "Scan cycle complete, sleeping for %s seconds",
            settings.scan_interval_seconds,
        )
        time.sleep(settings.scan_interval_seconds)


if __name__ == "__main__":
    main()
