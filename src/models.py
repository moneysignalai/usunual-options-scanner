from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel


class OptionContractDay(BaseModel):
    change: Optional[float] = None
    change_percent: Optional[float] = None
    close: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    open: Optional[float] = None
    previous_close: Optional[float] = None
    volume: Optional[int] = None
    vwap: Optional[float] = None
    last_updated: Optional[int] = None


class OptionContractDetails(BaseModel):
    contract_type: Optional[str] = None
    exercise_style: Optional[str] = None
    expiration_date: Optional[str] = None
    shares_per_contract: Optional[int] = None
    strike_price: Optional[float] = None
    ticker: str


class OptionContractGreeks(BaseModel):
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None


class OptionContractQuote(BaseModel):
    ask: Optional[float] = None
    ask_size: Optional[int] = None
    bid: Optional[float] = None
    bid_size: Optional[int] = None
    midpoint: Optional[float] = None
    last_updated: Optional[int] = None
    timeframe: Optional[str] = None


class UnderlyingAssetSnapshot(BaseModel):
    ticker: Optional[str] = None
    last_quote: Optional[OptionContractQuote] = None


class OptionContractSnapshot(BaseModel):
    break_even_price: Optional[float] = None
    day: Optional[OptionContractDay] = None
    details: OptionContractDetails
    greeks: Optional[OptionContractGreeks] = None
    implied_volatility: Optional[float] = None
    last_quote: Optional[OptionContractQuote] = None
    underlying_asset: Optional[UnderlyingAssetSnapshot] = None


class OptionChainSnapshotResponse(BaseModel):
    results: List[OptionContractSnapshot] = []


class UnusualOptionsCandidate(BaseModel):
    options_ticker: str
    underlying_ticker: str
    direction: str
    expiration_date: date
    strike: float
    contract_type: str
    last_price: Optional[float]
    volume: Optional[int]
    open_interest: Optional[int]
    notional: float
    volume_oi_ratio: float
    dte_days: int
    score: float

    is_sweep: bool = False
    flow_type: str = "STANDARD"
    debug_alert: bool = False

    class Config:
        extra = "ignore"
