from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Iterable, List

from .config import Settings
from .models import OptionChainSnapshot, OptionContractSnapshot, UnusualOptionsCandidate

logger = logging.getLogger("strategy")


@dataclass(frozen=True)
class UnusualThresholds:
    min_dte_days: int
    max_dte_days: int
    min_notional: float
    min_volume: int
    min_open_interest: int
    min_volume_oi_ratio: float
    min_trade_count: int
    min_trade_size: int
    min_rvol: float
    min_iv_pctile: float
    max_otm_pct: float
    spread_threshold_bps: float
    min_unusual_score: float


def _get_effective_thresholds(settings: Settings) -> UnusualThresholds:
    if settings.debug_mode:
        return UnusualThresholds(
            min_dte_days=0,
            max_dte_days=max(settings.unusual_max_dte_days, 60),
            min_notional=min(settings.unusual_min_notional, 1_000.0),
            min_volume=min(settings.unusual_min_volume, 1),
            min_open_interest=min(settings.unusual_min_open_interest, 0),
            min_volume_oi_ratio=min(settings.unusual_min_volume_oi_ratio, 0.0),
            min_trade_count=min(settings.unusual_min_trade_count, 0),
            min_trade_size=min(settings.unusual_min_trade_size, 0),
            min_rvol=min(settings.unusual_min_rvol, 0.0),
            min_iv_pctile=min(settings.unusual_min_iv_pctile, 0.0),
            max_otm_pct=max(settings.unusual_max_otm_pct, 0.0),
            spread_threshold_bps=max(settings.unusual_spread_threshold_bps, 0.0),
            min_unusual_score=min(settings.unusual_min_unusual_score, 0.0),
        )

    return UnusualThresholds(
        min_dte_days=settings.unusual_min_dte_days,
        max_dte_days=settings.unusual_max_dte_days,
        min_notional=settings.unusual_min_notional,
        min_volume=settings.unusual_min_volume,
        min_open_interest=settings.unusual_min_open_interest,
        min_volume_oi_ratio=settings.unusual_min_volume_oi_ratio,
        min_trade_count=settings.unusual_min_trade_count,
        min_trade_size=settings.unusual_min_trade_size,
        min_rvol=settings.unusual_min_rvol,
        min_iv_pctile=settings.unusual_min_iv_pctile,
        max_otm_pct=settings.unusual_max_otm_pct,
        spread_threshold_bps=settings.unusual_spread_threshold_bps,
        min_unusual_score=settings.unusual_min_unusual_score,
    )


def _calculate_mid_price(contract: OptionContractSnapshot) -> float | None:
    if contract.bid is None or contract.ask is None:
        return None
    return (contract.bid + contract.ask) / 2


def _resolve_underlying_price(
    contract: OptionContractSnapshot, chain: OptionChainSnapshot
) -> float | None:
    return contract.underlying_price or chain.underlying_price


def _calculate_notional(
    contract: OptionContractSnapshot, price: float | None, volume: int | None
) -> float:
    if contract.notional is not None and contract.notional > 0:
        return float(contract.notional)
    if price is None or volume is None:
        return 0.0
    return price * volume * 100


def _calculate_ratio(volume: int | None, open_interest: int | None) -> float:
    if volume is None or volume == 0:
        return 0.0
    if open_interest is None or open_interest == 0:
        return 0.0
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


def _candidate_from_contract(
    contract: OptionContractSnapshot,
    chain: OptionChainSnapshot,
    notional: float,
    ratio: float,
    dte_days: int,
    score: float,
    is_sweep: bool,
    flow_type: str,
    debug_alert: bool = False,
) -> UnusualOptionsCandidate:
    return UnusualOptionsCandidate(
        options_ticker=contract.options_ticker or "",
        underlying_ticker=contract.underlying_ticker or chain.underlying_symbol or "",
        direction="BULLISH" if (contract.contract_type or "").lower() == "call" else "BEARISH",
        expiration_date=contract.expiration_date,
        strike=float(contract.strike or 0.0),
        contract_type=(contract.contract_type or "").upper(),
        last_price=contract.last_price,
        volume=contract.volume,
        open_interest=contract.open_interest,
        notional=notional,
        volume_oi_ratio=ratio,
        dte_days=dte_days,
        score=score,
        is_sweep=is_sweep,
        flow_type=flow_type,
        debug_alert=debug_alert,
    )


def _build_debug_candidates(
    contracts: Iterable[OptionContractSnapshot],
    chain: OptionChainSnapshot,
    max_alerts: int = 2,
) -> List[UnusualOptionsCandidate]:
    scored: List[tuple[float, OptionContractSnapshot, float, float, int]] = []
    today = date.today()

    for contract in contracts:
        if not contract.expiration_date or not contract.contract_type:
            continue

        dte_days = (contract.expiration_date - today).days
        mid_price = _calculate_mid_price(contract)
        price = contract.last_price or mid_price
        if price is None:
            continue

        notional = _calculate_notional(contract, price, contract.volume)
        ratio = _calculate_ratio(contract.volume, contract.open_interest)
        score = _calculate_score(notional, ratio, max(dte_days, 0), max(dte_days, 1))
        scored.append((notional, contract, ratio, score, dte_days))

    scored.sort(key=lambda item: item[0], reverse=True)
    debug_candidates: List[UnusualOptionsCandidate] = []
    for notional, contract, ratio, score, dte_days in scored[:max_alerts]:
        debug_candidates.append(
            _candidate_from_contract(
                contract=contract,
                chain=chain,
                notional=notional,
                ratio=ratio,
                dte_days=dte_days,
                score=score,
                is_sweep=False,
                flow_type="DEBUG",
                debug_alert=True,
            )
        )
    return debug_candidates


def find_unusual_activity(
    chain: OptionChainSnapshot,
    settings: Settings,
) -> List[UnusualOptionsCandidate]:
    candidates: List[UnusualOptionsCandidate] = []
    today = date.today()
    thresholds = _get_effective_thresholds(settings)
    rejection_logs = 0

    for contract in chain.contracts:
        reasons: list[str] = []

        if not contract.expiration_date or not contract.contract_type:
            reasons.append("missing_expiry_or_type")
            if reasons:
                if settings.debug_mode and rejection_logs < 5:
                    logger.debug(
                        "Contract rejected | symbol=%s | reasons=%s",
                        contract.options_ticker,
                        reasons,
                    )
                    rejection_logs += 1
            continue

        dte_days = (contract.expiration_date - today).days
        if dte_days < thresholds.min_dte_days or dte_days > thresholds.max_dte_days:
            reasons.append("dte")

        volume = contract.volume or 0
        if volume < thresholds.min_volume:
            reasons.append("volume")

        open_interest = contract.open_interest or 0
        if open_interest < thresholds.min_open_interest:
            reasons.append("open_interest")

        if contract.trade_count is not None and contract.trade_count < thresholds.min_trade_count:
            reasons.append("trade_count")

        if contract.trade_size is not None and contract.trade_size < thresholds.min_trade_size:
            reasons.append("trade_size")

        mid_price = _calculate_mid_price(contract)
        price = contract.last_price or mid_price
        if price is None and not contract.notional:
            reasons.append("price")

        notional = _calculate_notional(contract, price, contract.volume)
        if notional < thresholds.min_notional:
            reasons.append("notional")

        ratio = _calculate_ratio(contract.volume, contract.open_interest)
        if ratio < thresholds.min_volume_oi_ratio:
            reasons.append("volume_oi_ratio")

        if contract.rvol is not None and contract.rvol < thresholds.min_rvol:
            reasons.append("rvol")

        if (
            contract.iv_percentile is not None
            and contract.iv_percentile < thresholds.min_iv_pctile
        ):
            reasons.append("iv_pctile")

        if (
            contract.unusual_score is not None
            and contract.unusual_score < thresholds.min_unusual_score
        ):
            reasons.append("unusual_score")

        if thresholds.max_otm_pct > 0:
            underlying_price = _resolve_underlying_price(contract, chain)
            if underlying_price and contract.strike:
                otm_pct = abs((contract.strike - underlying_price) / underlying_price) * 100
                if otm_pct > thresholds.max_otm_pct:
                    reasons.append("otm_pct")

        if thresholds.spread_threshold_bps > 0:
            if contract.bid is not None and contract.ask is not None:
                mid = _calculate_mid_price(contract)
                if mid and mid > 0:
                    spread_bps = (contract.ask - contract.bid) / mid * 10_000
                    if spread_bps > thresholds.spread_threshold_bps:
                        reasons.append("spread_bps")

        if reasons:
            if settings.debug_mode and rejection_logs < 5:
                logger.debug(
                    "Contract rejected | symbol=%s | reasons=%s",
                    contract.options_ticker,
                    reasons,
                )
                rejection_logs += 1
            continue

        score = _calculate_score(notional, ratio, dte_days, thresholds.max_dte_days)
        is_sweep = _detect_sweep(contract, notional, ratio, thresholds.min_notional)
        flow_type = "SWEEP" if is_sweep else "STANDARD"

        candidate = _candidate_from_contract(
            contract=contract,
            chain=chain,
            notional=notional,
            ratio=ratio,
            dte_days=dte_days,
            score=score,
            is_sweep=is_sweep,
            flow_type=flow_type,
        )
        candidates.append(candidate)
        logger.info(
            "Alert created | ticker=%s | strike=%s | expiry=%s | premium=%.2f",
            candidate.underlying_ticker,
            candidate.strike,
            candidate.expiration_date,
            candidate.notional,
        )

    candidates.sort(key=lambda item: item.score, reverse=True)

    if settings.debug_mode and not candidates:
        logger.info("No contracts passed filters | ticker=%s", chain.underlying_symbol)
        debug_candidates = _build_debug_candidates(chain.contracts, chain)
        for candidate in debug_candidates:
            logger.info(
                "Alert created | ticker=%s | strike=%s | expiry=%s | premium=%.2f",
                candidate.underlying_ticker,
                candidate.strike,
                candidate.expiration_date,
                candidate.notional,
            )
        return debug_candidates

    return candidates
