import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from config import Settings, load_settings
from massive_client import MassiveClient, MassiveAPIError
from models import OptionAlert
from scanner import scan_ticker_for_unusual_options
from telegram_client import TelegramClient
from utils import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    """Main entry point for the unusual options scanner worker."""
    settings = load_settings()
    logger = setup_logging(settings.log_level)

    logger.info(
        "Config loaded | tickers=%s | interval=%ss | telegram=%s",
        ",".join(settings.ticker_universe),
        settings.scan_interval_seconds,
        settings.enable_telegram,
    )

    massive_client = MassiveClient(api_key=settings.massive_api_key, logger=logger)

    telegram_client: Optional[TelegramClient] = None
    if settings.enable_telegram:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            logger.error(
                "ENABLE_TELEGRAM=true but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing"
            )
        else:
            telegram_client = TelegramClient(
                settings.telegram_bot_token,
                settings.telegram_chat_id,
                logger=logger,
            )

    # ✅ FIX: include enable_telegram parameter
    alert_sinks = build_alert_sinks(
        logger=logger,
        enable_telegram=settings.enable_telegram,
        telegram_client=telegram_client,
    )

    worker = Worker(
        settings=settings,
        massive_client=massive_client,
        alert_sinks=alert_sinks,
        logger=logger,
    )

    def handle_sigterm(signum, frame):
        logger.info("Received SIGTERM, shutting down gracefully...")
        worker.stop()

    signal.signal(signal.SIGTERM, handle_sigterm)

    try:
        worker.run()
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, shutting down...")
        worker.stop()
    except Exception:
        logger.exception("Unhandled exception in worker")
        sys.exit(1)


class Worker:
    def __init__(
        self,
        settings: Settings,
        massive_client: MassiveClient,
        alert_sinks: List["AlertSink"],
        logger: logging.Logger,
    ) -> None:
        self.settings = settings
        self.massive_client = massive_client
        self.alert_sinks = alert_sinks
        self.logger = logger
        self._running = True
        self._last_alert_time: Dict[str, datetime] = {}

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        cycle = 0
        while self._running:
            cycle += 1
            start_time = time.time()
            alerts: List[OptionAlert] = []

            for ticker in self.settings.ticker_universe:
                if not self._running:
                    break

                try:
                    ticker_alerts = scan_ticker_for_unusual_options(
                        massive_client=self.massive_client,
                        ticker=ticker,
                        max_dte_days=self.settings.unusual_max_dte_days,
                        min_dte_days=self.settings.unusual_min_dte_days,
                        min_notional=self.settings.unusual_min_notional,
                        min_volume_oi_ratio=self.settings.unusual_min_volume_oi_ratio,
                        logger=self.logger,
                    )
                except MassiveAPIError as e:
                    self.logger.error(
                        "Skipping ticker due to Massive API error | ticker=%s | error=%s",
                        ticker,
                        e,
                    )
                    continue
                except Exception:
                    self.logger.exception(
                        "Unexpected error while scanning ticker | ticker=%s", ticker
                    )
                    continue

                for alert in ticker_alerts:
                    last_time = self._last_alert_time.get(alert.contract_symbol)
                    if last_time and (datetime.now(timezone.utc) - last_time) < timedelta(
                        minutes=5
                    ):
                        continue

                    alerts.append(alert)
                    self._last_alert_time[alert.contract_symbol] = datetime.now(
                        timezone.utc
                    )

            for alert in alerts:
                for sink in self.alert_sinks:
                    try:
                        sink.send(alert)
                    except Exception:
                        self.logger.exception(
                            "Failed to send alert to sink | sink=%s | alert=%s",
                            type(sink).__name__,
                            alert.contract_symbol,
                        )

            duration = time.time() - start_time
            self.logger.info(
                "Scan cycle complete | cycle=%d | tickers=%d | alerts=%d | duration=%.2fs",
                cycle,
                len(self.settings.ticker_universe),
                len(alerts),
                duration,
            )

            if not self._running:
                break

            sleep_time = max(0, self.settings.scan_interval_seconds - duration)
            time.sleep(sleep_time)


class AlertSink:
    def send(self, alert: OptionAlert) -> None:
        raise NotImplementedError


class LoggingAlertSink(AlertSink):
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def send(self, alert: OptionAlert) -> None:
        self.logger.info("ALERT | %s", alert.format_for_logging())


class TelegramAlertSink(AlertSink):
    def __init__(self, telegram_client: TelegramClient, logger: logging.Logger) -> None:
        self.telegram_client = telegram_client
        self.logger = logger

    def send(self, alert: OptionAlert) -> None:
        message = alert.format_for_telegram()
        self.telegram_client.send_message(message)
        self.logger.info(
            "Sent alert to Telegram | contract=%s", alert.contract_symbol
        )


def build_alert_sinks(
    logger: logging.Logger,
    enable_telegram: bool,
    telegram_client: Optional[TelegramClient] = None,
) -> List[AlertSink]:
    sinks: List[AlertSink] = [LoggingAlertSink(logger=logger)]

    if enable_telegram and telegram_client is not None:
        sinks.append(TelegramAlertSink(telegram_client=telegram_client, logger=logger))

    return sinks


if __name__ == "__main__":
    main()
