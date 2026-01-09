from __future__ import annotations

import math
from datetime import date
from typing import List

from .config import Settings
from .models import OptionChainSnapshot, OptionContractSnapshot, UnusualOptionsCandidate


def _calculate_mid_price(contract: OptionContractSnapshot) -> float | None:
    if contract.bid is None or contract.ask is None:
        return None
    return (contract.bid + contract.ask) / 2


def _calculate_notional(price: float | None, volume: int | None) -> float:
    if price is None or volume is None:
        return 0.0
    return price * volume * 100


def _calculate_ratio(volume: int | None, open_interest: int | None) -> float:
    if volume is None or volume == 0:
        return 0.0
    if open_interest is None or open_interest == 0:
        return float("inf")
    return volume / open_interest


def _calculate_score(notional: float, ratio: float, dte_days: int, max_dte: int) -> float:
    ratio_capped = min(ratio, 10.0)
    notional_log = math.log10(max(notional, 1.0))
    dte_bonus = 0.0
    if max_dte > 0:
        dte_bonus = max((max_dte - dte_days) / max_dte, 0.0)
    return ratio_capped + notional_log + dte_bonus


def _detect_sweep(
    contract: OptionContractSnapshot,
    notional: float,
    ratio: float,
    min_notional: float,
) -> bool:
    if contract.sweep is True:
        return True

    volume = contract.volume or 0
    open_interest = contract.open_interest or 0
    aggressive_volume = volume >= 5 * open_interest if open_interest > 0 else ratio >= 3.0
    notional_ok = notional >= 2 * min_notional

    mid_price = _calculate_mid_price(contract)
    if mid_price is not None and contract.last_price is not None:
        price_ok = contract.last_price >= mid_price
    else:
        price_ok = True

    return aggressive_volume and notional_ok and price_ok


def find_unusual_activity(
    chain: OptionChainSnapshot,
    settings: Settings,
) -> List[UnusualOptionsCandidate]:
    candidates: List[UnusualOptionsCandidate] = []
    today = date.today()

    for contract in chain.options:
        if not contract.expiration_date or not contract.contract_type:
            continue

        dte_days = (contract.expiration_date - today).days
        if dte_days < settings.unusual_min_dte_days or dte_days > settings.unusual_max_dte_days:
            continue

        mid_price = _calculate_mid_price(contract)
        price = contract.last_price or mid_price
        if price is None:
            continue

        notional = _calculate_notional(price, contract.volume)
        if notional < settings.unusual_min_notional:
            continue

        ratio = _calculate_ratio(contract.volume, contract.open_interest)
        if ratio < settings.unusual_min_volume_oi_ratio:
            continue

        score = _calculate_score(notional, ratio, dte_days, settings.unusual_max_dte_days)
        is_sweep = _detect_sweep(contract, notional, ratio, settings.unusual_min_notional)
        flow_type = "SWEEP" if is_sweep else "STANDARD"

        candidates.append(
            UnusualOptionsCandidate(
                options_ticker=contract.options_ticker or "",
                underlying_ticker=contract.underlying_ticker or "",
                direction="BULLISH" if contract.contract_type.lower() == "call" else "BEARISH",
                expiration_date=contract.expiration_date,
                strike=float(contract.strike or 0.0),
                contract_type=contract.contract_type.upper(),
                last_price=contract.last_price,
                volume=contract.volume,
                open_interest=contract.open_interest,
                notional=notional,
                volume_oi_ratio=ratio,
                dte_days=dte_days,
                score=score,
                is_sweep=is_sweep,
                flow_type=flow_type,
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates
