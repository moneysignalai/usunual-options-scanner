from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import date
from typing import Iterable, List

from .alerts import AlertSink, build_alert_sinks
from .config import Settings, load_settings
from .massive_client import MassiveClient
from .models import OptionContractSnapshot, UnusualOptionsCandidate
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
    # 2) flatten contracts (strategy)
    # 3) filter by DTE/notional/volume/OI/ratio
    # 4) build Alert objects (UnusualOptionsCandidate)
    # 5) send to sinks
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
            logger.info("No snapshot | ticker=%s", ticker)
            continue

        results = snapshot_resp.results or []
        if not results:
            logger.info("No snapshot data for ticker=%s", ticker)
            continue

        contract_count = sum(len(result.contracts or []) for result in results)
        logger.info(
            "Snapshot loaded | ticker=%s | contract_count=%s",
            ticker,
            contract_count,
        )

        candidates: List[UnusualOptionsCandidate] = []
        rejection_logs = 0
        today = date.today()

        for result in results:
            contracts = result.contracts or []
            if not contracts:
                continue

            for contract in contracts:
                reasons: List[str] = []

                dte_days = None
                if contract.expiration_date:
                    dte_days = (contract.expiration_date - today).days
                    if dte_days < settings.min_time_to_expiry_days:
                        reasons.append("dte")
                else:
                    reasons.append("missing_expiry")

                volume = contract.volume or 0
                if volume < settings.min_contract_volume:
                    reasons.append("volume")

                oi = contract.open_interest or 0
                if oi == 0:
                    reasons.append("zero_oi")

                price = _resolve_price(contract)
                if price is None:
                    reasons.append("price")

                notional = _calculate_notional(price, oi or volume)
                if notional < settings.min_notional:
                    reasons.append("notional")

                ratio = _calculate_ratio(volume, oi)
                if ratio < settings.min_volume_oi_ratio:
                    reasons.append("vol/oi")

                if reasons:
                    if settings.debug_mode and rejection_logs < 5:
                        logger.debug(
                            "Rejected %s reasons=%s",
                            contract.options_ticker or "UNKNOWN",
                            reasons,
                        )
                        rejection_logs += 1
                    continue

                candidate = _build_candidate(
                    contract=contract,
                    underlying=result.underlying_symbol or contract.underlying_ticker or ticker,
                    notional=notional,
                    ratio=ratio,
                    dte_days=dte_days or 0,
                )
                candidates.append(candidate)

                logger.info(
                    "ALERT EMITTED | %s %s | notional=%s",
                    ticker,
                    candidate.options_ticker,
                    notional,
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
            if settings.debug_mode:
                logger.info("No contracts passed filters | ticker=%s", ticker)
            else:
                logger.info("No unusual activity found | ticker=%s", ticker)
            continue
        logger.info(
            "Unusual activity detected | ticker=%s | count=%d",
            ticker,
            len(candidates),
        )


def _resolve_price(contract: OptionContractSnapshot) -> float | None:
    if contract.bid is not None and contract.ask is not None:
        return (contract.bid + contract.ask) / 2
    if contract.ask is not None:
        return contract.ask
    if contract.bid is not None:
        return contract.bid
    return contract.last_price


def _calculate_notional(price: float | None, size: int) -> float:
    if price is None or size <= 0:
        return 0.0
    return price * size * 100


def _calculate_ratio(volume: int, open_interest: int) -> float:
    if open_interest <= 0:
        return 0.0
    return volume / open_interest


def _build_candidate(
    contract: OptionContractSnapshot,
    underlying: str,
    notional: float,
    ratio: float,
    dte_days: int,
) -> UnusualOptionsCandidate:
    contract_type = (contract.contract_type or "").upper()
    direction = "UNKNOWN"
    if contract_type == "CALL":
        direction = "BULLISH"
    elif contract_type == "PUT":
        direction = "BEARISH"

    return UnusualOptionsCandidate(
        options_ticker=contract.options_ticker or "",
        underlying_ticker=underlying,
        direction=direction,
        expiration_date=contract.expiration_date,
        strike=float(contract.strike or 0.0),
        contract_type=contract_type or "UNKNOWN",
        last_price=contract.last_price,
        volume=contract.volume,
        open_interest=contract.open_interest,
        notional=notional,
        volume_oi_ratio=ratio,
        dte_days=dte_days,
        score=notional + ratio,
        is_sweep=bool(contract.sweep),
        flow_type="SWEEP" if contract.sweep else "STANDARD",
        debug_alert=False,
    )


def main() -> None:
    _configure_logging()
    logger.info("Worker starting up")

    settings = load_settings()
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.info(
        "Strategy thresholds | min_notional=%s | min_contract_volume=%s | "
        "min_volume_oi_ratio=%s | min_time_to_expiry_days=%s | debug_mode=%s",
        settings.min_notional,
        settings.min_contract_volume,
        settings.min_volume_oi_ratio,
        settings.min_time_to_expiry_days,
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

    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
