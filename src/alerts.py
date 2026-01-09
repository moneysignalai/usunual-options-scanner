from __future__ import annotations

import logging
from datetime import date
from typing import Iterable, Optional

from .models import UnusualOptionsCandidate
from .telegram_client import TelegramClient, TelegramDeliveryError


def _format_expiration(expiration: date) -> str:
    return expiration.strftime("%m-%d-%Y")


def _format_number(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.2f}"


def _fmt_int(value: Optional[int]) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


def _format_ratio(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}x"


def _alert_title(candidate: UnusualOptionsCandidate) -> str:
    if candidate.is_sweep:
        return f"📌 {candidate.underlying_ticker} — {candidate.contract_type} (SWEEP)"
    return f"📌 {candidate.underlying_ticker} — {candidate.contract_type}"


def format_alert_message(candidate: UnusualOptionsCandidate) -> str:
    expiration = _format_expiration(candidate.expiration_date)
    notional = _format_number(candidate.notional)
    volume = _fmt_int(candidate.volume)
    if candidate.open_interest is None:
        vol_oi_line = f"📊 Vol: {volume} (OI N/A)"
    elif candidate.open_interest == 0:
        vol_oi_line = f"📊 Vol/OI: {volume}/0 (Ratio N/A)"
    else:
        open_interest = _fmt_int(candidate.open_interest)
        ratio_text = _format_ratio(candidate.volume_oi_ratio)
        vol_oi_line = f"📊 Vol/OI: {volume}/{open_interest} (Ratio {ratio_text})"
    last_price = _format_number(candidate.last_price)

    if candidate.is_sweep:
        header = "🚨 SWEEP DETECTED — UNUSUAL OPTIONS FLOW"
        title = _alert_title(candidate)
        footer = "#FlowBot #UnusualOptions #Sweep"
    else:
        header = "📢 UNUSUAL OPTIONS FLOW DETECTED"
        title = _alert_title(candidate)
        footer = "#FlowBot #UnusualOptions"

    if candidate.debug_alert:
        header = f"[DEBUG ALERT] {header}"
        footer = f"{footer} #Debug"

    lines = [
        header,
        "",
        title,
        f"🎯 Strike: {candidate.strike} | ⏳ Expires: {expiration}",
        f"💸 Premium: ${notional}",
        vol_oi_line,
        f"📈 Last: ${last_price} | DTE: {candidate.dte_days}",
        f"⭐ Score: {candidate.score:.2f}",
        "",
        footer,
    ]
    return "\n".join(lines)


class AlertSink:
    def send(self, candidate: UnusualOptionsCandidate) -> None:
        raise NotImplementedError


class ConsoleAlertSink(AlertSink):
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def send(self, candidate: UnusualOptionsCandidate) -> None:
        message = format_alert_message(candidate)
        self._logger.info(
            "Alert dispatched | ticker=%s | strike=%s | sweep=%s | message=%s",
            candidate.underlying_ticker,
            candidate.strike,
            candidate.is_sweep,
            message.replace("\n", " | "),
        )
        self._logger.info(
            "Alert sent via %s | ticker=%s | title=%s",
            self.__class__.__name__,
            candidate.underlying_ticker,
            _alert_title(candidate),
        )


class TelegramAlertSink(AlertSink):
    def __init__(self, client: TelegramClient, logger: logging.Logger) -> None:
        self._client = client
        self._logger = logger

    def send(self, candidate: UnusualOptionsCandidate) -> None:
        message = format_alert_message(candidate)
        try:
            self._client.send_message(message)
            self._logger.info(
                "Alert sent via %s | ticker=%s | title=%s",
                self.__class__.__name__,
                candidate.underlying_ticker,
                _alert_title(candidate),
            )
        except TelegramDeliveryError as exc:
            self._logger.error(
                "Telegram alert failed | ticker=%s | error=%s",
                candidate.underlying_ticker,
                exc,
            )


def build_alert_sinks(
    logger: logging.Logger,
    enable_telegram: bool,
    telegram_client: Optional[TelegramClient] = None,
) -> Iterable[AlertSink]:
    sinks: list[AlertSink] = [ConsoleAlertSink(logger)]
    if enable_telegram and telegram_client is not None:
        sinks.append(TelegramAlertSink(telegram_client, logger))
    return sinks
