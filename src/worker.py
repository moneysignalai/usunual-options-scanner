from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import date
from typing import Iterable, List, Optional

from .alerts import AlertSink, build_alert_sinks
from .config import Settings, load_settings
from .massive_client import MassiveClient
from .models import UnusualOptionsCandidate
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


def _parse_expiration(expiration: Optional[str]) -> Optional[date]:
    if not expiration:
        return None
    try:
        return date.fromisoformat(expiration)
    except ValueError:
        return None


def _calculate_midpoint(contract) -> Optional[float]:
    if not contract.last_quote:
        return None
    if contract.last_quote.midpoint is not None:
        return contract.last_quote.midpoint
    if contract.last_quote.bid is None or contract.last_quote.ask is None:
        return None
    return (contract.last_quote.bid + contract.last_quote.ask) / 2


def _get_last_price(contract, midpoint: Optional[float]) -> Optional[float]:
    if contract.last_trade and contract.last_trade.price is not None:
        return contract.last_trade.price
    if contract.last_price is not None:
        return contract.last_price
    if midpoint is not None:
        return midpoint
    if contract.day and contract.day.close is not None:
        return contract.day.close
    if contract.prev_day and contract.prev_day.close is not None:
        return contract.prev_day.close
    return None


def _calculate_premium(
    last_price: Optional[float], volume: int, shares_per_contract: int
) -> float:
    if last_price is None or volume <= 0:
        return 0.0
    return last_price * volume * shares_per_contract


def _calculate_volume_oi_ratio(
    volume: int, open_interest: Optional[int]
) -> Optional[float]:
    if open_interest and open_interest > 0:
        return float(volume) / float(open_interest)
    return None


def _calculate_score(
    notional: float,
    volume_oi_ratio: Optional[float],
    rvol: Optional[float],
    dte_days: int,
) -> float:
    notional_score = min(max(notional / 100_000.0, 0.0), 10.0)
    rvol_value = rvol if rvol is not None else 1.0
    rvol_score = min(max(rvol_value, 0.0), 10.0)
    ratio_value = volume_oi_ratio if volume_oi_ratio is not None else 1.0
    ratio_score = min(max(ratio_value, 0.0), 10.0)

    if dte_days <= 0:
        dte_score = 0.0
    elif dte_days <= 7:
        dte_score = 5.0
    elif dte_days <= 21:
        dte_score = 3.0
    else:
        dte_score = 1.0

    raw_score = (
        notional_score * 0.4
        + rvol_score * 0.3
        + ratio_score * 0.2
        + dte_score * 0.1
    )
    return round(min(raw_score, 50.0), 2)


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
            logger.info("No snapshot returned | ticker=%s", ticker)
            continue

        contracts = snapshot_resp.results or []
        contract_count = len(contracts)
        logger.info(
            "Snapshot loaded | ticker=%s | contract_count=%s",
            ticker,
            contract_count,
        )

        if contract_count == 0:
            continue

        candidates: List[UnusualOptionsCandidate] = []
        for contract in contracts:
            contract_ticker = contract.details.ticker
            strike = contract.details.strike_price
            expiration = contract.details.expiration_date
            side = contract.details.contract_type
            mid = _calculate_midpoint(contract)
            last_price = _get_last_price(contract, mid)

            logger.debug(
                "FILTER | opt=%s | strike=%s | exp=%s | mid=%s | vol=%s | "
                "min_notional=%s | dte_min=%s | dte_max=%s",
                contract_ticker,
                strike,
                expiration,
                mid,
                contract.day.volume if contract.day else None,
                settings.unusual_min_notional,
                settings.unusual_min_dte_days,
                settings.unusual_max_dte_days,
            )

            expiration_date = _parse_expiration(expiration)
            if not expiration_date or not side:
                continue

            dte_days = (expiration_date - date.today()).days
            if (
                dte_days < settings.unusual_min_dte_days
                or dte_days > settings.unusual_max_dte_days
            ):
                continue

            if contract.day and contract.day.volume is not None:
                vol = contract.day.volume
            elif contract.prev_day and contract.prev_day.volume is not None:
                vol = contract.prev_day.volume
            else:
                vol = contract.volume or 0
            if vol < settings.unusual_min_volume:
                continue

            if contract.day and contract.day.open_interest is not None:
                open_interest = contract.day.open_interest
            elif contract.prev_day and contract.prev_day.open_interest is not None:
                open_interest = contract.prev_day.open_interest
            else:
                open_interest = contract.open_interest

            volume_oi_ratio = _calculate_volume_oi_ratio(vol, open_interest)
            if (
                volume_oi_ratio is None
                and settings.unusual_min_volume_oi_ratio > 0.0
            ):
                continue
            if (
                volume_oi_ratio is not None
                and volume_oi_ratio < settings.unusual_min_volume_oi_ratio
            ):
                continue

            shares_per_contract = contract.details.shares_per_contract or 100
            notional = _calculate_premium(last_price, vol, shares_per_contract)
            if notional < settings.unusual_min_notional:
                continue

            underlying_ticker = (
                contract.underlying_asset.ticker
                if contract.underlying_asset and contract.underlying_asset.ticker
                else ticker
            )
            score = _calculate_score(notional, volume_oi_ratio, contract.rvol, dte_days)
            if score < settings.unusual_min_unusual_score:
                continue
            if not candidates:
                logger.debug(
                    "Alert debug | ticker=%s side=%s strike=%s exp=%s notional=%s "
                    "vol=%s oi=%s vol_oi_ratio=%s rvol=%s dte=%s score=%s",
                    underlying_ticker,
                    side,
                    strike,
                    expiration,
                    notional,
                    vol,
                    open_interest,
                    volume_oi_ratio,
                    contract.rvol,
                    dte_days,
                    score,
                )
            candidates.append(
                UnusualOptionsCandidate(
                    options_ticker=contract_ticker,
                    underlying_ticker=underlying_ticker,
                    direction="BULLISH"
                    if side.lower() == "call"
                    else "BEARISH",
                    expiration_date=expiration_date,
                    strike=float(strike or 0.0),
                    contract_type=side.upper(),
                    last_price=last_price,
                    volume=vol,
                    open_interest=open_interest,
                    notional=notional,
                    volume_oi_ratio=volume_oi_ratio,
                    dte_days=dte_days,
                    score=score,
                )
            )

        if candidates:
            logger.info(
                "Found %d unusual contracts | ticker=%s", len(candidates), ticker
            )

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
