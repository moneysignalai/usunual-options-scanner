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


def _calculate_score(notional: float, volume_oi_ratio: float, dte_days: int) -> float:
    """
    Compute a bounded 0–100 “unusualness” score combining:
    - notional size
    - volume/oi ratio
    - days to expiration

    Design:
    - Notional contributes 0–50 points
    - Vol/OI ratio contributes 0–30 points (after clamping)
    - DTE contributes 0–20 points with a sweet spot around ~10 DTE
    """

    # Guard against None / bad values
    notional = float(notional or 0.0)
    volume_oi_ratio = float(volume_oi_ratio or 0.0)
    dte_days = int(dte_days or 0)

    # 1) Ratio component: 0–30
    # Cap ratio at 25 so extreme outliers don’t dominate.
    ratio_capped = max(0.0, min(volume_oi_ratio, 25.0))
    ratio_score = (ratio_capped / 25.0) * 30.0  # 0–30

    # 2) Notional component: 0–50
    # Use log10(notional) so size scales sensibly by order of magnitude.
    if notional <= 0:
        notional_score = 0.0
    else:
        # Rough intuition:
        # - $10k  => log10(1e4)  = 4  => score ~ 0
        # - $100k => log10(1e5)  = 5  => score ~ 10
        # - $1M   => log10(1e6)  = 6  => score ~ 20
        # - $10M  => log10(1e7)  = 7  => score ~ 30
        # - $100M => log10(1e8)  = 8  => score ~ 40
        log_n = math.log10(notional)
        notional_score = (log_n - 4.0) * 10.0
        notional_score = max(0.0, min(notional_score, 50.0))  # clamp to 0–50

    # 3) DTE component: 0–20
    # We want near-term flow (around ~10 DTE) to score higher.
    if dte_days <= 0:
        dte_score = 0.0
    else:
        # Center at 10 days; decay as we move away.
        # distance 0 -> 20 pts, distance ~10 -> ~0 pts.
        distance = abs(dte_days - 10)
        dte_score = max(0.0, 20.0 - (distance / 10.0) * 20.0)
        # Already clamped to [0, 20]

    total_score = ratio_score + notional_score + dte_score
    # Final clamp for safety
    total_score = max(0.0, min(total_score, 100.0))
    return round(total_score, 2)


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
        notional = _calculate_notional(contract, midpoint, volume)
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

        # Compute volume/OI ratio only when OI is present and > 0.
        # If OI is missing or zero, treat ratio as 0.0 for filtering/scoring.
        if open_interest and open_interest > 0:
            volume_oi_ratio = float(volume) / float(open_interest)
        else:
            volume_oi_ratio = 0.0
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
