from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Optional

from .config import Settings
from .models import OptionContractSnapshot, UnusualOptionsCandidate

logger = logging.getLogger("strategy")


@dataclass(frozen=True)
class UnusualThresholds:
    min_dte_days: int
    max_dte_days: int
    min_notional: float
    min_volume: int
    min_volume_oi_ratio: float


def _get_effective_thresholds(settings: Settings) -> UnusualThresholds:
    if settings.debug_mode:
        return UnusualThresholds(
            min_dte_days=0,
            max_dte_days=max(settings.unusual_max_dte_days, 60),
            min_notional=min(settings.unusual_min_notional, 1_000.0),
            min_volume=min(settings.unusual_min_volume, 1),
            min_volume_oi_ratio=min(settings.unusual_min_volume_oi_ratio, 0.0),
        )

    return UnusualThresholds(
        min_dte_days=settings.unusual_min_dte_days,
        max_dte_days=settings.unusual_max_dte_days,
        min_notional=settings.unusual_min_notional,
        min_volume=settings.unusual_min_volume,
        min_volume_oi_ratio=settings.unusual_min_volume_oi_ratio,
    )


def _parse_expiration(expiration: Optional[str]) -> Optional[date]:
    if not expiration:
        return None
    try:
        return date.fromisoformat(expiration)
    except ValueError:
        return None


def _calculate_mid_price(contract: OptionContractSnapshot) -> Optional[float]:
    if not contract.last_quote:
        return None
    if contract.last_quote.midpoint is not None:
        return contract.last_quote.midpoint
    if contract.last_quote.bid is None or contract.last_quote.ask is None:
        return None
    return (contract.last_quote.bid + contract.last_quote.ask) / 2


def _calculate_notional(
    contract: OptionContractSnapshot,
    midpoint: Optional[float],
    volume: int,
) -> float:
    shares_per_contract = contract.details.shares_per_contract or 100
    if midpoint is None or volume <= 0:
        return 0.0
    return midpoint * volume * shares_per_contract


def _calculate_score(notional: float, ratio: float, dte_days: int) -> float:
    ratio_capped = min(ratio, 10.0)
    notional_log = math.log10(max(notional, 1.0))
    dte_bonus = max(0.0, (30 - dte_days) / 30)
    return ratio_capped + notional_log + dte_bonus


def find_unusual_activity(
    contracts: Iterable[OptionContractSnapshot],
    settings: Settings,
    underlying_ticker: Optional[str] = None,
) -> List[UnusualOptionsCandidate]:
    candidates: List[UnusualOptionsCandidate] = []
    thresholds = _get_effective_thresholds(settings)
    today = date.today()

    for contract in contracts:
        expiration_date = _parse_expiration(contract.details.expiration_date)
        side = contract.details.contract_type
        if not expiration_date or not side:
            continue

        dte_days = (expiration_date - today).days
        if dte_days < thresholds.min_dte_days or dte_days > thresholds.max_dte_days:
            continue

        volume = contract.day.volume if contract.day and contract.day.volume else 0
        if volume < thresholds.min_volume:
            continue

        midpoint = _calculate_mid_price(contract)
        notional = _calculate_notional(contract, midpoint, volume)
        if notional < thresholds.min_notional:
            continue

        open_interest = None
        volume_oi_ratio = (
            volume / open_interest if open_interest and open_interest > 0 else float(volume)
        )
        if volume_oi_ratio < thresholds.min_volume_oi_ratio:
            continue

        score = _calculate_score(notional, volume_oi_ratio, dte_days)
        candidates.append(
            UnusualOptionsCandidate(
                options_ticker=contract.details.ticker,
                underlying_ticker=(
                    contract.underlying_asset.ticker
                    if contract.underlying_asset and contract.underlying_asset.ticker
                    else underlying_ticker or ""
                ),
                direction="BULLISH" if side.lower() == "call" else "BEARISH",
                expiration_date=expiration_date,
                strike=float(contract.details.strike_price or 0.0),
                contract_type=side.upper(),
                last_price=midpoint,
                volume=volume,
                open_interest=open_interest,
                notional=notional,
                volume_oi_ratio=volume_oi_ratio,
                dte_days=dte_days,
                score=score,
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates
