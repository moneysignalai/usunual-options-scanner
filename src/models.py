from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field, root_validator


class MassiveBaseModel(BaseModel):
    @root_validator(pre=True)
    def normalize_massive_keys(cls, values):
        if not isinstance(values, dict):
            return values

        normalized = dict(values)

        def _map_key(old_key: str, new_key: str) -> None:
            if old_key in normalized and new_key not in normalized:
                normalized[new_key] = normalized.pop(old_key)

        _map_key("openInterest", "open_interest")
        _map_key("openinterest", "open_interest")
        _map_key("prevDay", "prev_day")
        _map_key("lastTrade", "last_trade")
        _map_key("lastQuote", "last_quote")
        _map_key("impliedVolatility", "implied_volatility")
        _map_key("breakEvenPrice", "break_even_price")
        _map_key("sharesPerContract", "shares_per_contract")
        _map_key("strikePrice", "strike_price")
        _map_key("expirationDate", "expiration_date")
        _map_key("contractType", "contract_type")
        _map_key("exerciseStyle", "exercise_style")
        _map_key("relativeVolume", "rvol")
        _map_key("relative_volume", "rvol")
        _map_key("last_price", "last")
        _map_key("tradeCount", "trades_count")
        _map_key("tradesCount", "trades_count")
        _map_key("trades", "trades_count")

        return normalized

    class Config:
        allow_population_by_field_name = True
        extra = "ignore"


class OptionContractDay(MassiveBaseModel):
    change: Optional[float] = None
    change_percent: Optional[float] = None
    close: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    open: Optional[float] = None
    open_interest: Optional[int] = Field(None, alias="open_interest")
    previous_close: Optional[float] = None
    volume: Optional[int] = None
    vwap: Optional[float] = None
    last_updated: Optional[int] = None


class OptionContractDetails(MassiveBaseModel):
    contract_type: Optional[str] = None
    exercise_style: Optional[str] = None
    expiration_date: Optional[str] = None
    shares_per_contract: Optional[int] = None
    strike_price: Optional[float] = None
    ticker: str


class OptionContractGreeks(MassiveBaseModel):
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None


class OptionContractQuote(MassiveBaseModel):
    ask: Optional[float] = None
    ask_size: Optional[int] = None
    bid: Optional[float] = None
    bid_size: Optional[int] = None
    midpoint: Optional[float] = None
    last_updated: Optional[int] = None
    timeframe: Optional[str] = None


class OptionContractTrade(MassiveBaseModel):
    price: Optional[float] = None
    size: Optional[int] = None
    exchange: Optional[int] = None
    last_updated: Optional[int] = None


class UnderlyingAssetSnapshot(MassiveBaseModel):
    ticker: Optional[str] = None
    last_quote: Optional[OptionContractQuote] = None


class OptionContractSnapshot(MassiveBaseModel):
    break_even_price: Optional[float] = None
    day: Optional[OptionContractDay] = None
    details: OptionContractDetails
    greeks: Optional[OptionContractGreeks] = None
    implied_volatility: Optional[float] = None
    last_price: Optional[float] = Field(None, alias="last")
    last_trade: Optional[OptionContractTrade] = None
    last_quote: Optional[OptionContractQuote] = None
    notional: Optional[float] = None
    open_interest: Optional[int] = Field(None, alias="open_interest")
    prev_day: Optional[OptionContractDay] = Field(None, alias="prev_day")
    rvol: Optional[float] = None
    trades_count: Optional[int] = None
    volume: Optional[int] = None
    underlying_asset: Optional[UnderlyingAssetSnapshot] = None


class OptionChainSnapshotResponse(MassiveBaseModel):
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
    volume_oi_ratio: Optional[float]
    rvol: Optional[float]
    dte_days: int
    score: float

    is_sweep: bool = False
    flow_type: str = "STANDARD"
    debug_alert: bool = False

    class Config:
        extra = "ignore"
