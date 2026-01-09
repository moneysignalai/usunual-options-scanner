from __future__ import annotations

from datetime import date
from typing import List, Optional, Any, Dict

from pydantic.v1 import BaseModel, Field, root_validator


class OptionContractSnapshot(BaseModel):
    options_ticker: Optional[str] = None
    underlying_ticker: Optional[str] = None
    expiration_date: Optional[date] = None
    strike: Optional[float] = None
    contract_type: Optional[str] = None
    last_price: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    sweep: Optional[bool] = None

    @root_validator(pre=True)
    def normalize_fields(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(values, dict):
            return values

        def _first(*keys: str) -> Any:
            for key in keys:
                if key in values and values[key] is not None:
                    return values[key]
            return None

        if values.get("options_ticker") is None:
            values["options_ticker"] = _first(
                "symbol",
                "ticker",
                "options_ticker",
                "contract_symbol",
            )

        if values.get("underlying_ticker") is None:
            values["underlying_ticker"] = _first(
                "underlying_symbol",
                "underlying_ticker",
            )

        if values.get("expiration_date") is None:
            values["expiration_date"] = _first(
                "expiration",
                "expiration_date",
                "exp_date",
            )

        if values.get("strike") is None:
            values["strike"] = _first("strike", "strike_price")

        if values.get("last_price") is None:
            values["last_price"] = _first("last", "last_price", "last_trade_price")

        if values.get("open_interest") is None:
            values["open_interest"] = _first("oi", "open_interest", "openInterest")

        if values.get("volume") is None:
            values["volume"] = _first("volume", "vol")

        return values

    class Config:
        extra = "ignore"


class OptionChainSnapshot(BaseModel):
    underlying_symbol: Optional[str] = None
    timestamp: Optional[str] = None
    contracts: List[OptionContractSnapshot] = Field(default_factory=list)

    class Config:
        extra = "ignore"


class OptionChainSnapshotResponse(BaseModel):
    results: List[OptionChainSnapshot] = Field(default_factory=list)

    class Config:
        extra = "ignore"


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

    class Config:
        extra = "ignore"
