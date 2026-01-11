from __future__ import annotations

import logging
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


def _get_last_price(
    contract: OptionContractSnapshot, midpoint: Optional[float]
) -> Optional[float]:
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


def _calculate_premium(last_price: Optional[float], volume: int) -> float:
    if last_price is None or volume <= 0:
        return 0.0
    return float(last_price) * int(volume) * 100.0


def _calculate_volume_oi_ratio(
    volume: int, open_interest: Optional[int]
) -> Optional[float]:
    if open_interest and open_interest > 0:
        return float(volume) / float(open_interest)
    return None


# NOTE: Score blends notional ($ premium), relative volume (rvol), volume/OI,
# and DTE (days to expiration). With current weights, the effective range is
# roughly 0–9.5 (e.g., 10*0.4 + 10*0.3 + 10*0.2 + 5*0.1 = 9.5). Keep
# UNUSUAL_MIN_UNUSUAL_SCORE within this range (e.g., ~3–7) or no contracts
# will pass the filter.
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

        if contract.day and contract.day.volume is not None:
            volume = contract.day.volume
        elif contract.prev_day and contract.prev_day.volume is not None:
            volume = contract.prev_day.volume
        else:
            volume = 0
        if volume < thresholds.min_volume:
            continue

        midpoint = _calculate_mid_price(contract)
        last_price = _get_last_price(contract, midpoint)
        notional = _calculate_premium(last_price, volume)
        if notional < thresholds.min_notional:
            continue

        if contract.day and contract.day.open_interest is not None:
            open_interest = contract.day.open_interest
        elif contract.prev_day and contract.prev_day.open_interest is not None:
            open_interest = contract.prev_day.open_interest
        elif contract.open_interest is not None:
            open_interest = contract.open_interest
        else:
            open_interest = None

        volume_oi_ratio = _calculate_volume_oi_ratio(volume, open_interest)
        if (
            volume_oi_ratio is None
            and thresholds.min_volume_oi_ratio > 0.0
        ):
            continue
        if (
            volume_oi_ratio is not None
            and volume_oi_ratio < thresholds.min_volume_oi_ratio
        ):
            continue

        score = _calculate_score(notional, volume_oi_ratio, contract.rvol, dte_days)
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
                last_price=last_price,
                volume=volume,
                open_interest=open_interest,
                notional=notional,
                volume_oi_ratio=volume_oi_ratio,
                rvol=contract.rvol,
                dte_days=dte_days,
                score=score,
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates
