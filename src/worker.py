import asyncio
import logging
import signal
from typing import Dict, List

from .alerts import build_alert_sinks
from .config import load_settings
from .massive_client import MassiveClient, OptionContractSnapshot
from .scanner import scan_unusual_options
from .telegram_client import TelegramClient


logger = logging.getLogger("worker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


async def process_ticker(
    massive_client: MassiveClient,
    ticker: str,
    all_unusual_candidates: Dict[str, List[OptionContractSnapshot]],
    max_attempts: int = 3,
) -> None:
    """
    Fetch option snapshots for a single ticker and scan for unusual options.
    Retries up to `max_attempts` times on network errors.
    """
    attempt = 0
    while attempt < max_attempts:
        attempt += 1
        try:
            logger.info("Fetching option snapshots | ticker=%s | attempt=%d", ticker, attempt)
            snapshots = await massive_client.fetch_option_snapshots(ticker)
            logger.info(
                "Fetched %d option snapshots for ticker=%s", len(snapshots), ticker
            )

            unusual_candidates = scan_unusual_options(ticker, snapshots)
            if unusual_candidates:
                all_unusual_candidates[ticker] = unusual_candidates
                logger.info(
                    "Found %d unusual option candidates for ticker=%s",
                    len(unusual_candidates),
                    ticker,
                )
            else:
                logger.info("No unusual options found for ticker=%s", ticker)

            # Success, stop retrying
            return

        except Exception as e:
            logger.exception(
                "Error processing ticker=%s on attempt=%d", ticker, attempt
            )
            if attempt >= max_attempts:
                logger.error(
                    "Max attempts reached for ticker=%s. Skipping.", ticker
                )
            else:
                # Consider an exponential backoff or fixed short sleep if desired
                await asyncio.sleep(1.0)


async def main_loop() -> None:
    """
    Main loop: periodically fetch snapshots for all tickers in the universe,
    detect unusual options, and send alerts to the configured sinks.
    """
    settings = load_settings()

    logger.info(
        "Worker starting | tickers=%s | interval=%ss",
        ",".join(settings.ticker_universe),
        settings.poll_interval_seconds,
    )

    massive_client = MassiveClient(
        api_key=settings.massive_api_key,
        base_url=settings.massive_base_url,
    )

    telegram_client = None
    if settings.enable_telegram:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            logger.warning(
                "Telegram alerts enabled but bot token or chat ID missing. Disabling Telegram."
            )
        else:
            # ✅ FIX: use correct TelegramClient signature (token, chat_id, logger)
            telegram_client = TelegramClient(
                token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
                logger=logger,
            )
            logger.info("Telegram alerts enabled")

    # ✅ build alert sinks (Telegram, future sinks, etc.)
    alert_sinks = build_alert_sinks(
        logger=logger,
        enable_telegram=settings.enable_telegram,
        telegram_client=telegram_client,
    )

    stop_event = asyncio.Event()

    def handle_signal(sig, frame):
        logger.info("Received signal %s, shutting down...", sig)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        while not stop_event.is_set():
            all_unusual_candidates: Dict[str, List[OptionContractSnapshot]] = {}

            # Process each ticker, possibly in parallel
            tasks = [
                process_ticker(massive_client, ticker, all_unusual_candidates)
                for ticker in settings.ticker_universe
            ]
            await asyncio.gather(*tasks)

            # Dispatch alerts for all tickers that had unusual candidates
            if all_unusual_candidates:
                logger.info(
                    "Dispatching alerts for %d tickers", len(all_unusual_candidates)
                )
                for ticker, candidates in all_unusual_candidates.items():
                    for sink in alert_sinks:
                        try:
                            await sink.send_alerts(ticker, candidates)
                        except Exception:
                            logger.exception(
                                "Error sending alerts via sink=%s for ticker=%s",
                                sink.__class__.__name__,
                                ticker,
                            )
            else:
                logger.info("No unusual options detected in this cycle")

            logger.info(
                "Sleeping for %d seconds before next cycle",
                settings.poll_interval_seconds,
            )
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=settings.poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                # Timeout means it's time for the next cycle
                continue

    finally:
        logger.info("Worker shut down")


def main() -> None:
    asyncio.run(main_loop())


if __name__ == "__main__":
    main()