import logging
import signal
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import ValidationError

from .config import load_settings
from .massive_client import MassiveClient, MassiveAPIError
from .models import OptionSnapshot
from .scanner import filter_contracts
from .telegram_client import TelegramClient
from . import utils

logger = logging.getLogger("worker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)


# ---------- Graceful shutdown handling ----------

_stop_requested = False


def _handle_signal(signum, frame):
    global _stop_requested
    logger.info("Received shutdown signal %s, stopping after current loop...", signum)
    _stop_requested = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


@contextmanager
def log_time(message: str):
    start = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start
        logger.info("%s | elapsed=%.3fs", message, elapsed)


# ---------- Core worker logic ----------


def _build_symbol_batches(symbols: Sequence[str], batch_size: int = 50) -> List[List[str]]:
    """
    Split the symbol universe into batches for Massive snapshot calls.
    """
    return [list(symbols[i : i + batch_size]) for i in range(0, len(symbols), batch_size)]


def _fetch_snapshots_for_batch(
    client: MassiveClient,
    symbols: Sequence[str],
    limit_per_symbol: int,
) -> Dict[str, List[OptionSnapshot]]:
    """
    Fetch option snapshots for a batch of underlying symbols.
    Returns mapping: underlying -> list of OptionSnapshot.
    """
    snapshots_by_underlying: Dict[str, List[OptionSnapshot]] = {}

    for symbol in symbols:
        try:
            with log_time(f"Massive snapshot for {symbol}"):
                snapshots = client.get_option_snapshots(symbol, limit=limit_per_symbol)
        except MassiveAPIError as e:
            logger.error(
                "Skipping ticker due to Massive API error | ticker=%s | error=%s",
                symbol,
                e,
            )
            continue

        if not snapshots:
            logger.info("No option snapshots returned | ticker=%s", symbol)
            continue

        snapshots_by_underlying[symbol] = snapshots

    return snapshots_by_underlying


def _scan_and_alert_for_symbol(
    symbol: str,
    snapshots: List[OptionSnapshot],
    telegram_client: Optional[TelegramClient],
    dry_run: bool,
) -> int:
    """
    Run the scanning logic for a single underlying and send alerts if any qualify.
    Returns number of alerts sent for this symbol.
    """
    alerts_sent = 0

    # Filter & score contracts according to strategy rules
    filtered = filter_contracts(symbol, snapshots)

    if not filtered:
        logger.info("No contracts passed filters | ticker=%s", symbol)
        return 0

    for alert in filtered:
        msg = utils.format_alert_message(alert)

        if dry_run or telegram_client is None:
            logger.info("DRY RUN ALERT | ticker=%s\n%s", symbol, msg)
        else:
            try:
                telegram_client.send_message(msg)
                alerts_sent += 1
                logger.info(
                    "Sent Telegram alert | ticker=%s | contract=%s | side=%s",
                    symbol,
                    alert.contract_symbol,
                    alert.side,
                )
            except Exception as e:
                logger.exception(
                    "Failed to send Telegram alert | ticker=%s | contract=%s | error=%s",
                    symbol,
                    alert.contract_symbol,
                    e,
                )

    return alerts_sent


def main() -> None:
    try:
        settings = load_settings()
    except ValidationError as e:
        logger.error("Invalid settings: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.exception("Failed to load settings: %s", e)
        sys.exit(1)

    tickers = settings.ticker_universe
    interval = settings.scan_interval_seconds

    logger.info(
        "Worker starting | tickers=%s | interval=%ss",
        ",".join(tickers),
        interval,
    )

    massive_client = MassiveClient(
        api_key=settings.massive_api_key,
        base_url=settings.massive_base_url,
        timeout=settings.massive_timeout_seconds,
    )

    telegram_client: Optional[TelegramClient] = None
    if settings.telegram_enabled:
        if settings.telegram_bot_token and settings.telegram_chat_id:
            try:
                telegram_client = TelegramClient(
                    settings.telegram_bot_token,
                    settings.telegram_chat_id,
                    logger=logger,
                )
                logger.info("Telegram client initialized | telegram=True")
            except Exception as e:
                logger.exception("Failed to initialize Telegram client: %s", e)
        else:
            logger.warning(
                "Telegram is enabled but bot token or chat id missing | telegram_enabled=True"
            )

    logger.info(
        "Config loaded | tickers=%s | interval=%ss | telegram=%s",
        ",".join(tickers),
        interval,
        bool(telegram_client),
    )

    symbol_batches = _build_symbol_batches(tickers, batch_size=settings.batch_size)

    # Main loop
    while not _stop_requested:
        loop_start = time.time()
        total_alerts = 0
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info("Scan loop started | time=%s", now)

        for batch in symbol_batches:
            if _stop_requested:
                break

            logger.info("Processing batch | size=%d | batch=%s", len(batch), ",".join(batch))

            try:
                snapshots_by_underlying = _fetch_snapshots_for_batch(
                    massive_client,
                    batch,
                    limit_per_symbol=settings.contracts_per_symbol,
                )
            except Exception as e:
                logger.exception("Unexpected error while fetching snapshots for batch: %s", e)
                continue

            for symbol, snapshots in snapshots_by_underlying.items():
                try:
                    alerts_for_symbol = _scan_and_alert_for_symbol(
                        symbol=symbol,
                        snapshots=snapshots,
                        telegram_client=telegram_client,
                        dry_run=settings.dry_run,
                    )
                    total_alerts += alerts_for_symbol
                except Exception as e:
                    logger.exception(
                        "Unexpected error while scanning/alerting for symbol | ticker=%s | error=%s",
                        symbol,
                        e,
                    )

        loop_elapsed = time.time() - loop_start
        logger.info(
            "Scan loop finished | alerts_sent=%d | elapsed=%.3fs",
            total_alerts,
            loop_elapsed,
        )

        if _stop_requested:
            break

        sleep_for = max(0, interval - loop_elapsed)
        if sleep_for > 0:
            logger.info("Sleeping before next loop | sleep=%.3fs", sleep_for)
            time.sleep(sleep_for)

    logger.info("Worker stopped gracefully")


if __name__ == "__main__":
    main()
