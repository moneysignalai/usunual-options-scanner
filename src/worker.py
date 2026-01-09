from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Iterable, List

from .alerts import AlertSink, build_alert_sinks
from .config import Settings, load_settings
from .massive_client import MassiveClient
from .models import UnusualOptionsCandidate
from .strategy import find_unusual_activity
from .telegram_client import TelegramClient


logger = logging.getLogger("worker")


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    handler.setFormatter(formatter)

    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if the worker is restarted
    if not logger.handlers:
        logger.addHandler(handler)


def _build_massive_client(settings: Settings) -> MassiveClient:
    """
    MassiveClient already knows how to read base URL and API key
    from Settings, so we just pass the settings object through.
    """
    return MassiveClient(settings=settings)


def _build_telegram_client(settings: Settings) -> TelegramClient | None:
    """
    Build Telegram client if Telegram alerts are enabled and credentials
    are configured. Otherwise return None.
    """
    if not settings.enable_telegram:
        return None

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning(
            "Telegram alerts enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID "
            "is not configured. Telegram alerts will be disabled."
        )
        return None

    return TelegramClient(
        token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
        logger=logging.getLogger("worker.telegram"),
    )


def _build_sinks(settings: Settings) -> Iterable[AlertSink]:
    """
    Build the list of alert sinks (console + optional Telegram),
    using the current Settings.
    """
    telegram_client = _build_telegram_client(settings)

    sinks = build_alert_sinks(
        logger=logging.getLogger("worker.alerts"),
        enable_telegram=bool(telegram_client),
        telegram_client=telegram_client,
    )
    return sinks


def _scan_once(
    settings: Settings,
    client: MassiveClient,
    sinks: Iterable[AlertSink],
) -> None:
    """
    Run a single scan across the configured ticker universe.
    """
    tickers = settings.ticker_universe
    if not tickers:
        logger.warning("No tickers configured in TICKER_UNIVERSE; nothing to scan.")
        return

    logger.info("Starting scan cycle | tickers=%s", ",".join(tickers))

    for ticker in tickers:
        try:
            snapshot_resp = client.get_option_chain_snapshot(ticker)
        except Exception as exc:
            logger.exception(
                "Failed to fetch option chain snapshot | ticker=%s | error=%s",
                ticker,
                exc,
            )
            continue

        if not snapshot_resp or not snapshot_resp.results:
            logger.info("No option chain data returned | ticker=%s", ticker)
            continue

        candidates: List[UnusualOptionsCandidate] = []
        for result in snapshot_resp.results:
            candidates.extend(find_unusual_activity(result, settings))

        if not candidates:
            logger.info("No unusual activity found | ticker=%s", ticker)
            continue

        logger.info(
            "Unusual activity detected | ticker=%s | count=%d",
            ticker,
            len(candidates),
        )

        for candidate in candidates:
            for sink in sinks:
                try:
                    sink.send(candidate)
                except Exception as exc:
                    logger.exception(
                        "Alert sink failed | ticker=%s | sink=%s | error=%s",
                        ticker,
                        sink.__class__.__name__,
                        exc,
                    )


def main() -> None:
    _configure_logging()
    logger.info("Worker starting up")

    settings = load_settings()
    client = _build_massive_client(settings)
    sinks = list(_build_sinks(settings))

    scan_interval = settings.scan_interval_seconds
    stopped = False

    def _handle_signal(signum, frame):
        nonlocal stopped
        logger.info("Received signal %s, shutting down gracefully", signum)
        stopped = True

    # Graceful shutdown for Render
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while not stopped:
        start = time.time()
        _scan_once(settings, client, sinks)
        elapsed = time.time() - start

        # Respect configured scan interval
        sleep_for = max(0, scan_interval - elapsed)
        if sleep_for > 0:
            logger.info("Sleeping for %.2f seconds before next scan", sleep_for)
            time.sleep(sleep_for)

    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
