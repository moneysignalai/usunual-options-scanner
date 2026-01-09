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

    # PIPELINE:
    # 1) fetch snapshot
    # 2) filter contracts
    # 3) build Alert objects (UnusualOptionsCandidate)
    # 4) send to sinks
    logger.info(
        "Starting scan cycle | tickers=%s | ticker_count=%d",
        ",".join(tickers),
        len(tickers),
    )

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

        if snapshot_resp is None:
            logger.info("No snapshot data | ticker=%s", ticker)
            continue

        results = snapshot_resp.results or []
        if not results:
            logger.info("No snapshot data | ticker=%s", ticker)
            continue

        contract_count = sum(len(result.contracts or []) for result in results)
        logger.info(
            "Snapshot loaded | ticker=%s | contract_count=%s",
            ticker,
            contract_count,
        )

        candidates: List[UnusualOptionsCandidate] = []

        for result in results:
            contracts = result.contracts or []
            if not contracts:
                continue

            candidates.extend(find_unusual_activity(result, settings))

        for candidate in candidates:
            logger.info(
                "ALERT EMITTED | %s %s | notional=%s",
                ticker,
                candidate.options_ticker,
                candidate.notional,
            )
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

        if not candidates:
            logger.info("No contracts passed filters | ticker=%s", ticker)
            continue
        logger.info(
            "Unusual activity found | ticker=%s | contracts_passing=%d",
            ticker,
            len(candidates),
        )


def main() -> None:
    _configure_logging()
    logger.info("Worker starting up")

    settings = load_settings()
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.info(
        "Strategy thresholds | min_notional=%s | min_volume=%s | "
        "min_volume_oi_ratio=%s | min_dte_days=%s | max_dte_days=%s | "
        "min_trade_count=%s | min_trade_size=%s | min_rvol=%s | "
        "min_iv_pctile=%s | max_otm_pct=%s | spread_bps=%s | "
        "min_unusual_score=%s | debug_mode=%s",
        settings.unusual_min_notional,
        settings.unusual_min_volume,
        settings.unusual_min_volume_oi_ratio,
        settings.unusual_min_dte_days,
        settings.unusual_max_dte_days,
        settings.unusual_min_trade_count,
        settings.unusual_min_trade_size,
        settings.unusual_min_rvol,
        settings.unusual_min_iv_pctile,
        settings.unusual_max_otm_pct,
        settings.unusual_spread_threshold_bps,
        settings.unusual_min_unusual_score,
        settings.debug_mode,
    )
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

    client.close()
    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
